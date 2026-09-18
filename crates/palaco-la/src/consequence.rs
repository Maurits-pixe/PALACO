use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConsequenceReceipt {
    pub consequence_id: Uuid,
    pub execution_id: Uuid,
    pub observed_at: DateTime<Utc>,
    pub summary: String,
    pub evidence: Vec<Uuid>,
    pub contradictions: Vec<String>,
}

impl ConsequenceReceipt {
    pub fn is_reviewable(&self) -> bool {
        !self.summary.is_empty() && !self.evidence.is_empty()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ReassessmentTrigger {
    NewEvidence,
    Contradiction,
    Consequence,
    AuthorityChange,
    Revocation,
    Expiration,
    Supersession,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Reassessment {
    pub reassessment_id: Uuid,
    pub question_id: Uuid,
    pub trigger: ReassessmentTrigger,
    pub evidence: Vec<Uuid>,
    pub rationale: String,
}

impl Reassessment {
    pub fn requires_new_decision(&self) -> bool {
        matches!(
            self.trigger,
            ReassessmentTrigger::NewEvidence
                | ReassessmentTrigger::Contradiction
                | ReassessmentTrigger::Consequence
                | ReassessmentTrigger::AuthorityChange
                | ReassessmentTrigger::Revocation
                | ReassessmentTrigger::Expiration
                | ReassessmentTrigger::Supersession
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn consequence_without_evidence_is_not_reviewable() {
        let consequence = ConsequenceReceipt {
            consequence_id: Uuid::new_v4(),
            execution_id: Uuid::new_v4(),
            observed_at: Utc::now(),
            summary: "changed".to_owned(),
            evidence: Vec::new(),
            contradictions: Vec::new(),
        };
        assert!(!consequence.is_reviewable());
    }

    #[test]
    fn revocation_requires_reassessment() {
        let reassessment = Reassessment {
            reassessment_id: Uuid::new_v4(),
            question_id: Uuid::new_v4(),
            trigger: ReassessmentTrigger::Revocation,
            evidence: Vec::new(),
            rationale: "authority revoked".to_owned(),
        };
        assert!(reassessment.requires_new_decision());
    }
}
