use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::domain::{AuthorityId, Authorization, AuthorizationId, AuthorizationStatus};
use crate::event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
use crate::revocation::RevocationReceipt;
use crate::signature::CanonicalSigner;
use crate::verification::CanonicalBytes;

pub const AUTHORIZATION_INVALIDATED_EVENT_TYPE: &str = "AuthorizationInvalidated";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CometPropagationStatus {
    Propagated,
    Blocked,
    AlreadyRevoked,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthorizationInvalidation {
    pub propagation_id: Uuid,
    pub revocation_id: Uuid,
    pub authority_id: AuthorityId,
    pub authorization_id: AuthorizationId,
    pub status: AuthorizationStatus,
    pub observed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CometError {
    AuthorityMismatch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct AuthorizationInvalidationEventPayload {
    propagation_id: Uuid,
    revocation_id: Uuid,
    authority_id: AuthorityId,
    authorization_id: AuthorizationId,
    status: AuthorizationStatus,
    observed_at: DateTime<Utc>,
}

pub fn canonical_invalidation_payload(
    invalidation: &AuthorizationInvalidation,
) -> Result<CanonicalBytes, serde_json::Error> {
    let payload = AuthorizationInvalidationEventPayload {
        propagation_id: invalidation.propagation_id,
        revocation_id: invalidation.revocation_id,
        authority_id: invalidation.authority_id,
        authorization_id: invalidation.authorization_id,
        status: invalidation.status,
        observed_at: invalidation.observed_at,
    };
    serde_json::to_vec(&payload).map(CanonicalBytes::new)
}

#[allow(clippy::too_many_arguments)]
pub fn build_authorization_invalidation_event(
    invalidation: &AuthorizationInvalidation,
    aggregate_id: AggregateId,
    sequence: Sequence,
    actor_id: Uuid,
    correlation_id: Option<Uuid>,
    causation_id: Option<EventId>,
    previous_event_hash: Option<crate::verification::Sha256Digest>,
    provenance: Uuid,
    signer: &CanonicalSigner,
) -> Result<EventEnvelope, serde_json::Error> {
    let payload = canonical_invalidation_payload(invalidation)?;
    let signature = signer.sign(&payload);
    Ok(EventEnvelope::new(
        EventId::new(invalidation.propagation_id),
        AUTHORIZATION_INVALIDATED_EVENT_TYPE.to_owned(),
        aggregate_id,
        "Authorization".to_owned(),
        sequence,
        invalidation.observed_at,
        Utc::now(),
        actor_id,
        Some(invalidation.authority_id.value()),
        correlation_id,
        causation_id,
        payload,
        previous_event_hash,
        SchemaVersion(1),
        provenance,
        signature,
    ))
}

pub fn propagate_revocation(
    revocation: &RevocationReceipt,
    authorization: &Authorization,
    observed_at: DateTime<Utc>,
) -> Result<AuthorizationInvalidation, CometError> {
    if authorization.authority_id != revocation.authority_id {
        return Err(CometError::AuthorityMismatch);
    }

    Ok(AuthorizationInvalidation {
        propagation_id: Uuid::new_v4(),
        revocation_id: revocation.revocation_id,
        authority_id: revocation.authority_id,
        authorization_id: authorization.id,
        status: AuthorizationStatus::Revoked,
        observed_at,
    })
}

pub fn apply_invalidation(
    authorization: &Authorization,
    invalidation: &AuthorizationInvalidation,
) -> Authorization {
    if authorization.id == invalidation.authorization_id
        && authorization.authority_id == invalidation.authority_id
        && invalidation.status == AuthorizationStatus::Revoked
    {
        Authorization {
            status: AuthorizationStatus::Revoked,
            ..authorization.clone()
        }
    } else {
        authorization.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{DecisionId, Scope};

    fn authorization(authority_id: AuthorityId, status: AuthorizationStatus) -> Authorization {
        Authorization {
            id: AuthorizationId::new(Uuid::new_v4()),
            decision_id: DecisionId::new(Uuid::new_v4()),
            authority_id,
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["write".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
            status,
        }
    }

    #[test]
    fn revocation_propagates_only_to_bound_authorization() {
        let authority_id = AuthorityId::new(Uuid::new_v4());
        let authorization = authorization(authority_id, AuthorizationStatus::Active);
        let revocation = RevocationReceipt {
            revocation_id: Uuid::new_v4(),
            authority_id,
            reason: crate::revocation::RevocationReason::Explicit,
            occurred_at: Utc::now(),
        };

        let result = propagate_revocation(&revocation, &authorization, Utc::now());
        assert!(result.is_ok());

        let invalidation = match result {
            Ok(value) => value,
            Err(_) => return,
        };
        let invalidated = apply_invalidation(&authorization, &invalidation);
        assert_eq!(invalidated.status, AuthorizationStatus::Revoked);
        assert_eq!(invalidation.revocation_id, revocation.revocation_id);
    }

    #[test]
    fn mismatched_authority_blocks_comet_propagation() {
        let authorization = authorization(
            AuthorityId::new(Uuid::new_v4()),
            AuthorizationStatus::Active,
        );
        let revocation = RevocationReceipt {
            revocation_id: Uuid::new_v4(),
            authority_id: AuthorityId::new(Uuid::new_v4()),
            reason: crate::revocation::RevocationReason::Explicit,
            occurred_at: Utc::now(),
        };

        assert_eq!(
            propagate_revocation(&revocation, &authorization, Utc::now()),
            Err(CometError::AuthorityMismatch)
        );
    }

    #[test]
    fn already_revoked_authorization_remains_revoked() {
        let authority_id = AuthorityId::new(Uuid::new_v4());
        let authorization = authorization(authority_id, AuthorizationStatus::Revoked);
        let revocation = RevocationReceipt {
            revocation_id: Uuid::new_v4(),
            authority_id,
            reason: crate::revocation::RevocationReason::Explicit,
            occurred_at: Utc::now(),
        };

        let result = propagate_revocation(&revocation, &authorization, Utc::now());
        assert!(result.is_ok());
        let invalidation = match result {
            Ok(value) => value,
            Err(_) => return,
        };
        assert_eq!(invalidation.status, AuthorizationStatus::Revoked);
    }

    #[test]
    fn invalidation_event_uses_exact_canonical_payload() {
        let authority_id = AuthorityId::new(Uuid::new_v4());
        let invalidation = AuthorizationInvalidation {
            propagation_id: Uuid::new_v4(),
            revocation_id: Uuid::new_v4(),
            authority_id,
            authorization_id: AuthorizationId::new(Uuid::new_v4()),
            status: AuthorizationStatus::Revoked,
            observed_at: Utc::now(),
        };
        let signer = CanonicalSigner::from_key(ed25519_dalek::SigningKey::from_bytes(&[7_u8; 32]));
        let event = match build_authorization_invalidation_event(
            &invalidation,
            AggregateId::new(invalidation.authorization_id.value()),
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

        assert_eq!(event.event_type, AUTHORIZATION_INVALIDATED_EVENT_TYPE);
        assert_eq!(event.event_id.value(), invalidation.propagation_id);
        assert_eq!(
            event.authority_reference,
            Some(invalidation.authority_id.value())
        );
        assert_eq!(
            event.payload_hash,
            crate::verification::Sha256Digest::calculate(&event.payload)
        );
        assert!(
            crate::CanonicalVerifier::from_key(signer.verifying_key())
                .verify(&event.payload, &event.signature)
                .is_ok()
        );
    }
}
