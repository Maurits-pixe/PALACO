use chrono::DateTime;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const LIFECYCLE_EVENT_SCHEMA_V01: &str = "aap-1-lifecycle-event-v0.1";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum GrantState {
    Effective,
    UnderReview,
    Suspended,
    Revoked,
    Expired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LifecycleDecision {
    Review,
    Suspend,
    Reinstate,
    Revoke,
    Expire,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleEventV01 {
    pub schema: String,
    pub grant_ref: String,
    pub from_state: GrantState,
    pub to_state: GrantState,
    pub decision: LifecycleDecision,
    pub decision_ref: String,
    pub actor_ref: String,
    pub reason: String,
    pub evidence_refs: Vec<String>,
    pub occurred_at: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LifecycleValidationError {
    UnsupportedSchema,
    InvalidIdentifier,
    InvalidReason,
    MissingEvidence,
    DuplicateEvidence,
    InvalidTimestamp,
    TimestampNotMonotonic,
    EventFromFuture,
    InvalidTransition,
}

/// Validates a proposed lifecycle event without applying or persisting it.
///
/// A successful result is only a syntactic and transition-shape check. It does not
/// establish registry state, authenticate evidence or actors, or make authority effective.
pub fn validate_lifecycle_event(
    event: &LifecycleEventV01,
    previous_event_at: &str,
    evaluated_at: &str,
) -> Result<(), LifecycleValidationError> {
    if event.schema != LIFECYCLE_EVENT_SCHEMA_V01 {
        return Err(LifecycleValidationError::UnsupportedSchema);
    }

    if !valid_identifier(&event.grant_ref)
        || !valid_identifier(&event.decision_ref)
        || !valid_identifier(&event.actor_ref)
    {
        return Err(LifecycleValidationError::InvalidIdentifier);
    }
    if event.reason.trim().is_empty() || event.reason.len() > 2_000 {
        return Err(LifecycleValidationError::InvalidReason);
    }
    if event.evidence_refs.is_empty() || event.evidence_refs.len() > 64 {
        return Err(LifecycleValidationError::MissingEvidence);
    }
    let mut unique_evidence = BTreeSet::new();
    for reference in &event.evidence_refs {
        if !valid_identifier(reference) {
            return Err(LifecycleValidationError::InvalidIdentifier);
        }
        if !unique_evidence.insert(reference) {
            return Err(LifecycleValidationError::DuplicateEvidence);
        }
    }

    let occurred = parse_timestamp(&event.occurred_at)?;
    let previous = parse_timestamp(previous_event_at)?;
    let evaluated = parse_timestamp(evaluated_at)?;
    if occurred <= previous {
        return Err(LifecycleValidationError::TimestampNotMonotonic);
    }
    if occurred > evaluated {
        return Err(LifecycleValidationError::EventFromFuture);
    }

    if !transition_is_permitted(event.from_state, event.to_state, event.decision) {
        return Err(LifecycleValidationError::InvalidTransition);
    }

    Ok(())
}

fn transition_is_permitted(from: GrantState, to: GrantState, decision: LifecycleDecision) -> bool {
    matches!(
        (from, to, decision),
        (
            GrantState::Effective,
            GrantState::UnderReview,
            LifecycleDecision::Review
        ) | (
            GrantState::UnderReview,
            GrantState::Effective,
            LifecycleDecision::Review
        ) | (
            GrantState::Effective,
            GrantState::Suspended,
            LifecycleDecision::Suspend
        ) | (
            GrantState::UnderReview,
            GrantState::Suspended,
            LifecycleDecision::Suspend
        ) | (
            GrantState::Suspended,
            GrantState::Effective,
            LifecycleDecision::Reinstate
        ) | (
            GrantState::Effective,
            GrantState::Revoked,
            LifecycleDecision::Revoke
        ) | (
            GrantState::UnderReview,
            GrantState::Revoked,
            LifecycleDecision::Revoke
        ) | (
            GrantState::Suspended,
            GrantState::Revoked,
            LifecycleDecision::Revoke
        ) | (
            GrantState::Effective,
            GrantState::Expired,
            LifecycleDecision::Expire
        ) | (
            GrantState::UnderReview,
            GrantState::Expired,
            LifecycleDecision::Expire
        ) | (
            GrantState::Suspended,
            GrantState::Expired,
            LifecycleDecision::Expire
        )
    )
}

fn valid_identifier(value: &str) -> bool {
    !value.trim().is_empty() && value.trim() == value && value.len() <= 256
}

fn parse_timestamp(value: &str) -> Result<DateTime<chrono::FixedOffset>, LifecycleValidationError> {
    DateTime::parse_from_rfc3339(value).map_err(|_| LifecycleValidationError::InvalidTimestamp)
}
