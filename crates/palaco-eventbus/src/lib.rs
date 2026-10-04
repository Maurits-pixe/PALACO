#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Evidence-bearing event transport boundary.

use palaco_foundation::{ContractError, EvidenceRef, Validatable};

/// Event transported across PALACO Foundation crate boundaries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventEnvelope {
    topic: String,
    evidence: EvidenceRef,
}

impl EventEnvelope {
    /// Creates an event whose evidence reference has already been validated.
    #[must_use]
    pub fn new(topic: impl Into<String>, evidence: EvidenceRef) -> Self {
        Self {
            topic: topic.into(),
            evidence,
        }
    }

    /// Event topic.
    #[must_use]
    pub fn topic(&self) -> &str {
        &self.topic
    }

    /// Evidence reference carried with the event.
    #[must_use]
    pub fn evidence(&self) -> &EvidenceRef {
        &self.evidence
    }
}

impl Validatable for EventEnvelope {
    fn validate(&self) -> Result<(), ContractError> {
        self.evidence.validate()
    }
}
