#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Final runtime-facing PALACO Foundation execution boundary.

use palaco_foundation::{ContractDisposition, ContractError, FailClosed, Validatable};
use palaco_runtime::RuntimePlan;

/// Kernel cycle that preserves the runtime's constitutional disposition.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KernelCycle {
    plan: RuntimePlan,
    disposition: ContractDisposition,
}

impl KernelCycle {
    /// Creates a kernel cycle without widening execution authority.
    #[must_use]
    pub fn new(plan: RuntimePlan) -> Self {
        let disposition = plan.disposition();
        Self { plan, disposition }
    }

    /// Kernel disposition.
    #[must_use]
    pub fn disposition(&self) -> ContractDisposition {
        self.disposition
    }

    /// Execution is possible only when every preceding boundary preserved Execute.
    #[must_use]
    pub fn can_execute(&self) -> bool {
        self.disposition == ContractDisposition::Execute
    }

    /// Runtime plan consumed by the kernel.
    #[must_use]
    pub fn plan(&self) -> &RuntimePlan {
        &self.plan
    }
}

impl Validatable for KernelCycle {
    fn validate(&self) -> Result<(), ContractError> {
        self.plan.validate()
    }
}

impl FailClosed for KernelCycle {
    type Output = ContractDisposition;

    fn fail_closed(&self) -> Self::Output {
        ContractDisposition::Deny
    }
}
