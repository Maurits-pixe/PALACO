#[cfg(test)]
mod tests {
    use ed25519_dalek::SigningKey;
    use uuid::Uuid;

    use crate::{
        CanonicalBytes, CanonicalSigner, CanonicalVerifier,
        decision::{DecisionEvaluation, DecisionEvaluationError, evaluate},
        domain::{
            Authorization, AuthorizationId, Decision, DecisionId, DecisionVerdict, EpistemicStatus,
            Evidence, EvidenceId, Question, QuestionId, Scope, ThresholdAssessment, ThresholdState,
        },
    };

    fn question() -> Question {
        Question {
            id: QuestionId::new(Uuid::from_u128(1)),
            subject: "synthetic subject".to_owned(),
            context: "synthetic context".to_owned(),
        }
    }

    fn evidence(question_id: QuestionId, status: EpistemicStatus) -> Evidence {
        Evidence {
            id: EvidenceId::new(Uuid::from_u128(2)),
            question_id,
            source: "synthetic source".to_owned(),
            origin: "synthetic origin".to_owned(),
            content_digest: "synthetic digest".to_owned(),
            relevance: "synthetic relevance".to_owned(),
            limitations: Vec::new(),
            status,
        }
    }

    fn threshold(question_id: QuestionId, state: ThresholdState) -> ThresholdAssessment {
        ThresholdAssessment {
            question_id,
            state,
            basis: vec![EvidenceId::new(Uuid::from_u128(2))],
            rationale: "synthetic test basis".to_owned(),
        }
    }

    #[test]
    fn only_an_explicit_allow_decision_can_be_authorizable() {
        for verdict in [
            DecisionVerdict::Allow,
            DecisionVerdict::Deny,
            DecisionVerdict::Defer,
            DecisionVerdict::Escalate,
            DecisionVerdict::Unknown,
        ] {
            let decision = crate::domain::Decision {
                id: DecisionId::new(Uuid::from_u128(3)),
                question_id: QuestionId::new(Uuid::from_u128(1)),
                verdict,
            };

            assert_eq!(
                decision.can_authorize(),
                verdict == DecisionVerdict::Allow,
                "unexpected authorization capability for {verdict:?}"
            );
        }
    }

    #[test]
    fn every_non_satisfied_threshold_fails_closed_before_decision_creation() {
        let q = question();
        let e = evidence(q.id, EpistemicStatus::Known);

        for state in [
            ThresholdState::NotEvaluated,
            ThresholdState::InsufficientEvidence,
            ThresholdState::Unsatisfied,
            ThresholdState::Indeterminate,
        ] {
            let result = evaluate(
                q.clone(),
                std::slice::from_ref(&e),
                threshold(q.id, state.clone()),
                DecisionId::new(Uuid::from_u128(3)),
            );

            assert_eq!(
                result,
                Err(DecisionEvaluationError::ThresholdNotSatisfied),
                "unexpected decision from {state:?} threshold"
            );
        }
    }

    #[test]
    fn unknown_evidence_cannot_satisfy_the_decision_gate() {
        let q = question();
        let e = evidence(q.id, EpistemicStatus::Unknown);
        let result = evaluate(
            q.clone(),
            std::slice::from_ref(&e),
            threshold(q.id, ThresholdState::Satisfied),
            DecisionId::new(Uuid::from_u128(3)),
        );

        assert_eq!(result, Err(DecisionEvaluationError::UnusableEvidence));
    }

    #[test]
    fn signature_verification_does_not_change_decision_authority() {
        let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
        let bytes = CanonicalBytes::new(b"synthetic signed bytes".to_vec());
        let signature = signer.sign(&bytes);
        let verifier = CanonicalVerifier::from_key(signer.verifying_key());
        let decision = crate::domain::Decision {
            id: DecisionId::new(Uuid::from_u128(3)),
            question_id: QuestionId::new(Uuid::from_u128(1)),
            verdict: DecisionVerdict::Unknown,
        };

        assert!(verifier.verify(&bytes, &signature).is_ok());
        assert!(!decision.can_authorize());
        assert!(
            verifier
                .verify(
                    &CanonicalBytes::new(b"different bytes".to_vec()),
                    &signature
                )
                .is_err()
        );
        assert!(!decision.can_authorize());
    }

    #[test]
    fn successful_evaluation_returns_a_decision_not_an_execution_result() {
        let q = question();
        let e = evidence(q.id, EpistemicStatus::Known);
        let result: Result<DecisionEvaluation, DecisionEvaluationError> = evaluate(
            q.clone(),
            &[e],
            threshold(q.id, ThresholdState::Satisfied),
            DecisionId::new(Uuid::from_u128(3)),
        );

        let evaluation = result.expect("satisfied synthetic evidence should evaluate");
        assert_eq!(evaluation.decision.verdict, DecisionVerdict::Allow);
        assert_eq!(evaluation.decision.question_id, q.id);
        assert_eq!(evaluation.threshold.state, ThresholdState::Satisfied);
    }

    #[test]
    fn authorization_preserves_only_the_scope_explicitly_bound_to_its_decision() {
        let scope = Scope {
            target: "synthetic-target".to_owned(),
            operations: vec!["synthetic-read".to_owned()],
            territory: "local-test".to_owned(),
            purpose: "architecture-test".to_owned(),
        };

        for verdict in [
            DecisionVerdict::Allow,
            DecisionVerdict::Deny,
            DecisionVerdict::Defer,
            DecisionVerdict::Escalate,
            DecisionVerdict::Unknown,
        ] {
            let decision = Decision {
                id: DecisionId::new(Uuid::from_u128(3)),
                question_id: QuestionId::new(Uuid::from_u128(1)),
                verdict,
            };

            let authorization = decision.can_authorize().then(|| Authorization {
                id: AuthorizationId::new(Uuid::from_u128(4)),
                decision_id: decision.id,
                scope: scope.clone(),
            });

            assert_eq!(
                authorization.is_some(),
                verdict == DecisionVerdict::Allow,
                "unexpected authorization issuance for {verdict:?}"
            );
            if let Some(authorization) = authorization {
                assert_eq!(authorization.decision_id, decision.id);
                assert_eq!(authorization.scope, scope);
            }
        }
    }
}
