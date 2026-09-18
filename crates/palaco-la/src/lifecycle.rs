use serde::{Deserialize, Serialize};

use crate::domain::{Authority, AuthorityStatus, Authorization, AuthorizationStatus};
use crate::execution::ExecutionPermit;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ExecutionDisposition {
    Continue,
    Stop,
    Reassess,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LifecycleReason {
    ActiveAuthority,
    AuthorityMismatch,
    SuspendedAuthority,
    RevokedAuthority,
    ExpiredAuthority,
    AuthorizationRevoked,
    AuthorizationSuspended,
    AuthorizationExpired,
    AuthorizationSuperseded,
}

pub fn evaluate(
    authority: &Authority,
    authorization: &Authorization,
    permit: &ExecutionPermit,
) -> (ExecutionDisposition, LifecycleReason) {
    if authorization.authority_id != authority.id {
        return (
            ExecutionDisposition::Stop,
            LifecycleReason::AuthorityMismatch,
        );
    }

    if permit.authorization_id() != authorization.id {
        return (
            ExecutionDisposition::Stop,
            LifecycleReason::AuthorityMismatch,
        );
    }

    match authorization.status {
        AuthorizationStatus::Revoked => (
            ExecutionDisposition::Stop,
            LifecycleReason::AuthorizationRevoked,
        ),
        AuthorizationStatus::Suspended => (
            ExecutionDisposition::Reassess,
            LifecycleReason::AuthorizationSuspended,
        ),
        AuthorizationStatus::Expired => (
            ExecutionDisposition::Stop,
            LifecycleReason::AuthorizationExpired,
        ),
        AuthorizationStatus::Superseded => (
            ExecutionDisposition::Stop,
            LifecycleReason::AuthorizationSuperseded,
        ),
        AuthorizationStatus::Active => match authority.status {
            AuthorityStatus::Active => (
                ExecutionDisposition::Continue,
                LifecycleReason::ActiveAuthority,
            ),
            AuthorityStatus::Suspended => (
                ExecutionDisposition::Reassess,
                LifecycleReason::SuspendedAuthority,
            ),
            AuthorityStatus::Revoked => (
                ExecutionDisposition::Stop,
                LifecycleReason::RevokedAuthority,
            ),
            AuthorityStatus::Expired => (
                ExecutionDisposition::Stop,
                LifecycleReason::ExpiredAuthority,
            ),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{AuthorityId, AuthorizationId, DecisionId, Scope};
    use crate::execution::{ExecutionRequest, gate};
    use uuid::Uuid;

    fn authority(status: AuthorityStatus) -> Authority {
        Authority {
            id: AuthorityId::new(Uuid::new_v4()),
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["write".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
            status,
        }
    }

    fn make_authorization(authority_id: AuthorityId, status: AuthorizationStatus) -> Authorization {
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

    fn permit(authorization: &Authorization) -> Option<ExecutionPermit> {
        let request = ExecutionRequest {
            operation: "write".to_owned(),
            scope: authorization.scope.clone(),
        };
        gate(authorization, request).ok()
    }

    #[test]
    fn revoked_authority_stops_execution_lifecycle() {
        let auth = authority(AuthorityStatus::Revoked);
        let authorization = make_authorization(auth.id, AuthorizationStatus::Active);
        let Some(permit) = permit(&authorization) else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&auth, &authorization, &permit);
        assert_eq!(disposition, ExecutionDisposition::Stop);
        assert_eq!(reason, LifecycleReason::RevokedAuthority);
    }

    #[test]
    fn suspended_authority_requires_reassessment() {
        let auth = authority(AuthorityStatus::Suspended);
        let authorization = make_authorization(auth.id, AuthorizationStatus::Active);
        let Some(permit) = permit(&authorization) else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&auth, &authorization, &permit);
        assert_eq!(disposition, ExecutionDisposition::Reassess);
        assert_eq!(reason, LifecycleReason::SuspendedAuthority);
    }

    #[test]
    fn active_authority_allows_lifecycle_continuation() {
        let auth = authority(AuthorityStatus::Active);
        let authorization = make_authorization(auth.id, AuthorizationStatus::Active);
        let Some(permit) = permit(&authorization) else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&auth, &authorization, &permit);
        assert_eq!(disposition, ExecutionDisposition::Continue);
        assert_eq!(reason, LifecycleReason::ActiveAuthority);
    }

    #[test]
    fn revoked_authorization_stops_execution_lifecycle() {
        let auth = authority(AuthorityStatus::Active);
        let authorization = make_authorization(auth.id, AuthorizationStatus::Revoked);
        let invalidated = authorization.revoked();
        assert_eq!(invalidated.status, AuthorizationStatus::Revoked);
        let prior_permit = {
            let active = make_authorization(&auth.id, AuthorizationStatus::Active);
            permit(&active)
        };
        let Some(prior_permit) = prior_permit else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&auth, &invalidated, &prior_permit);
        assert_eq!(disposition, ExecutionDisposition::Stop);
        assert_eq!(reason, LifecycleReason::AuthorizationRevoked);
    }

    #[test]
    fn mismatched_authority_stops_execution_lifecycle() {
        let auth = authority(AuthorityStatus::Active);
        let authorization = make_authorization(
            AuthorityId::new(Uuid::new_v4()),
            AuthorizationStatus::Active,
        );
        let Some(permit) = permit(&authorization) else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&auth, &authorization, &permit);
        assert_eq!(disposition, ExecutionDisposition::Stop);
        assert_eq!(reason, LifecycleReason::AuthorityMismatch);
    }

    #[test]
    fn mismatched_permit_authorization_stops_execution_lifecycle() {
        let auth = authority(AuthorityStatus::Active);
        let authorization = make_authorization(auth.id, AuthorizationStatus::Active);
        let other = make_authorization(auth.id, AuthorizationStatus::Active);
        let Some(permit) = permit(&other) else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&auth, &authorization, &permit);
        assert_eq!(disposition, ExecutionDisposition::Stop);
        assert_eq!(reason, LifecycleReason::AuthorityMismatch);
    }
}
