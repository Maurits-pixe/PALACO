use crate::domain::{
    Authority, AuthorityStatus, Authorization, AuthorizationId, AuthorizationStatus, Decision,
    Scope,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthorizationEvaluationError {
    DecisionNotAllow,
    AuthorityInactive,
    ScopeExpansion,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizationEvaluation {
    pub authorization: Authorization,
    pub authority: Authority,
}

pub fn authorize(
    decision: Decision,
    authority: Authority,
    requested_scope: Scope,
    authorization_id: AuthorizationId,
) -> Result<AuthorizationEvaluation, AuthorizationEvaluationError> {
    if !decision.is_allow() {
        return Err(AuthorizationEvaluationError::DecisionNotAllow);
    }

    if !matches!(authority.status, AuthorityStatus::Active) {
        return Err(AuthorizationEvaluationError::AuthorityInactive);
    }

    if !authority.scope.contains(&requested_scope) {
        return Err(AuthorizationEvaluationError::ScopeExpansion);
    }

    let authorization = Authorization {
        id: authorization_id,
        decision_id: decision.id,
        authority_id: authority.id,
        scope: requested_scope,
        status: AuthorizationStatus::Active,
    };

    Ok(AuthorizationEvaluation {
        authorization,
        authority,
    })
}

use chrono::Utc;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
use crate::signature::CanonicalSigner;
use crate::verification::CanonicalBytes;

pub const AUTHORIZATION_ISSUED_EVENT_TYPE: &str = "AuthorizationIssued";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct AuthorizationIssuedEventPayload {
    authorization_id: AuthorizationId,
    decision_id: crate::domain::DecisionId,
    authority_id: crate::domain::AuthorityId,
    scope: Scope,
    status: AuthorizationStatus,
}

pub fn canonical_authorization_issued_payload(
    authorization: &Authorization,
) -> Result<CanonicalBytes, serde_json::Error> {
    let payload = AuthorizationIssuedEventPayload {
        authorization_id: authorization.id,
        decision_id: authorization.decision_id,
        authority_id: authorization.authority_id,
        scope: authorization.scope.clone(),
        status: authorization.status,
    };
    serde_json::to_vec(&payload).map(CanonicalBytes::new)
}

#[allow(clippy::too_many_arguments)]
pub fn build_authorization_issued_event(
    authorization: &Authorization,
    sequence: Sequence,
    actor_id: Uuid,
    correlation_id: Option<Uuid>,
    causation_id: Option<EventId>,
    previous_event_hash: Option<crate::verification::Sha256Digest>,
    provenance: Uuid,
    signer: &CanonicalSigner,
) -> Result<EventEnvelope, serde_json::Error> {
    let payload = canonical_authorization_issued_payload(authorization)?;
    let signature = signer.sign(&payload);
    Ok(EventEnvelope::new(
        EventId::new(authorization.id.value()),
        AUTHORIZATION_ISSUED_EVENT_TYPE.to_owned(),
        AggregateId::new(authorization.id.value()),
        "Authorization".to_owned(),
        sequence,
        Utc::now(),
        Utc::now(),
        actor_id,
        Some(authorization.authority_id.value()),
        correlation_id,
        causation_id,
        payload,
        previous_event_hash,
        SchemaVersion(1),
        provenance,
        signature,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{AuthorityId, DecisionId, DecisionVerdict, QuestionId};
    use uuid::Uuid;

    fn scope() -> Scope {
        Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned(), "write".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        }
    }

    fn authority() -> Authority {
        Authority {
            id: AuthorityId::new(Uuid::new_v4()),
            scope: scope(),
            status: AuthorityStatus::Active,
        }
    }

    fn decision(verdict: DecisionVerdict) -> Decision {
        Decision {
            id: DecisionId::new(Uuid::new_v4()),
            question_id: QuestionId::new(Uuid::new_v4()),
            verdict,
        }
    }

    #[test]
    fn allow_decision_can_be_authorized_only_with_active_authority() {
        let result = authorize(
            decision(DecisionVerdict::Allow),
            authority(),
            Scope {
                target: "target".to_owned(),
                operations: vec!["read".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
            AuthorizationId::new(Uuid::new_v4()),
        );

        assert!(result.is_ok());
    }

    #[test]
    fn deny_decision_cannot_create_authorization() {
        let result = authorize(
            decision(DecisionVerdict::Deny),
            authority(),
            scope(),
            AuthorizationId::new(Uuid::new_v4()),
        );

        assert_eq!(result, Err(AuthorizationEvaluationError::DecisionNotAllow));
    }

    #[test]
    fn revoked_authority_cannot_create_authorization() {
        let mut authority = authority();
        authority.status = AuthorityStatus::Revoked;

        let result = authorize(
            decision(DecisionVerdict::Allow),
            authority,
            scope(),
            AuthorizationId::new(Uuid::new_v4()),
        );

        assert_eq!(result, Err(AuthorizationEvaluationError::AuthorityInactive));
    }

    #[test]
    fn authorization_cannot_expand_authority_scope() {
        let authority = authority();
        let requested = Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned(), "delete".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        };

        let result = authorize(
            decision(DecisionVerdict::Allow),
            authority,
            requested,
            AuthorizationId::new(Uuid::new_v4()),
        );

        assert_eq!(result, Err(AuthorizationEvaluationError::ScopeExpansion));
    }
}
