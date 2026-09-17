use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::domain::AuthorizationId;
use crate::execution::{ExecutionPermit, ExecutionRequest};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ExecutionStatus {
    NotStarted,
    Started,
    Completed,
    Failed,
    Partial,
    Cancelled,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionReceipt {
    pub execution_id: Uuid,
    pub authorization_id: AuthorizationId,
    pub request: ExecutionRequest,
    pub status: ExecutionStatus,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub outcome: Option<String>,
}

impl ExecutionReceipt {
    pub fn from_permit(execution_id: Uuid, permit: &ExecutionPermit) -> Self {
        Self {
            execution_id,
            authorization_id: permit.authorization_id(),
            request: permit.request().clone(),
            status: ExecutionStatus::NotStarted,
            started_at: None,
            completed_at: None,
            outcome: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObservationReceipt {
    pub observation_id: Uuid,
    pub execution_id: Uuid,
    pub observed_at: DateTime<Utc>,
    pub source: String,
    pub method: String,
    pub before_state: String,
    pub after_state: String,
    pub evidence: Vec<Uuid>,
    pub contradictions: Vec<String>,
}

impl ObservationReceipt {
    pub fn is_usable(&self) -> bool {
        !self.source.is_empty() && !self.method.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::Scope;
    use crate::execution::{gate, ExecutionRequest};

    fn permit() -> ExecutionPermit {
        let authorization = crate::domain::Authorization {
            id: AuthorizationId::new(Uuid::new_v4()),
            decision_id: crate::domain::DecisionId::new(Uuid::new_v4()),
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
        match gate(&authorization, request) {
            Ok(permit) => permit,
            Err(_) => {
                assert!(false);
                return;
            }
        }
    }

    #[test]
    fn execution_receipt_is_bound_to_permit() {
        let permit = permit();
        let receipt = ExecutionReceipt::from_permit(Uuid::new_v4(), &permit);
        assert_eq!(receipt.authorization_id, permit.authorization_id());
        assert_eq!(receipt.request, *permit.request());
        assert_eq!(receipt.status, ExecutionStatus::NotStarted);
    }

    #[test]
    fn observation_requires_source_and_method() {
        let observation = ObservationReceipt {
            observation_id: Uuid::new_v4(),
            execution_id: Uuid::new_v4(),
            observed_at: Utc::now(),
            source: String::new(),
            method: "test".to_owned(),
            before_state: "before".to_owned(),
            after_state: "after".to_owned(),
            evidence: Vec::new(),
            contradictions: Vec::new(),
        };
        assert!(!observation.is_usable());
    }
}
