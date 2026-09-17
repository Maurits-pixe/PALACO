use serde::{Deserialize, Serialize};
use uuid::Uuid;

macro_rules! id_type {
    ($name:ident) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
        pub struct $name(pub Uuid);

        impl $name {
            pub fn new(value: Uuid) -> Self {
                Self(value)
            }

            pub fn value(self) -> Uuid {
                self.0
            }
        }
    };
}

id_type!(QuestionId);
id_type!(EvidenceId);
id_type!(DecisionId);
id_type!(AuthorizationId);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EpistemicStatus {
    Known,
    Unknown,
    Disputed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DecisionVerdict {
    Allow,
    Deny,
    Defer,
    Escalate,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ThresholdState {
    NotEvaluated,
    InsufficientEvidence,
    Satisfied,
    Unsatisfied,
    Indeterminate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Question {
    pub id: QuestionId,
    pub subject: String,
    pub context: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Evidence {
    pub id: EvidenceId,
    pub question_id: QuestionId,
    pub source: String,
    pub origin: String,
    pub content_digest: String,
    pub relevance: String,
    pub limitations: Vec<String>,
    pub status: EpistemicStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EpistemicState {
    pub question_id: QuestionId,
    pub known: Vec<String>,
    pub unknown: Vec<String>,
    pub disputed: Vec<String>,
    pub assumptions: Vec<String>,
    pub contradictions: Vec<String>,
    pub limitations: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ThresholdAssessment {
    pub question_id: QuestionId,
    pub state: ThresholdState,
    pub basis: Vec<EvidenceId>,
    pub rationale: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Scope {
    pub target: String,
    pub operations: Vec<String>,
    pub territory: String,
    pub purpose: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Decision {
    pub id: DecisionId,
    pub question_id: QuestionId,
    pub verdict: DecisionVerdict,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Authorization {
    pub id: AuthorizationId,
    pub decision_id: DecisionId,
    pub scope: Scope,
}

impl Evidence {
    pub fn is_usable(&self) -> bool {
        !self.source.is_empty()
            && !self.origin.is_empty()
            && !self.content_digest.is_empty()
            && matches!(self.status, EpistemicStatus::Known | EpistemicStatus::Disputed)
    }
}

impl ThresholdAssessment {
    pub fn permits_decision(&self) -> bool {
        matches!(self.state, ThresholdState::Satisfied)
    }
}

impl Decision {
    pub fn can_authorize(&self) -> bool {
        matches!(self.verdict, DecisionVerdict::Allow)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn threshold_requires_explicit_satisfaction() {
        let assessment = ThresholdAssessment {
            question_id: QuestionId::new(Uuid::new_v4()),
            state: ThresholdState::Indeterminate,
            basis: Vec::new(),
            rationale: String::new(),
        };
        assert!(!assessment.permits_decision());
    }

    #[test]
    fn incomplete_evidence_is_not_usable() {
        let evidence = Evidence {
            id: EvidenceId::new(Uuid::new_v4()),
            question_id: QuestionId::new(Uuid::new_v4()),
            source: String::new(),
            origin: "test".to_owned(),
            content_digest: "digest".to_owned(),
            relevance: "test".to_owned(),
            limitations: Vec::new(),
            status: EpistemicStatus::Known,
        };
        assert!(!evidence.is_usable());
    }

    #[test]
    fn unknown_is_not_authorizable() {
        let decision = Decision {
            id: DecisionId::new(Uuid::new_v4()),
            question_id: QuestionId::new(Uuid::new_v4()),
            verdict: DecisionVerdict::Unknown,
        };
        assert!(!decision.can_authorize());
    }
}
