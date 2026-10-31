use palaco_la::authority_assignment::{
    GrantState, LIFECYCLE_EVENT_SCHEMA_V01, LifecycleDecision, LifecycleEventV01,
    LifecycleValidationError, validate_lifecycle_event, validate_lifecycle_history,
};

fn event(
    from_state: GrantState,
    to_state: GrantState,
    decision: LifecycleDecision,
) -> LifecycleEventV01 {
    LifecycleEventV01 {
        schema: LIFECYCLE_EVENT_SCHEMA_V01.to_owned(),
        grant_ref: "synthetic-grant-1".to_owned(),
        from_state,
        to_state,
        decision,
        decision_ref: "synthetic-decision-1".to_owned(),
        actor_ref: "synthetic-reviewer-1".to_owned(),
        reason: "Synthetic lifecycle test".to_owned(),
        evidence_refs: vec!["synthetic-evidence-1".to_owned()],
        occurred_at: "2030-01-01T00:01:00Z".to_owned(),
    }
}

const PREVIOUS: &str = "2030-01-01T00:00:00Z";
const EVALUATED: &str = "2030-01-01T00:02:00Z";

#[test]
fn permitted_lifecycle_transitions_validate_without_granting_authority() {
    let permitted = [
        (
            GrantState::Effective,
            GrantState::UnderReview,
            LifecycleDecision::Review,
        ),
        (
            GrantState::UnderReview,
            GrantState::Effective,
            LifecycleDecision::Review,
        ),
        (
            GrantState::Effective,
            GrantState::Suspended,
            LifecycleDecision::Suspend,
        ),
        (
            GrantState::Suspended,
            GrantState::Effective,
            LifecycleDecision::Reinstate,
        ),
        (
            GrantState::Effective,
            GrantState::Revoked,
            LifecycleDecision::Revoke,
        ),
        (
            GrantState::Suspended,
            GrantState::Expired,
            LifecycleDecision::Expire,
        ),
    ];

    for (from, to, decision) in permitted {
        assert_eq!(
            validate_lifecycle_event(&event(from, to, decision), PREVIOUS, EVALUATED),
            Ok(())
        );
    }
}

#[test]
fn revoked_and_expired_grants_are_terminal() {
    for terminal in [GrantState::Revoked, GrantState::Expired] {
        assert_eq!(
            validate_lifecycle_event(
                &event(
                    terminal,
                    GrantState::Effective,
                    LifecycleDecision::Reinstate
                ),
                PREVIOUS,
                EVALUATED
            ),
            Err(LifecycleValidationError::InvalidTransition)
        );
    }
}

#[test]
fn suspended_grant_requires_reinstatement_decision() {
    assert_eq!(
        validate_lifecycle_event(
            &event(
                GrantState::Suspended,
                GrantState::Effective,
                LifecycleDecision::Review
            ),
            PREVIOUS,
            EVALUATED
        ),
        Err(LifecycleValidationError::InvalidTransition)
    );
}

#[test]
fn every_transition_requires_unique_evidence_and_decision_references() {
    let mut no_evidence = event(
        GrantState::Effective,
        GrantState::Suspended,
        LifecycleDecision::Suspend,
    );
    no_evidence.evidence_refs.clear();
    assert_eq!(
        validate_lifecycle_event(&no_evidence, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::MissingEvidence)
    );

    let mut duplicate_evidence = event(
        GrantState::Effective,
        GrantState::Suspended,
        LifecycleDecision::Suspend,
    );
    duplicate_evidence
        .evidence_refs
        .push("synthetic-evidence-1".to_owned());
    assert_eq!(
        validate_lifecycle_event(&duplicate_evidence, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::DuplicateEvidence)
    );

    let mut missing_decision = event(
        GrantState::Effective,
        GrantState::Suspended,
        LifecycleDecision::Suspend,
    );
    missing_decision.decision_ref.clear();
    assert_eq!(
        validate_lifecycle_event(&missing_decision, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::InvalidIdentifier)
    );

    let mut invalid_evidence_ref = event(
        GrantState::Effective,
        GrantState::Suspended,
        LifecycleDecision::Suspend,
    );
    invalid_evidence_ref.evidence_refs[0] = " ".to_owned();
    assert_eq!(
        validate_lifecycle_event(&invalid_evidence_ref, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::InvalidIdentifier)
    );
}

