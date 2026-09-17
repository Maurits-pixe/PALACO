use crate::domain::{
    Decision, DecisionId, DecisionVerdict, Evidence, EpistemicState, Question, ThresholdAssessment,
    ThresholdState,
};
use crate::assessment::{assess, AssessmentError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DecisionEvaluationError {
    Assessment(AssessmentError),
    ThresholdNotSatisfied,
    QuestionMismatch,
    MissingThresholdEvidence,
    UnusableEvidence,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecisionEvaluation {
    pub decision: Decision,
    pub question: Question,
    pub epistemic_state: EpistemicState,
    pub threshold: ThresholdAssessment,
}

pub fn evaluate(
    question: Question,
    evidence: &[Evidence],
    threshold: ThresholdAssessment,
    decision_id: DecisionId,
) -> Result<DecisionEvaluation, DecisionEvaluationError> {
    if threshold.question_id != question.id {
        return Err(DecisionEvaluationError::QuestionMismatch);
    }

    let assessed = assess(question.clone(), evidence, threshold)
        .map_err(DecisionEvaluationError::Assessment)?;

    if assessed.threshold.state != ThresholdState::Satisfied {
        return Err(DecisionEvaluationError::ThresholdNotSatisfied);
    }

    if assessed.threshold.basis.is_empty() {
        return Err(DecisionEvaluationError::MissingThresholdEvidence);
    }

    for evidence_id in &assessed.threshold.basis {
        let Some(item) = evidence.iter().find(|item| item.id == *evidence_id) else {
            return Err(DecisionEvaluationError::MissingThresholdEvidence);
        };

        if !item.is_usable() {
            return Err(DecisionEvaluationError::UnusableEvidence);
        }
    }

    let decision = Decision {
        id: decision_id,
        question_id: question.id,
        verdict: DecisionVerdict::Allow,
    };

    Ok(DecisionEvaluation {
        decision,
        question,
        epistemic_state: assessed.epistemic_state,
        threshold: assessed.threshold,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{EpistemicStatus, EvidenceId, QuestionId};

    fn question() -> Question {
        Question::new(
            QuestionId::new(Uuid::new_v4()),
            "subject".to_owned(),
            "context".to_owned(),
        )
    }

    fn evidence(question_id: QuestionId) -> Evidence {
        Evidence {
            id: EvidenceId::new(Uuid::new_v4()),
            question_id,
            source: "source".to_owned(),
            origin: "origin".to_owned(),
            content_digest: "digest".to_owned(),
            relevance: "relevant".to_owned(),
            limitations: Vec::new(),
            status: EpistemicStatus::Known,
        }
    }

    use uuid::Uuid;

    #[test]
    fn satisfied_threshold_produces_decision() {
        let q = question();
        let e = evidence(q.id);
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::Satisfied,
            basis: vec![e.id],
            rationale: "sufficient evidence".to_owned(),
        };

        let result = evaluate(q.clone(), &[e], threshold, DecisionId::new(Uuid::new_v4()));
        assert!(matches!(result.map(|value| value.decision.verdict), Ok(DecisionVerdict::Allow)));
        assert_eq!(
            result.map(|value| value.decision.question_id),
            Ok(q.id)
        );
    }

    #[test]
    fn unsatisfied_threshold_cannot_produce_decision() {
        let q = question();
        let e = evidence(q.id);
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::Unsatisfied,
            basis: vec![e.id],
            rationale: "threshold not met".to_owned(),
        };

        let result = evaluate(q, &[e], threshold, DecisionId::new(Uuid::new_v4()));
        assert_eq!(
            result,
            Err(DecisionEvaluationError::ThresholdNotSatisfied)
        );
    }

    #[test]
    fn unknown_evidence_cannot_support_decision() {
        let q = question();
        let mut e = evidence(q.id);
        e.status = EpistemicStatus::Unknown;
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::Satisfied,
            basis: vec![e.id],
            rationale: "invalid basis".to_owned(),
        };

        let result = evaluate(q, &[e], threshold, DecisionId::new(Uuid::new_v4()));
        assert_eq!(
            result,
            Err(DecisionEvaluationError::UnusableEvidence)
        );
    }

    #[test]
    fn missing_basis_evidence_fails_closed() {
        let q = question();
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::Satisfied,
            basis: vec![EvidenceId::new(Uuid::new_v4())],
            rationale: "missing".to_owned(),
        };

        let result = evaluate(q, &[], threshold, DecisionId::new(Uuid::new_v4()));
        assert_eq!(result, Err(DecisionEvaluationError::MissingThresholdEvidence));
    }
}
