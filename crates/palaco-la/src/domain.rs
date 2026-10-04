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
pub enum DecisionVerdict {
    Allow,
    Deny,
    Defer,
    Escalate,
    Unknown,
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

impl Decision {
    pub fn can_authorize(&self) -> bool {
        matches!(self.verdict, DecisionVerdict::Allow)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
