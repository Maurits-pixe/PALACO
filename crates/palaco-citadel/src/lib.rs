#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Constitutional execution boundary.

use palaco_foundation::{
    ContractDisposition, ContractError, FailClosed, Validatable, disposition_for,
};
use palaco_quay::ProvenanceRecord;

/// Boundary object that converts provenance plus authority into an execution disposition.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionBoundary {
    record: ProvenanceRecord,
    disposition: ContractDisposition,
}

impl ExecutionBoundary {
    /// Creates a boundary without inventing authority.
    #[must_use]
    pub fn new(record: ProvenanceRecord) -> Self {
        let disposition = disposition_for(record.authority());
        Self {
            record,
            disposition,
        }
    }

    /// Current boundary disposition.
    #[must_use]
    pub fn disposition(&self) -> ContractDisposition {
        self.disposition
    }

    /// Provenance record that justified the boundary state.
    #[must_use]
    pub fn record(&self) -> &ProvenanceRecord {
        &self.record
    }
}

impl Validatable for ExecutionBoundary {
    fn validate(&self) -> Result<(), ContractError> {
        match self.disposition {
            ContractDisposition::Execute => self.record.validate(),
            ContractDisposition::Hold | ContractDisposition::Deny => Ok(()),
        }
    }
}

impl FailClosed for ExecutionBoundary {
    type Output = ContractDisposition;

    fn fail_closed(&self) -> Self::Output {
        ContractDisposition::Deny
    }
}
