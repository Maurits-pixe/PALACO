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
id_type!(AuthorityId);

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

impl Question {
    pub fn new(id: QuestionId, subject: String, context: String) -> Self {
        Self { id, subject, context }
    }
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

impl Scope {
    pub fn contains(&self, requested: &Self) -> bool {
        self.target == requested.target
            && self.territory == requested.territory
            && self.purpose == requested.purpose
            && requested
                .operations
                .iter()
                .all(|operation| self.operations.contains(operation))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorityStatus {
    Active,
    Suspended,
    Revoked,
    Expired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Authority {
    pub id: AuthorityId,
    pub scope: Scope,
    pub status: AuthorityStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Decision {
    pub id: DecisionId,
    pub question_id: QuestionId,
    pub verdict: DecisionVerdict,
}

impl Decision {
    pub fn is_allow(&self) -> bool {
        matches!(self.verdict, DecisionVerdict::Allow)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorizationStatus {
    Active,
    Suspended,
    Revoked,
    Expired,
    Superseded,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Authorization {
    pub id: AuthorizationId,
    pub decision_id: DecisionId,
    pub authority_id: AuthorityId,
    pub scope: Scope,
    pub status: AuthorizationStatus,
}

impl Authorization {
    pub fn is_active(&self) -> bool {
        matches!(self.status, AuthorizationStatus::Active)
    }

    pub fn revoked(&self) -> Self {
        Self {
            status: AuthorizationStatus::Revoked,
            ..self.clone()
        }
    }
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
    fn unknown_decision_is_not_allow() {
        let decision = Decision {
            id: DecisionId::new(Uuid::new_v4()),
            question_id: QuestionId::new(Uuid::new_v4()),
            verdict: DecisionVerdict::Unknown,
        };
        assert!(!decision.is_allow());
    }

    #[test]
    fn authority_scope_cannot_be_expanded() {
        let authority = Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        };
        let requested = Scope {
            target: "target".to_owned(),
            operations: vec!["read".to_owned(), "write".to_owned()],
            territory: "territory".to_owned(),
            purpose: "purpose".to_owned(),
        };
        assert!(!authority.contains(&requested));
    }

    #[test]
    fn revoked_authorization_is_not_active() {
        let authorization = Authorization {
            id: AuthorizationId::new(Uuid::new_v4()),
            decision_id: DecisionId::new(Uuid::new_v4()),
            authority_id: AuthorityId::new(Uuid::new_v4()),
            scope: Scope {
                target: "target".to_owned(),
                operations: vec!["read".to_owned()],
                territory: "territory".to_owned(),
                purpose: "purpose".to_owned(),
            },
            status: AuthorizationStatus::Revoked,
        };
        assert!(!authorization.is_active());
    }
}
