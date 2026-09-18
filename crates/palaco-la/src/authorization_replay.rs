use serde::Deserialize;

use crate::authorization::AUTHORIZATION_ISSUED_EVENT_TYPE;
use crate::comet::AUTHORIZATION_INVALIDATED_EVENT_TYPE;
use crate::domain::{
    AuthorityId, Authorization, AuthorizationId, AuthorizationStatus, DecisionId, Scope,
};
use crate::event::EventEnvelope;
use crate::replay::{ReplayError, verify_history};
use crate::signature::CanonicalVerifier;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthorizationReplayError {
    Structural(ReplayError),
    InvalidPayload,
    AggregateIdentityMismatch,
    UnsupportedEventType,
    InvalidTransition,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizationReplay {
    pub authorization: Authorization,
    pub applied_events: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
struct AuthorizationIssuedPayload {
    authorization_id: AuthorizationId,
    decision_id: DecisionId,
    authority_id: AuthorityId,
    scope: Scope,
    status: AuthorizationStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
struct AuthorizationInvalidatedPayload {
    authorization_id: AuthorizationId,
    authority_id: AuthorityId,
    status: AuthorizationStatus,
}

pub fn replay_authorization_history(
    events: &[EventEnvelope],
    verifier: &CanonicalVerifier,
) -> Result<AuthorizationReplay, AuthorizationReplayError> {
    verify_history(events, verifier).map_err(AuthorizationReplayError::Structural)?;

    let first = events.first().ok_or(AuthorizationReplayError::Structural(
        ReplayError::EmptyHistory,
    ))?;

    if first.event_type != AUTHORIZATION_ISSUED_EVENT_TYPE {
        return Err(AuthorizationReplayError::InvalidTransition);
    }

    let issued: AuthorizationIssuedPayload = serde_json::from_slice(first.payload.as_slice())
        .map_err(|_| AuthorizationReplayError::InvalidPayload)?;

    if first.aggregate_id.value() != issued.authorization_id.value() {
        return Err(AuthorizationReplayError::AggregateIdentityMismatch);
    }

    let mut authorization = Authorization {
        id: issued.authorization_id,
        decision_id: issued.decision_id,
        authority_id: issued.authority_id,
        scope: issued.scope,
        status: issued.status,
    };

    for event in events.iter().skip(1) {
        if event.aggregate_id.value() != authorization.id.value() {
            return Err(AuthorizationReplayError::AggregateIdentityMismatch);
        }

        match event.event_type.as_str() {
            AUTHORIZATION_INVALIDATED_EVENT_TYPE => {
                let invalidation: AuthorizationInvalidatedPayload =
                    serde_json::from_slice(event.payload.as_slice())
                        .map_err(|_| AuthorizationReplayError::InvalidPayload)?;

                if invalidation.authorization_id != authorization.id
                    || invalidation.authority_id != authorization.authority_id
                {
                    return Err(AuthorizationReplayError::AggregateIdentityMismatch);
                }

                authorization.status = invalidation.status;
            }
            _ => return Err(AuthorizationReplayError::UnsupportedEventType),
        }
    }

    Ok(AuthorizationReplay {
        authorization,
        applied_events: events.len(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::authorization::canonical_authorization_issued_payload;
    use crate::comet::canonical_invalidation_payload;
    use crate::domain::{AuthorityId, AuthorizationId, DecisionId, Scope};
    use crate::event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
    use crate::signature::CanonicalSigner;
    use chrono::Utc;
    use ed25519_dalek::SigningKey;
    use uuid::Uuid;

    fn fixture() -> (Vec<EventEnvelope>, CanonicalVerifier, AuthorizationId) {
        let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
        let authorization_id = AuthorizationId::new(Uuid::new_v4());
        let authority_id = AuthorityId::new(Uuid::new_v4());
        let authorization = Authorization {
            id: authorization_id,
            decision_id: DecisionId::new(Uuid::new_v4()),
            authority_id,
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["read".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
            status: AuthorizationStatus::Active,
        };

        let issued_payload = match canonical_authorization_issued_payload(&authorization) {
            Ok(value) => value,
            Err(_) => {
                return (
                    Vec::new(),
                    CanonicalVerifier::from_key(signer.verifying_key()),
                    authorization_id,
                );
            }
        };
        let issued = EventEnvelope::new(
            EventId::new(authorization.id.value()),
            AUTHORIZATION_ISSUED_EVENT_TYPE.to_owned(),
            AggregateId::new(authorization.id.value()),
            "Authorization".to_owned(),
            Sequence::genesis(),
            Utc::now(),
            Utc::now(),
            Uuid::new_v4(),
            Some(authority_id.value()),
            None,
            None,
            issued_payload.clone(),
            None,
            SchemaVersion(1),
            Uuid::new_v4(),
            signer.sign(&issued_payload),
        );

        let invalidation = crate::comet::AuthorizationInvalidation {
            propagation_id: Uuid::new_v4(),
            revocation_id: Uuid::new_v4(),
            authority_id,
            authorization_id,
            status: AuthorizationStatus::Revoked,
            observed_at: Utc::now(),
        };
        let invalidation_payload = match canonical_invalidation_payload(&invalidation) {
            Ok(value) => value,
            Err(_) => {
                return (
                    vec![issued],
                    CanonicalVerifier::from_key(signer.verifying_key()),
                    authorization_id,
                );
            }
        };
        let second = EventEnvelope::new(
            EventId::new(invalidation.propagation_id),
            AUTHORIZATION_INVALIDATED_EVENT_TYPE.to_owned(),
            AggregateId::new(authorization_id.value()),
            "Authorization".to_owned(),
            Sequence(2),
            invalidation.observed_at,
            Utc::now(),
            Uuid::new_v4(),
            Some(authority_id.value()),
            None,
            Some(issued.event_id),
            invalidation_payload.clone(),
            Some(issued.payload_hash),
            SchemaVersion(1),
            issued.provenance,
            signer.sign(&invalidation_payload),
        );

        (
            vec![issued, second],
            CanonicalVerifier::from_key(signer.verifying_key()),
            authorization_id,
        )
    }

    #[test]
    fn issued_then_invalidated_reconstructs_revoked_state() {
        let (events, verifier, authorization_id) = fixture();
        let result = replay_authorization_history(&events, &verifier);
        assert!(result.is_ok());
        let replay = match result {
            Ok(value) => value,
            Err(_) => return,
        };
        assert_eq!(replay.authorization.id, authorization_id);
        assert_eq!(replay.authorization.status, AuthorizationStatus::Revoked);
        assert_eq!(replay.applied_events, 2);
    }

    #[test]
    fn unknown_lifecycle_event_fails_closed() {
        let (mut events, verifier, _) = fixture();
        events[1].event_type = "UnknownAuthorizationEvent".to_owned();
        assert_eq!(
            replay_authorization_history(&events, &verifier),
            Err(AuthorizationReplayError::UnsupportedEventType)
        );
    }
}
