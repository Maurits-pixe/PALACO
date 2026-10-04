#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Provenance boundary for evidence-bearing events.

use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, Validatable};

/// Provenance record carried from Quay into execution governance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProvenanceRecord {
    event: EventEnvelope,
    authority: AuthorityState,
}

impl ProvenanceRecord {
    /// Creates a provenance record without changing the supplied authority state.
    #[must_use]
    pub fn new(event: EventEnvelope, authority: AuthorityState) -> Self {
        Self { event, authority }
    }

    /// Event whose provenance is being carried.
    #[must_use]
    pub fn event(&self) -> &EventEnvelope {
        &self.event
    }

    /// Current authority state attached to the record.
    #[must_use]
    pub fn authority(&self) -> AuthorityState {
        self.authority
    }
}

impl Validatable for ProvenanceRecord {
    fn validate(&self) -> Result<(), ContractError> {
        self.event.validate()?;
        match self.authority {
            AuthorityState::Authorized => Ok(()),
            AuthorityState::Revoked => Err(ContractError::RevokedAuthority),
            AuthorityState::Expired => Err(ContractError::ExpiredAuthority),
            AuthorityState::InDoubt => Err(ContractError::AuthorityInDoubt),
        }
    }
}
