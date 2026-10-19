//! Bounded, process-local scheduling of caller-supplied plans.
//!
//! Admission is not authority authentication. No task, callback or external
//! effect is executed here. Consumers must independently justify execution.

use crate::RuntimePlan;
use palaco_foundation::{ContractDisposition, ContractError, Validatable};
use std::collections::VecDeque;

/// Reason a plan was not admitted, in precedence order: stopped, disposition,
/// validation, capacity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdmissionError {
    /// The queue has been permanently stopped.
    Stopped,
    /// The supplied plan carries Hold.
    Held,
    /// The supplied plan carries Deny.
    Denied,
    /// The existing contract chain rejected the plan.
    Invalid(ContractError),
    /// The pending-plan limit has been reached.
    Full,
}

/// An admission failure retaining ownership of the unmodified supplied plan.
///
/// Debug output includes the plan and may contain caller-provided evidence.
#[derive(Debug)]
pub struct RejectedPlan {
    reason: AdmissionError,
    plan: RuntimePlan,
}

impl RejectedPlan {
    /// Returns the admission failure, not an authorization decision.
    #[must_use]
    pub fn reason(&self) -> AdmissionError {
        self.reason
    }

    /// Recovers the original plan without changing its disposition.
    #[must_use]
    pub fn into_plan(self) -> RuntimePlan {
        self.plan
    }
}

/// Single-owner FIFO with a fixed maximum number of pending plans.
///
/// The limit counts plans, not bytes. Storage grows only on admission; it is
/// neither preallocated to the limit nor durable. Duplicate submissions are not
/// deduplicated. A plan carrying Execute must also pass existing validation,
/// but neither check establishes current authority or authenticates evidence.
#[derive(Debug)]
pub struct RuntimeQueue {
    pending: VecDeque<RuntimePlan>,
    capacity: usize,
    stopped: bool,
}

impl RuntimeQueue {
    /// Creates an empty queue. Zero capacity rejects every submission as full.
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        Self {
            pending: VecDeque::new(),
            capacity,
            stopped: false,
        }
    }

    /// Maximum number of pending plans.
    #[must_use]
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// Current number of pending plans.
    #[must_use]
    pub fn len(&self) -> usize {
        self.pending.len()
    }

    /// Whether no plans are pending.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }

    /// Whether this queue has been permanently stopped.
    #[must_use]
    pub fn is_stopped(&self) -> bool {
        self.stopped
    }

    /// Admits a plan only if running, carrying Execute, valid and below capacity.
    ///
    /// On rejection, the queue is unchanged and the caller recovers the plan.
    /// No source or output I/O, execution or live authority check is performed.
    pub fn submit(&mut self, plan: RuntimePlan) -> Result<(), RejectedPlan> {
        let reason = if self.stopped {
            Some(AdmissionError::Stopped)
        } else {
            match plan.disposition() {
                ContractDisposition::Hold => Some(AdmissionError::Held),
                ContractDisposition::Deny => Some(AdmissionError::Denied),
                ContractDisposition::Execute => match plan.validate() {
                    Err(error) => Some(AdmissionError::Invalid(error)),
                    Ok(()) if self.pending.len() == self.capacity => Some(AdmissionError::Full),
                    Ok(()) => None,
                },
            }
        };
        if let Some(reason) = reason {
            return Err(RejectedPlan { reason, plan });
        }
        self.pending.push_back(plan);
        Ok(())
    }

    /// Transfers the oldest pending plan back to the caller, without executing it.
    ///
    /// This does not refresh authority. The caller must enforce current policy
    /// before any execution; a previous admission grants no execution permission.
    pub fn next_plan(&mut self) -> Option<RuntimePlan> {
        self.pending.pop_front()
    }

    /// Permanently stops admission and discards pending local plans.
    ///
    /// Returns the number discarded. Repeated calls return zero. Already
    /// transferred plans are outside this queue: no work is cancelled externally
    /// and no authority is revoked. There is deliberately no restart operation.
    pub fn stop(&mut self) -> usize {
        self.stopped = true;
        let discarded = self.pending.len();
        self.pending.clear();
        discarded
    }
}
