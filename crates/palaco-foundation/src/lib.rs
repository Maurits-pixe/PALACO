#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Minimal constitutional contracts shared by the PALACO Foundation workspace.
//!
//! The contract shape is aligned with the existing PALACO genesis pattern:
//! explicit evidence, explicit authority state, validation, and fail-closed
//! dispositions. This crate creates no execution authority by itself.

use std::{error::Error, fmt};

/// Reference to evidence required by cross-crate security decisions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceRef(String);

impl EvidenceRef {
    /// Creates a non-empty evidence reference.
    pub fn new(id: impl Into<String>) -> Result<Self, ContractError> {
        let id = id.into();
        if id.trim().is_empty() {
            return Err(ContractError::MissingEvidence);
        }
        Ok(Self(id))
    }

    /// Returns the evidence identifier.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Authority state observed by the execution chain.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthorityState {
    /// Explicitly authorized under the current decision context.
    Authorized,
    /// Authorization was intentionally revoked.
    Revoked,
    /// Authorization expired.
    Expired,
    /// Authority cannot currently be established.
    InDoubt,
}

/// Fail-closed disposition shared across execution-facing crates.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContractDisposition {
    /// Execution may proceed.
    Execute,
    /// Execution must pause for additional evidence or review.
    Hold,
    /// Execution must not proceed.
    Deny,
}

/// Errors produced by constitutional contract validation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContractError {
    /// A required evidence reference was absent.
    MissingEvidence,
    /// The relevant authority was revoked.
    RevokedAuthority,
    /// The relevant authority expired.
    ExpiredAuthority,
    /// Authority is currently indeterminate.
    AuthorityInDoubt,
}

impl fmt::Display for ContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::MissingEvidence => "required evidence reference is missing",
            Self::RevokedAuthority => "authority is revoked",
            Self::ExpiredAuthority => "authority is expired",
            Self::AuthorityInDoubt => "authority is in doubt",
        };
        formatter.write_str(message)
    }
}

impl Error for ContractError {}

/// Contract types that can validate their own structural and authority bounds.
pub trait Validatable {
    /// Validates the contract.
    fn validate(&self) -> Result<(), ContractError>;
}

/// Contract types that expose an explicit fail-closed result.
pub trait FailClosed {
    /// Fail-closed output type.
    type Output;

    /// Returns the state used when execution cannot be justified.
    fn fail_closed(&self) -> Self::Output;
}

impl Validatable for EvidenceRef {
    fn validate(&self) -> Result<(), ContractError> {
        if self.0.trim().is_empty() {
            return Err(ContractError::MissingEvidence);
        }
        Ok(())
    }
}

/// Maps authority into a conservative execution disposition.
#[must_use]
pub fn disposition_for(authority: AuthorityState) -> ContractDisposition {
    match authority {
        AuthorityState::Authorized => ContractDisposition::Execute,
        AuthorityState::Revoked | AuthorityState::Expired => ContractDisposition::Deny,
        AuthorityState::InDoubt => ContractDisposition::Hold,
    }
}
