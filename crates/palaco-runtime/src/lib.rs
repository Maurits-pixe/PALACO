#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Runtime orchestration constrained by the Citadel boundary.

pub mod elixer;
pub mod sixri9ade;

use palaco_citadel::ExecutionBoundary;
use palaco_foundation::{ContractDisposition, ContractError, Validatable};

/// Runtime plan derived exclusively from a validated Citadel boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimePlan {
    boundary: ExecutionBoundary,
    disposition: ContractDisposition,
}

impl RuntimePlan {
    /// Creates a runtime plan while preserving the boundary disposition.
    #[must_use]
    pub fn new(boundary: ExecutionBoundary) -> Self {
        let disposition = boundary.disposition();
        Self {
            boundary,
            disposition,
        }
    }

    /// Runtime disposition.
    #[must_use]
    pub fn disposition(&self) -> ContractDisposition {
        self.disposition
    }

    /// Returns whether execution is explicitly permitted.
    #[must_use]
    pub fn can_execute(&self) -> bool {
        self.disposition == ContractDisposition::Execute
    }

    /// Boundary that produced this plan.
    #[must_use]
    pub fn boundary(&self) -> &ExecutionBoundary {
        &self.boundary
    }
}

impl Validatable for RuntimePlan {
    fn validate(&self) -> Result<(), ContractError> {
        self.boundary.validate()
    }
}
