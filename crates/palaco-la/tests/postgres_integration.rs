use std::env;

use chrono::Utc;
use palaco_la::authorization::authorize;
use palaco_la::comet::{AuthorizationInvalidation, AUTHORIZATION_INVALIDATED_EVENT_TYPE};
use palaco_la::domain::{AuthorizationId, AuthorizationStatus, Authority, AuthorityStatus, Decision, DecisionId, DecisionVerdict, Scope};
use palaco_la::domain::AuthorityId;
use palaco_la::revocation::{RevocationReason, RevocationReceipt, REVOCATION_EVENT_TYPE};
use ed25519_dalek::SigningKey;
use sqlx::postgres::PgPoolOptions;
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
}


#[tokio::test]
async fn postgres_persists_canonical_revocation_event() {
    let store = store().await;
    let authority_id = AuthorityId::new(Uuid::new_v4());
    let revocation = RevocationReceipt {
        revocation_id: Uuid::new_v4(),
        authority_id,
        reason: RevocationReason::Explicit,
        occurred_at: Utc::now(),
    };
    let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
    let actor_id = Uuid::new_v4();
    let provenance = Uuid::new_v4();

    let event = store
        .append_revocation(
            &revocation,
            actor_id,
            Some(Uuid::new_v4()),
            None,
            provenance,
            &signer,
        )
        .await
        .expect("revocation event must persist");

    assert_eq!(event.event_type, REVOCATION_EVENT_TYPE);
    assert_eq!(event.aggregate_id.value(), authority_id.value());
    assert_eq!(event.authority_reference, Some(authority_id.value()));
    assert_eq!(event.event_id.value(), revocation.revocation_id);

    let reconstructed = store
        .current_head(event.aggregate_id)
        .await
        .expect("head lookup must succeed")
        .expect("revocation head must exist");

    assert_eq!(reconstructed, event);
    assert_eq!(
        reconstructed.payload_hash,
        palaco_la::Sha256Digest::calculate(&reconstructed.payload)
    );
    assert!(
        palaco_la::CanonicalVerifier::from_key(signer.verifying_key())
            .verify(&reconstructed.payload, &reconstructed.signature)
            .is_ok()
    );
}


#[tokio::test]
async fn postgres_persists_canonical_authorization_invalidation_event() {
    let store = store().await;
    let authority_id = AuthorityId::new(Uuid::new_v4());
    let authorization_id = AuthorizationId::new(Uuid::new_v4());
    let invalidation = AuthorizationInvalidation {
        propagation_id: Uuid::new_v4(),
        revocation_id: Uuid::new_v4(),
        authority_id,
        authorization_id,
        status: AuthorizationStatus::Revoked,
        observed_at: Utc::now(),
    };
    let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
    let actor_id = Uuid::new_v4();
    let provenance = Uuid::new_v4();

    let event = store
        .append_authorization_invalidation(
            &invalidation,
            actor_id,
            Some(Uuid::new_v4()),
            None,
            provenance,
            &signer,
        )
        .await
        .expect("authorization invalidation event must persist");

    assert_eq!(event.event_type, AUTHORIZATION_INVALIDATED_EVENT_TYPE);
    assert_eq!(event.aggregate_id.value(), authorization_id.value());
    assert_eq!(event.authority_reference, Some(authority_id.value()));
    assert_eq!(event.event_id.value(), invalidation.propagation_id);

    let reconstructed = store
        .current_head(event.aggregate_id)
        .await
        .expect("head lookup must succeed")
        .expect("authorization invalidation head must exist");

    assert_eq!(reconstructed, event);
    assert_eq!(
        reconstructed.payload_hash,
        palaco_la::Sha256Digest::calculate(&reconstructed.payload)
    );
    assert!(
        palaco_la::CanonicalVerifier::from_key(signer.verifying_key())
            .verify(&reconstructed.payload, &reconstructed.signature)
            .is_ok()
    );
}


#[tokio::test]
async fn postgres_reconstructs_active_authorizations_and_comet_invalidates_them_collectively() {
    let store = store().await;
    let authority_id = AuthorityId::new(Uuid::new_v4());
    let authority = Authority {
        id: authority_id,
        scope: Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned(), "write".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        },
        status: AuthorityStatus::Active,
    };
    let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
    let actor_id = Uuid::new_v4();
    let provenance = Uuid::new_v4();

    let first = authorize(
        Decision {
            id: DecisionId::new(Uuid::new_v4()),
            question_id: palaco_la::QuestionId::new(Uuid::new_v4()),
            verdict: DecisionVerdict::Allow,
        },
        authority.clone(),
        authority.scope.clone(),
        AuthorizationId::new(Uuid::new_v4()),
    )
    .expect("authorization evaluation must succeed")
    .authorization;

    let second = authorize(
        Decision {
            id: DecisionId::new(Uuid::new_v4()),
            question_id: palaco_la::QuestionId::new(Uuid::new_v4()),
            verdict: DecisionVerdict::Allow,
        },
        authority.clone(),
        Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        },
        AuthorizationId::new(Uuid::new_v4()),
    )
    .expect("authorization evaluation must succeed")
    .authorization;

    store
        .append_authorization_issued(
            &first,
            actor_id,
            None,
            None,
            provenance,
            &signer,
        )
        .await
        .expect("first authorization issuance must persist");
    store
        .append_authorization_issued(
            &second,
            actor_id,
            None,
            None,
            provenance,
            &signer,
        )
        .await
        .expect("second authorization issuance must persist");

    let active = store
        .active_authorization_ids_for_authority(authority_id)
        .await
        .expect("active authorization reconstruction must succeed");
    assert_eq!(active, vec![first.id, second.id]);

    let revocation = RevocationReceipt {
        revocation_id: Uuid::new_v4(),
        authority_id,
        reason: RevocationReason::Explicit,
        occurred_at: Utc::now(),
    };
    let revocation_event = store
        .append_revocation(
            &revocation,
            actor_id,
            None,
            None,
            provenance,
            &signer,
        )
        .await
        .expect("authority revocation must persist");

    let invalidations = store
        .invalidate_active_authorizations_for_revocation(
            &revocation,
            actor_id,
            None,
            Some(revocation_event.event_id),
            provenance,
            &signer,
            Utc::now(),
        )
        .await
        .expect("COMET bulk invalidation must persist");
    assert_eq!(invalidations.len(), 2);
    assert!(invalidations.iter().all(|event| {
        event.event_type == AUTHORIZATION_INVALIDATED_EVENT_TYPE
            && event.authority_reference == Some(authority_id.value())
    }));

    let active_after = store
        .active_authorization_ids_for_authority(authority_id)
        .await
        .expect("active authorization reconstruction must succeed");
    assert!(active_after.is_empty());
}
