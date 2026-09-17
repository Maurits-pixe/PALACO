use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::domain::{Authorization, AuthorizationStatus, AuthorityId};
use crate::revocation::RevocationReceipt;

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
    pub authorization_id: crate::domain::AuthorizationId,
    pub status: AuthorizationStatus,
    pub observed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CometError {
    AuthorityMismatch,
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
    use crate::domain::{AuthorizationId, DecisionId, Scope};

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
}
