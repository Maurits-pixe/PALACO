use serde::{Deserialize, Serialize};

use crate::domain::{Authorization, AuthorizationStatus, Scope};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExecutionGateError {
    ScopeMismatch,
    EmptyOperation,
    AuthorizationInactive,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionRequest {
    pub operation: String,
    pub scope: Scope,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionPermit {
    authorization_id: crate::domain::AuthorizationId,
    request: ExecutionRequest,
}

impl ExecutionPermit {
    pub fn authorization_id(&self) -> crate::domain::AuthorizationId {
        self.authorization_id
    }

    pub fn request(&self) -> &ExecutionRequest {
        &self.request
    }
}

pub fn gate(
    authorization: &Authorization,
    request: ExecutionRequest,
) -> Result<ExecutionPermit, ExecutionGateError> {
    if request.operation.is_empty() {
        return Err(ExecutionGateError::EmptyOperation);
    }

    if !matches!(authorization.status, AuthorizationStatus::Active) {
        return Err(ExecutionGateError::AuthorizationInactive);
    }

    if !authorization.scope.contains(&request.scope)
        || !request.scope.operations.contains(&request.operation)
    {
        return Err(ExecutionGateError::ScopeMismatch);
    }

    Ok(ExecutionPermit {
        authorization_id: authorization.id,
        request,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{AuthorityId, AuthorizationId, DecisionId};

    fn authorization() -> Authorization {
        Authorization {
            id: AuthorizationId::new(uuid::Uuid::new_v4()),
            decision_id: DecisionId::new(uuid::Uuid::new_v4()),
            authority_id: AuthorityId::new(uuid::Uuid::new_v4()),
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["read".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
            status: AuthorizationStatus::Active,
        }
    }

    fn request(operation: &str) -> ExecutionRequest {
        ExecutionRequest {
            operation: operation.to_owned(),
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["read".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
        }
    }

    #[test]
    fn execution_requires_authorized_scope() {
        assert!(gate(&authorization(), request("read")).is_ok());
    }

    #[test]
    fn execution_rejects_operation_outside_authorization() {
        assert_eq!(
            gate(&authorization(), request("write")),
            Err(ExecutionGateError::ScopeMismatch)
        );
    }

    #[test]
    fn execution_rejects_empty_operation() {
        assert_eq!(
            gate(&authorization(), request("")),
            Err(ExecutionGateError::EmptyOperation)
        );
    }

    #[test]
    fn permit_is_bound_to_authorization() {
        let permit = gate(&authorization(), request("read"));
        assert!(permit.is_ok());
        if let Ok(permit) = permit {
            assert_ne!(
                permit.authorization_id(),
                AuthorizationId::new(uuid::Uuid::nil())
            );
        }
    }

    #[test]
    fn revoked_authorization_cannot_create_execution_permit() {
        let mut authorization = authorization();
        authorization.status = AuthorizationStatus::Revoked;
        assert_eq!(
            gate(&authorization, request("read")),
            Err(ExecutionGateError::AuthorizationInactive)
        );
    }
}
