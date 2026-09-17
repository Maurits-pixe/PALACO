use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::domain::AuthorityId;

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
}