#[test]
fn lifecycle_events_require_monotonic_non_future_rfc3339_timestamps() {
    let mut non_monotonic = event(
        GrantState::Effective,
        GrantState::UnderReview,
        LifecycleDecision::Review,
    );
    non_monotonic.occurred_at = PREVIOUS.to_owned();
    assert_eq!(
        validate_lifecycle_event(&non_monotonic, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::TimestampNotMonotonic)
    );

    let mut future = event(
        GrantState::Effective,
        GrantState::UnderReview,
        LifecycleDecision::Review,
    );
    future.occurred_at = "2030-01-01T00:03:00Z".to_owned();
    assert_eq!(
        validate_lifecycle_event(&future, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::EventFromFuture)
    );

    let mut invalid = event(
        GrantState::Effective,
        GrantState::UnderReview,
        LifecycleDecision::Review,
    );
    invalid.occurred_at = "not-a-timestamp".to_owned();
    assert_eq!(
        validate_lifecycle_event(&invalid, PREVIOUS, EVALUATED),
        Err(LifecycleValidationError::InvalidTimestamp)
    );
}

#[test]
fn lifecycle_contract_rejects_unknown_fields() {
    let serialized = serde_json::to_string(&event(
        GrantState::Effective,
        GrantState::UnderReview,
        LifecycleDecision::Review,
    ))
    .expect("serialize synthetic event");
    let with_unknown = serialized.trim_end_matches('}').to_owned() + ",\"effective\":true}";

    assert!(serde_json::from_str::<LifecycleEventV01>(&with_unknown).is_err());
}

#[test]
fn history_validates_state_chain_and_event_order() {
    let mut review = event(
        GrantState::Effective,
        GrantState::UnderReview,
        LifecycleDecision::Review,
    );
    review.occurred_at = "2030-01-01T00:00:30Z".to_owned();

    let mut suspend = event(
        GrantState::UnderReview,
        GrantState::Suspended,
        LifecycleDecision::Suspend,
    );
    suspend.occurred_at = "2030-01-01T00:01:00Z".to_owned();

    let mut revoke = event(
        GrantState::Suspended,
        GrantState::Revoked,
        LifecycleDecision::Revoke,
    );
    revoke.occurred_at = "2030-01-01T00:01:30Z".to_owned();

    assert_eq!(
        validate_lifecycle_history(
            "synthetic-grant-1",
            GrantState::Effective,
            PREVIOUS,
            &[review, suspend, revoke],
            EVALUATED
        ),
        Ok(())
    );
}

#[test]
fn history_rejects_state_discontinuity_and_grant_mismatch() {
    let mut discontinuous = event(
        GrantState::Effective,
        GrantState::Suspended,
        LifecycleDecision::Suspend,
    );
    discontinuous.occurred_at = "2030-01-01T00:00:30Z".to_owned();
    let next = event(
        GrantState::Effective,
        GrantState::Revoked,
        LifecycleDecision::Revoke,
    );
    assert_eq!(
        validate_lifecycle_history(
            "synthetic-grant-1",
            GrantState::Effective,
            PREVIOUS,
            &[discontinuous.clone(), next],
            EVALUATED
        ),
        Err(LifecycleValidationError::StateChainMismatch)
    );

    discontinuous.grant_ref = "different-grant".to_owned();
    assert_eq!(
        validate_lifecycle_history(
            "synthetic-grant-1",
            GrantState::Effective,
            PREVIOUS,
            &[discontinuous],
            EVALUATED
        ),
        Err(LifecycleValidationError::GrantReferenceMismatch)
    );
}

#[test]
fn empty_history_is_valid_only_with_valid_evaluation_timestamps() {
    assert_eq!(
        validate_lifecycle_history(
            "synthetic-grant-1",
            GrantState::Effective,
            PREVIOUS,
            &[],
            EVALUATED
        ),
        Ok(())
    );
    assert_eq!(
        validate_lifecycle_history(
            "synthetic-grant-1",
            GrantState::Effective,
            "2030-01-01T00:03:00Z",
            &[],
            EVALUATED
        ),
        Err(LifecycleValidationError::EventFromFuture)
    );
}
