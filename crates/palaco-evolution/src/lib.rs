#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Evolution proposal boundary.
//!
//! Evolution may propose change but cannot create execution authority.

use palaco_foundation::{ContractDisposition, ContractError, EvidenceRef, Validatable};

/// Evidence-bearing proposal emitted by the Evolution layer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvolutionProposal {
    evidence: EvidenceRef,
}

impl EvolutionProposal {
    /// Creates an evidence-bearing proposal.
    #[must_use]
    pub fn new(evidence: EvidenceRef) -> Self {
        Self { evidence }
    }

    /// Evolution proposals always require governance before execution.
    #[must_use]
    pub fn requested_disposition(&self) -> ContractDisposition {
        ContractDisposition::Hold
    }
}

impl Validatable for EvolutionProposal {
    fn validate(&self) -> Result<(), ContractError> {
        self.evidence.validate()
    }
}
