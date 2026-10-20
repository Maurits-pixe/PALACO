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
    /// Admission is closed while pending plans await transfer.
    Draining,
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

/// Process-local queue lifecycle, not the state of external work.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueueState {
    /// New plans may be admitted.
    Running,
    /// Admission is closed; pending plans may still be transferred.
    Draining,
    /// Admission is permanently closed and no plans remain pending.
    Stopped,
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
    state: QueueState,
}

impl RuntimeQueue {
    /// Creates an empty queue. Zero capacity rejects every submission as full.
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        Self {
            pending: VecDeque::new(),
            capacity,
            state: QueueState::Running,
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

    /// Borrows pending plans in FIFO order without transferring or cloning them.
    ///
    /// Compatible with the inspection module's iterator APIs. Reading or
    /// dropping this iterator does not change queue state, even during drain.
    /// The borrow prevents queue mutation while yielded references are in use;
    /// it is not a detached snapshot or a current-authority check.
    pub fn pending(
        &self,
    ) -> impl ExactSizeIterator<Item = &RuntimePlan> + DoubleEndedIterator + '_ {
        self.pending.iter()
    }

    /// Whether this queue has been permanently stopped.
    #[must_use]
    pub fn is_stopped(&self) -> bool {
        self.state == QueueState::Stopped
    }

    /// Returns the local queue lifecycle, not execution completion.
    #[must_use]
    pub fn state(&self) -> QueueState {
        self.state
    }

    /// Permanently closes admission while retaining pending plans for transfer.
    ///
    /// Empty queues stop immediately. Otherwise the queue stops when the final
    /// pending plan is transferred by [`Self::next_plan`]. Repeated calls do
    /// nothing, including after stop. No external work is executed or awaited.
    pub fn begin_drain(&mut self) {
        if self.state == QueueState::Running {
            self.state = if self.pending.is_empty() {
                QueueState::Stopped
            } else {
                QueueState::Draining
            };
        }
    }

    /// Admits a plan only if running, carrying Execute, valid and below capacity.
    ///
    /// On rejection, the queue is unchanged and the caller recovers the plan.
    /// No source or output I/O, execution or live authority check is performed.
    pub fn submit(&mut self, plan: RuntimePlan) -> Result<(), RejectedPlan> {
        let reason = match self.state {
            QueueState::Stopped => Some(AdmissionError::Stopped),
            QueueState::Draining => Some(AdmissionError::Draining),
            QueueState::Running => match plan.disposition() {
                ContractDisposition::Hold => Some(AdmissionError::Held),
                ContractDisposition::Deny => Some(AdmissionError::Denied),
                ContractDisposition::Execute => match plan.validate() {
                    Err(error) => Some(AdmissionError::Invalid(error)),
                    Ok(()) if self.pending.len() == self.capacity => Some(AdmissionError::Full),
                    Ok(()) => None,
                },
            },
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
        let plan = self.pending.pop_front();
        if self.state == QueueState::Draining && self.pending.is_empty() {
            self.state = QueueState::Stopped;
        }
        plan
    }

    /// Permanently stops admission and discards pending local plans.
    ///
    /// Returns the number discarded. Repeated calls return zero. Already
    /// transferred plans are outside this queue: no work is cancelled externally
    /// and no authority is revoked. There is deliberately no restart operation.
    pub fn stop(&mut self) -> usize {
        self.state = QueueState::Stopped;
        let discarded = self.pending.len();
        self.pending.clear();
        discarded
    }
}
