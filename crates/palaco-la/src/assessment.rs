use crate::domain::{
    Evidence, EpistemicState, EpistemicStatus, Question, ThresholdAssessment, ThresholdState,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AssessmentError {
    QuestionMismatch,
    NoEvidence,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceAssessment {
    pub question: Question,
    pub epistemic_state: EpistemicState,
    pub threshold: ThresholdAssessment,
}

pub fn assess(
    question: Question,
    evidence: &[Evidence],
    threshold: ThresholdAssessment,
) -> Result<EvidenceAssessment, AssessmentError> {
    if threshold.question_id != question.id
        || evidence.iter().any(|item| item.question_id != question.id)
    {
        return Err(AssessmentError::QuestionMismatch);
    }

    if evidence.is_empty() {
        return Err(AssessmentError::NoEvidence);
    }

    let known = evidence
        .iter()
        .filter(|item| matches!(item.status, EpistemicStatus::Known))
        .map(|item| item.relevance.clone())
        .collect();

    let disputed = evidence
        .iter()
        .filter(|item| matches!(item.status, EpistemicStatus::Disputed))
        .map(|item| item.relevance.clone())
        .collect();

    let epistemic_state = EpistemicState {
        question_id: question.id,
        known,
        unknown: Vec::new(),
        disputed,
        assumptions: Vec::new(),
        contradictions: Vec::new(),
        limitations: evidence
            .iter()
            .flat_map(|item| item.limitations.clone())
            .collect(),
    };

    let threshold = if threshold.state == ThresholdState::Satisfied {
        threshold
    } else {
        ThresholdAssessment {
            question_id: question.id,
            state: ThresholdState::Indeterminate,
            basis: threshold.basis,
            rationale: threshold.rationale,
        }
    };

    Ok(EvidenceAssessment {
        question,
        epistemic_state,
        threshold,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{EvidenceId, QuestionId};

    fn question() -> Question {
        Question::new(
            QuestionId::new(Uuid::new_v4()),
            "test subject".to_owned(),
            "test context".to_owned(),
        )
    }

    fn evidence(question_id: QuestionId) -> Evidence {
        Evidence {
            id: EvidenceId::new(Uuid::new_v4()),
            question_id,
            source: "test-source".to_owned(),
            origin: "test-origin".to_owned(),
            content_digest: "digest".to_owned(),
            relevance: "relevant".to_owned(),
            limitations: vec!["limited".to_owned()],
            status: EpistemicStatus::Known,
        }
    }

    use uuid::Uuid;

    #[test]
    fn assessment_requires_same_question() {
        let q = question();
        let other = QuestionId::new(Uuid::new_v4());
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::Satisfied,
            basis: vec![EvidenceId::new(Uuid::new_v4())],
            rationale: "basis".to_owned(),
        };

        assert_eq!(
            assess(q, &[evidence(other)], threshold),
            Err(AssessmentError::QuestionMismatch)
        );
    }

    #[test]
    fn satisfied_threshold_is_preserved() {
        let q = question();
        let evidence = evidence(q.id);
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::Satisfied,
            basis: vec![evidence.id],
            rationale: "basis".to_owned(),
        };

        let assessment = assess(q, &[evidence], threshold);
        assert!(matches!(
            assessment.map(|value| value.threshold.state),
            Ok(ThresholdState::Satisfied)
        ));
    }

    #[test]
    fn non_satisfied_threshold_fails_closed_to_indeterminate() {
        let q = question();
        let evidence = evidence(q.id);
        let threshold = ThresholdAssessment {
            question_id: q.id,
            state: ThresholdState::NotEvaluated,
            basis: vec![evidence.id],
            rationale: "not evaluated".to_owned(),
        };

        let assessment = assess(q, &[evidence], threshold);
        assert!(matches!(
            assessment.map(|value| value.threshold.state),
            Ok(ThresholdState::Indeterminate)
        ));
    }
}
