use serde::{Deserialize, Serialize};

use crate::domain::{Authority, AuthorityStatus};
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
}

pub fn evaluate(
    authority: &Authority,
    authorization: &Authorization,
    _permit: &ExecutionPermit,
) -> (ExecutionDisposition, LifecycleReason) {
    if authorization.authority_id != authority.id {
        return (
            ExecutionDisposition::Stop,
            LifecycleReason::AuthorityMismatch,
        );
    }
    match authority.status {
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
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{AuthorityId, Authorization, AuthorizationId, DecisionId, Scope};
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

    fn permit() -> Option<ExecutionPermit> {
        let authorization = Authorization {
            id: AuthorizationId::new(Uuid::new_v4()),
            decision_id: DecisionId::new(Uuid::new_v4()),
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["write".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
        };
        let request = ExecutionRequest {
            operation: "write".to_owned(),
            scope: authorization.scope.clone(),
        };
        gate(&authorization, request).ok()
    }

    #[test]
    fn revoked_authority_stops_execution_lifecycle() {
        let Some(permit) = permit() else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&authority(AuthorityStatus::Revoked), &permit);
        assert_eq!(disposition, ExecutionDisposition::Stop);
        assert_eq!(reason, LifecycleReason::RevokedAuthority);
    }

    #[test]
    fn suspended_authority_requires_reassessment() {
        let Some(permit) = permit() else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&authority(AuthorityStatus::Suspended), &permit);
        assert_eq!(disposition, ExecutionDisposition::Reassess);
        assert_eq!(reason, LifecycleReason::SuspendedAuthority);
    }

    #[test]
    fn active_authority_allows_lifecycle_continuation() {
        let Some(permit) = permit() else {
            assert!(false);
            return;
        };
        let (disposition, reason) = evaluate(&authority(AuthorityStatus::Active), &permit);
        assert_eq!(disposition, ExecutionDisposition::Continue);
        assert_eq!(reason, LifecycleReason::ActiveAuthority);
    }
}
