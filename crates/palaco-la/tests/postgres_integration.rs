use std::env;

use chrono::Utc;
use ed25519_dalek::SigningKey;
use palaco_la::authorization::authorize;
use palaco_la::execution::{gate, ExecutionGateError, ExecutionRequest};
use palaco_la::replay::replay_authorization_history;
use palaco_la::comet::{AuthorizationInvalidation, AUTHORIZATION_INVALIDATED_EVENT_TYPE};
use palaco_la::domain::{
    AuthorizationId, AuthorizationStatus, Authority, AuthorityId, AuthorityStatus, Decision,
    DecisionId, DecisionVerdict, Scope,
};
use palaco_la::revocation::{
    RevocationReason, RevocationReceipt, REVOCATION_EVENT_TYPE,
};
use sqlx::postgres::PgPoolOptions;
use uuid::Uuid;

use palaco_la::{
    AggregateId, CanonicalBytes, CanonicalSigner, EventEnvelope, EventId, EventStore,
    EventStoreError, PgEventStore, SchemaVersion, Sequence,
};

fn database_url() -> Result<String, String> {
    env::var("DATABASE_URL").map_err(|_| "DATABASE_URL must be supplied".to_owned())
}

async fn store() -> Result<PgEventStore, String> {
    let url = database_url()?;
    let pool = PgPoolOptions::new()
        .max_connections(8)
        .connect(&url)
        .await
        .map_err(|error| format!("PostgreSQL connection failed: {error}"))?;
    let store = PgEventStore::new(pool);
    store
        .migrate()
        .await
        .map_err(|error| format!("L.A. migrations failed: {error:?}"))?;
    Ok(store)
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
async fn postgres_golden_path_persists_and_reconstructs_exact_events() -> Result<(), String> {
    let store = store().await?;
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"question-1");

    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .map_err(|error| format!("genesis append failed: {error:?}"))?;

    let head = store
        .current_head(aggregate_id)
        .await
        .map_err(|error| format!("head lookup failed: {error:?}"))?
        .ok_or_else(|| "head must exist".to_owned())?;
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
        .map_err(|error| format!("second append failed: {error:?}"))?;

    let all = store
        .load(aggregate_id)
        .await
        .map_err(|error| format!("load failed: {error:?}"))?;
    assert_eq!(all, vec![first.clone(), second.clone()]);

    let after_first = store
        .load_after(aggregate_id, Sequence::genesis())
        .await
        .map_err(|error| format!("load_after failed: {error:?}"))?;
    assert_eq!(after_first, vec![second.clone()]);

    assert_eq!(
        store
            .current_head(aggregate_id)
            .await
            .map_err(|error| format!("head lookup failed: {error:?}"))?,
        Some(second)
    );
    Ok(())
}

#[tokio::test]
async fn postgres_rejects_sequence_and_predecessor_conflicts() -> Result<(), String> {
    let store = store().await?;
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"conflict-1");
    store
        .append(aggregate_id, Sequence::genesis(), None, first)
        .await
        .map_err(|error| format!("genesis append failed: {error:?}"))?;

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
    Ok(())
}

#[tokio::test]
async fn postgres_rejects_duplicate_event_id() -> Result<(), String> {
    let store = store().await?;
    let aggregate_a = AggregateId::new(Uuid::new_v4());
    let aggregate_b = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_a, Sequence::genesis(), None, b"duplicate");
    store
        .append(aggregate_a, Sequence::genesis(), None, first.clone())
        .await
        .map_err(|error| format!("first append failed: {error:?}"))?;

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
    Ok(())
}

#[tokio::test]
async fn postgres_rejects_direct_event_mutation() -> Result<(), String> {
    let store = store().await?;
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"immutable");
    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .map_err(|error| format!("append failed: {error:?}"))?;

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
    Ok(())
}

