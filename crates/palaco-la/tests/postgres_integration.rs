use std::env;

use chrono::Utc;
use ed25519_dalek::SigningKey;
use sqlx::{postgres::PgPoolOptions, Row};
use uuid::Uuid;

use palaco_la::{
    AggregateId, CanonicalBytes, CanonicalSigner, EventEnvelope, EventId, EventStore,
    EventStoreError, PgEventStore, SchemaVersion, Sequence,
};

fn database_url() -> String {
    env::var("DATABASE_URL").expect("DATABASE_URL must be supplied by the PostgreSQL CI service")
}

async fn store() -> PgEventStore {
    let pool = PgPoolOptions::new()
        .max_connections(8)
        .connect(&database_url())
        .await
        .expect("PostgreSQL must be reachable");
    let store = PgEventStore::new(pool);
    store.migrate().await.expect("L.A. migrations must apply");
    store
}

fn event(
    aggregate_id: AggregateId,
    sequence: Sequence,
    previous_event_hash: Option<palaco_la::verification::Sha256Digest>,
    payload: &[u8],
) -> EventEnvelope {
    let payload = CanonicalBytes::new(payload.to_vec());
    let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
    let signature = signer.sign(&payload);

    EventEnvelope::new(
        EventId::new(Uuid::new_v4()),
        "QuestionCreated".to_owned(),
        aggregate_id,
        "Question".to_owned(),
        sequence,
        Utc::now(),
        Utc::now(),
        Uuid::new_v4(),
        None,
        Some(Uuid::new_v4()),
        None,
        payload,
        previous_event_hash,
        SchemaVersion(1),
        Uuid::new_v4(),
        signature,
    )
}

#[tokio::test]
async fn postgres_golden_path_persists_and_reconstructs_exact_events() {
    let store = store().await;
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"question-1");

    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .expect("genesis append must succeed");

    let head = store
        .current_head(aggregate_id)
        .await
        .expect("head lookup must succeed")
        .expect("head must exist");
    assert_eq!(head, first);

    let second = event(
        aggregate_id,
        first.sequence.next(),
        Some(first.payload_hash),
        b"question-2",
    );
    store
        .append(
            aggregate_id,
            second.sequence,
            Some(first.payload_hash),
            second.clone(),
        )
        .await
        .expect("second append must succeed");

    let all = store.load(aggregate_id).await.expect("load must succeed");
    assert_eq!(all, vec![first.clone(), second.clone()]);

    let after_first = store
        .load_after(aggregate_id, Sequence::genesis())
        .await
        .expect("load_after must succeed");
    assert_eq!(after_first, vec![second.clone()]);

    assert_eq!(
        store
            .current_head(aggregate_id)
            .await
            .expect("head lookup must succeed"),
        Some(second)
    );
}

#[tokio::test]
async fn postgres_rejects_sequence_and_predecessor_conflicts() {
    let store = store().await;
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"conflict-1");
    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .expect("genesis append must succeed");

    let wrong_sequence = event(aggregate_id, Sequence(9), None, b"wrong-sequence");
    assert!(matches!(
        store
            .append(aggregate_id, Sequence(9), None, wrong_sequence)
            .await,
        Err(EventStoreError::SequenceConflict { .. })
    ));

    let wrong_predecessor = event(aggregate_id, Sequence(2), None, b"wrong-predecessor");
    assert_eq!(
        store
            .append(aggregate_id, Sequence(2), None, wrong_predecessor)
            .await,
        Err(EventStoreError::PredecessorConflict)
    );
}

#[tokio::test]
async fn postgres_rejects_duplicate_event_id() {
    let store = store().await;
    let aggregate_a = AggregateId::new(Uuid::new_v4());
    let aggregate_b = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_a, Sequence::genesis(), None, b"duplicate");
    store
        .append(aggregate_a, Sequence::genesis(), None, first.clone())
        .await
        .expect("first append must succeed");

    let duplicate = EventEnvelope {
        event_id: first.event_id,
        aggregate_id: aggregate_b,
        ..event(aggregate_b, Sequence::genesis(), None, b"duplicate")
    };
    assert_eq!(
        store
            .append(aggregate_b, Sequence::genesis(), None, duplicate)
            .await,
        Err(EventStoreError::DuplicateEvent)
    );
}

#[tokio::test]
async fn postgres_rejects_direct_event_mutation() {
    let store = store().await;
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"immutable");
    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .expect("append must succeed");

    let update = sqlx::query("UPDATE la.events SET event_type = 'Tampered' WHERE event_id = $1")
        .bind(first.event_id.value())
        .execute(store.pool())
        .await;
    assert!(update.is_err(), "UPDATE must be rejected by the append-only trigger");

    let delete = sqlx::query("DELETE FROM la.events WHERE event_id = $1")
        .bind(first.event_id.value())
        .execute(store.pool())
        .await;
    assert!(delete.is_err(), "DELETE must be rejected by the append-only trigger");
}

#[tokio::test]
async fn postgres_serializes_concurrent_appends_per_aggregate() {
    let store = store().await;
    let pool = store.pool().clone();
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"concurrency-1");
    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .expect("genesis append must succeed");

    let left_store = PgEventStore::new(pool.clone());
    let right_store = PgEventStore::new(pool);
    let left = event(aggregate_id, Sequence(2), Some(first.payload_hash), b"left");
    let right = event(aggregate_id, Sequence(2), Some(first.payload_hash), b"right");

    let (left_result, right_result) = tokio::join!(
        left_store.append(aggregate_id, Sequence(2), Some(first.payload_hash), left),
        right_store.append(aggregate_id, Sequence(2), Some(first.payload_hash), right),
    );

    let successes = [left_result.as_ref(), right_result.as_ref()]
        .into_iter()
        .filter(|result| result.is_ok())
        .count();
    assert_eq!(successes, 1, "exactly one concurrent append may claim sequence 2");

    let events = store.load(aggregate_id).await.expect("load must succeed");
    assert_eq!(events.len(), 2);

    let head_sequence: i64 = sqlx::query_scalar(
        "SELECT current_sequence FROM la.aggregate_heads WHERE aggregate_id = $1",
    )
    .bind(aggregate_id.value())
    .fetch_one(store.pool())
    .await
    .expect("aggregate head must exist");
    assert_eq!(head_sequence, 2);

    let _ = sqlx::query("SELECT event_id FROM la.events WHERE aggregate_id = $1")
        .bind(aggregate_id.value())
        .fetch_all(store.pool())
        .await
        .expect("events must remain queryable");

    let _ = sqlx::query("SELECT aggregate_id FROM la.aggregate_heads WHERE aggregate_id = $1")
        .bind(aggregate_id.value())
        .fetch_one(store.pool())
        .await
        .expect("head row must remain queryable");

    let _ = Row::try_get::<Uuid, _>;
}
