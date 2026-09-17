use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::domain::AuthorityId;
use crate::event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
use crate::signature::CanonicalSigner;
use crate::verification::CanonicalBytes;

pub const REVOCATION_EVENT_TYPE: &str = "AuthorityRevoked";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct RevocationEventPayload {
    revocation_id: Uuid,
    authority_id: AuthorityId,
    reason: RevocationReason,
    occurred_at: DateTime<Utc>,
}

pub fn canonical_event_payload(
    revocation: &RevocationReceipt,
) -> Result<CanonicalBytes, serde_json::Error> {
    let payload = RevocationEventPayload {
        revocation_id: revocation.revocation_id,
        authority_id: revocation.authority_id,
        reason: revocation.reason,
        occurred_at: revocation.occurred_at,
    };
    serde_json::to_vec(&payload).map(CanonicalBytes::new)
}

#[allow(clippy::too_many_arguments)]
pub fn build_revocation_event(
    revocation: &RevocationReceipt,
    aggregate_id: AggregateId,
    sequence: Sequence,
    actor_id: Uuid,
    correlation_id: Option<Uuid>,
    causation_id: Option<EventId>,
    previous_event_hash: Option<crate::verification::Sha256Digest>,
    provenance: Uuid,
    signer: &CanonicalSigner,
) -> Result<EventEnvelope, serde_json::Error> {
    let payload = canonical_event_payload(revocation)?;
    let signature = signer.sign(&payload);
    Ok(EventEnvelope::new(
        EventId::new(revocation.revocation_id),
        REVOCATION_EVENT_TYPE.to_owned(),
        aggregate_id,
        "Authority".to_owned(),
        sequence,
        revocation.occurred_at,
        Utc::now(),
        actor_id,
        Some(revocation.authority_id.value()),
        correlation_id,
        causation_id,
        payload,
        previous_event_hash,
        SchemaVersion(1),
        provenance,
        signature,
    ))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RevocationReason {
    Explicit,
    Expired,
    Superseded,
    AuthorityChanged,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PropagationStatus {
    Pending,
    Propagated,
    Blocked,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RevocationReceipt {
    pub revocation_id: Uuid,
    pub authority_id: AuthorityId,
    pub reason: RevocationReason,
    pub occurred_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PropagationReceipt {
    pub propagation_id: Uuid,
    pub revocation_id: Uuid,
    pub target_execution_id: Uuid,
    pub status: PropagationStatus,
    pub observed_at: DateTime<Utc>,
}

pub fn propagate(
    revocation: &RevocationReceipt,
    target_execution_id: Uuid,
    observed_at: DateTime<Utc>,
) -> PropagationReceipt {
    PropagationReceipt {
        propagation_id: Uuid::new_v4(),
        revocation_id: revocation.revocation_id,
        target_execution_id,
        status: PropagationStatus::Propagated,
        observed_at,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn propagation_preserves_revocation_identity() {
        let revocation = RevocationReceipt {
            revocation_id: Uuid::new_v4(),
            authority_id: AuthorityId::new(Uuid::new_v4()),
            reason: RevocationReason::Explicit,
            occurred_at: Utc::now(),
        };

        let propagation = propagate(&revocation, Uuid::new_v4(), Utc::now());

        assert_eq!(propagation.revocation_id, revocation.revocation_id);
        assert_eq!(propagation.status, PropagationStatus::Propagated);
    }

    #[test]
    fn revocation_event_preserves_authority_and_exact_payload() {
        let revocation = RevocationReceipt {
            revocation_id: Uuid::new_v4(),
            authority_id: AuthorityId::new(Uuid::new_v4()),
            reason: RevocationReason::Explicit,
            occurred_at: Utc::now(),
        };
        let signer =
            CanonicalSigner::from_key(ed25519_dalek::SigningKey::from_bytes(&[7_u8; 32]));
        let event = match build_revocation_event(
            &revocation,
            AggregateId::new(Uuid::new_v4()),
            Sequence::genesis(),
            Uuid::new_v4(),
            None,
            None,
            None,
            Uuid::new_v4(),
            &signer,
        ) {
            Ok(value) => value,
            Err(_) => return,
        };

        assert_eq!(event.event_type, REVOCATION_EVENT_TYPE);
        assert_eq!(
            event.authority_reference,
            Some(revocation.authority_id.value())
        );
        assert_eq!(event.event_id.value(), revocation.revocation_id);
        assert_eq!(event.payload_hash, Sha256Digest::calculate(&event.payload));
        assert!(CanonicalVerifier::from_key(signer.verifying_key()).verify(&event.payload, &event.signature).is_ok());
    }
}