#[tokio::test]
async fn postgres_serializes_concurrent_appends_per_aggregate() -> Result<(), String> {
    let store = store().await?;
    let pool = store.pool().clone();
    let aggregate_id = AggregateId::new(Uuid::new_v4());
    let first = event(aggregate_id, Sequence::genesis(), None, b"concurrency-1");
    store
        .append(aggregate_id, Sequence::genesis(), None, first.clone())
        .await
        .map_err(|error| format!("genesis append failed: {error:?}"))?;

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
    assert_eq!(
        successes, 1,
        "exactly one concurrent append may claim sequence 2"
    );

    let events = store
        .load(aggregate_id)
        .await
        .map_err(|error| format!("load failed: {error:?}"))?;
    assert_eq!(events.len(), 2);

    let head_sequence: i64 = sqlx::query_scalar(
        "SELECT current_sequence FROM la.aggregate_heads WHERE aggregate_id = $1",
    )
    .bind(aggregate_id.value())
    .fetch_one(store.pool())
    .await
    .map_err(|error| format!("aggregate head lookup failed: {error}"))?;
    assert_eq!(head_sequence, 2);
    Ok(())
}

#[tokio::test]
async fn postgres_persists_canonical_revocation_event() -> Result<(), String> {
    let store = store().await?;
    let authority_id = AuthorityId::new(Uuid::new_v4());
    let revocation = RevocationReceipt {
        revocation_id: Uuid::new_v4(),
        authority_id,
        reason: RevocationReason::Explicit,
        occurred_at: Utc::now(),
    };
    let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));

    let event = store
        .append_revocation(
            &revocation,
            Uuid::new_v4(),
            Some(Uuid::new_v4()),
            None,
            Uuid::new_v4(),
            &signer,
        )
        .await
        .map_err(|error| format!("revocation event failed: {error:?}"))?;

    assert_eq!(event.event_type, REVOCATION_EVENT_TYPE);
    assert_eq!(event.aggregate_id.value(), authority_id.value());
    assert_eq!(event.authority_reference, Some(authority_id.value()));
    assert_eq!(event.event_id.value(), revocation.revocation_id);

    let reconstructed = store
        .current_head(event.aggregate_id)
        .await
        .map_err(|error| format!("head lookup failed: {error:?}"))?
        .ok_or_else(|| "revocation head must exist".to_owned())?;

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
    Ok(())
}

#[tokio::test]
async fn postgres_persists_canonical_authorization_invalidation_event() -> Result<(), String> {
    let store = store().await?;
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

    let event = store
        .append_authorization_invalidation(
            &invalidation,
            Uuid::new_v4(),
            Some(Uuid::new_v4()),
            None,
            Uuid::new_v4(),
            &signer,
        )
        .await
        .map_err(|error| format!("authorization invalidation failed: {error:?}"))?;

    assert_eq!(event.event_type, AUTHORIZATION_INVALIDATED_EVENT_TYPE);
    assert_eq!(event.aggregate_id.value(), authorization_id.value());
    assert_eq!(event.authority_reference, Some(authority_id.value()));
    assert_eq!(event.event_id.value(), invalidation.propagation_id);

    let reconstructed = store
        .current_head(event.aggregate_id)
        .await
        .map_err(|error| format!("head lookup failed: {error:?}"))?
        .ok_or_else(|| "authorization invalidation head must exist".to_owned())?;

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
    Ok(())
}

#[tokio::test]
async fn postgres_replay_of_revoked_authorization_cannot_create_execution_permit()
    -> Result<(), String>
{
    let store = store().await?;
    let authority_id = AuthorityId::new(Uuid::new_v4());
    let authority = Authority {
        id: authority_id,
        scope: Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        },
        status: AuthorityStatus::Active,
    };
    let authorization = authorize(
        Decision {
            id: DecisionId::new(Uuid::new_v4()),
            question_id: palaco_la::QuestionId::new(Uuid::new_v4()),
            verdict: DecisionVerdict::Allow,
        },
        authority.clone(),
        authority.scope.clone(),
        AuthorizationId::new(Uuid::new_v4()),
    )
    .map_err(|error| format!("authorization evaluation failed: {error:?}"))?
    .authorization;
    let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));

    store
        .append_authorization_issued(
            &authorization,
            Uuid::new_v4(),
            None,
            None,
            Uuid::new_v4(),
            &signer,
        )
        .await
        .map_err(|error| format!("authorization issuance failed: {error:?}"))?;

    let revocation = RevocationReceipt {
        revocation_id: Uuid::new_v4(),
        authority_id,
        reason: RevocationReason::Explicit,
        occurred_at: Utc::now(),
    };
    let revocation_event = store
        .append_revocation(
            &revocation,
            Uuid::new_v4(),
            None,
            None,
            Uuid::new_v4(),
            &signer,
        )
        .await
        .map_err(|error| format!("authority revocation failed: {error:?}"))?;

    let invalidation = palaco_la::comet::propagate_revocation(
        &revocation,
        &authorization,
        Utc::now(),
    )
    .map_err(|error| format!("COMET propagation failed: {error:?}"))?;
    store
        .append_authorization_invalidation(
            &invalidation,
            Uuid::new_v4(),
            None,
            Some(revocation_event.event_id),
            Uuid::new_v4(),
            &signer,
        )
        .await
        .map_err(|error| format!("authorization invalidation failed: {error:?}"))?;

    let history = store
        .load(AggregateId::new(authorization.id.value()))
        .await
        .map_err(|error| format!("authorization history load failed: {error:?}"))?;
    let verifier = palaco_la::CanonicalVerifier::from_key(signer.verifying_key());
    let replay = replay_authorization_history(&history, &verifier)
        .map_err(|error| format!("authorization replay failed: {error:?}"))?;

    assert_eq!(
        replay.authorization.status,
        AuthorizationStatus::Revoked
    );

    let request = ExecutionRequest {
        operation: "read".to_owned(),
        scope: authorization.scope.clone(),
    };
    assert_eq!(
        gate(&replay.authorization, request),
        Err(ExecutionGateError::AuthorizationInactive)
    );
    Ok(())
}

#[tokio::test]
async fn postgres_reconstructs_active_authorizations_and_comet_invalidates_them_collectively()
    -> Result<(), String>
{
    let store = store().await?;
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
    .map_err(|error| format!("first authorization evaluation failed: {error:?}"))?
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
    .map_err(|error| format!("second authorization evaluation failed: {error:?}"))?
    .authorization;

    store
        .append_authorization_issued(&first, Uuid::new_v4(), None, None, Uuid::new_v4(), &signer)
        .await
        .map_err(|error| format!("first issuance failed: {error:?}"))?;
    store
        .append_authorization_issued(&second, Uuid::new_v4(), None, None, Uuid::new_v4(), &signer)
        .await
        .map_err(|error| format!("second issuance failed: {error:?}"))?;

    let active = store
        .active_authorization_ids_for_authority(authority_id)
        .await
        .map_err(|error| format!("active reconstruction failed: {error:?}"))?;
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
            Uuid::new_v4(),
            None,
            None,
            Uuid::new_v4(),
            &signer,
        )
        .await
        .map_err(|error| format!("authority revocation failed: {error:?}"))?;

    let invalidations = store
        .invalidate_active_authorizations_for_revocation(
            &revocation,
            Uuid::new_v4(),
            None,
            Some(revocation_event.event_id),
            Uuid::new_v4(),
            &signer,
            Utc::now(),
        )
        .await
        .map_err(|error| format!("COMET bulk invalidation failed: {error:?}"))?;
    assert_eq!(invalidations.len(), 2);
    assert!(invalidations.iter().all(|event| {
        event.event_type == AUTHORIZATION_INVALIDATED_EVENT_TYPE
            && event.authority_reference == Some(authority_id.value())
    }));

    let active_after = store
        .active_authorization_ids_for_authority(authority_id)
        .await
        .map_err(|error| format!("post-revocation reconstruction failed: {error:?}"))?;
    assert!(active_after.is_empty());
    Ok(())
}
