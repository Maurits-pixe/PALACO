//! ERA-009 process-local reference model; no durable or external execution effects.

use std::{collections::HashMap, error::Error, fmt, sync::Mutex};

use palaco_foundation::{ContractError, EvidenceRef, Validatable};

use crate::ExecutionBoundary;

/// Acknowledgement of an in-memory commit, not proof of external execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CommitReceipt {
    sequence: u64,
}

impl CommitReceipt {
    /// Position in this gate's local commit/revocation order, starting at one.
    #[must_use]
    pub fn sequence(self) -> u64 {
        self.sequence
    }
}

/// Classification of an in-memory acknowledgement, never execution permission.
///
/// The classification is made under the same lock as commit and revocation.
/// Neither variant establishes current authority or performs an external effect.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommitOutcome {
    /// This call inserted a new local record.
    Recorded(CommitReceipt),
    /// This call returned the receipt of an earlier exact-match record.
    Replayed(CommitReceipt),
}

impl CommitOutcome {
    /// Original local receipt, whether newly recorded or replayed.
    #[must_use]
    pub fn receipt(self) -> CommitReceipt {
        match self {
            Self::Recorded(receipt) | Self::Replayed(receipt) => receipt,
        }
    }
}

/// Fail-closed outcomes of the process-local model.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommitGateError {
    /// The supplied provenance does not carry valid authority.
    InvalidBoundary(ContractError),
    /// This gate has been permanently revoked.
    Revoked,
    /// A key was reused with a different payload or boundary.
    IdempotencyConflict,
    /// A panic poisoned the gate's mutex; state must not be trusted.
    Unavailable,
    /// The local sequence cannot advance without wrapping.
    SequenceExhausted,
}

impl fmt::Display for CommitGateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBoundary(error) => write!(formatter, "invalid commit boundary: {error}"),
            Self::Revoked => formatter.write_str("process-local gate is revoked"),
            Self::IdempotencyConflict => formatter.write_str("idempotency key conflicts"),
            Self::Unavailable => formatter.write_str("process-local gate is unavailable"),
            Self::SequenceExhausted => formatter.write_str("process-local sequence is exhausted"),
        }
    }
}

impl Error for CommitGateError {}

struct Committed {
    boundary: ExecutionBoundary,
    payload: Vec<u8>,
    receipt: CommitReceipt,
}

#[derive(Default)]
struct State {
    sequence: u64,
    revoked_at: Option<u64>,
    commits: HashMap<String, Committed>,
}

impl State {
    fn next_sequence(&self) -> Result<u64, CommitGateError> {
        self.sequence
            .checked_add(1)
            .ok_or(CommitGateError::SequenceExhausted)
    }
}

/// Mutex-serialized reference model for one caller-defined authority context.
///
/// Share the same instance between callers (for example via `Arc`). Separate
/// instances have independent state, even within one process. The caller binds
/// the gate to an authority context; this model does not authenticate that binding.
/// All payloads and keys remain in memory without eviction. No persistence,
/// replication, runtime wiring, or external side effects are provided.
#[derive(Default)]
pub struct InMemoryCommitGate {
    state: Mutex<State>,
}

impl InMemoryCommitGate {
    /// Creates an empty, unrevoked local gate; this does not grant authority.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Records a validated request or returns the original exact-match receipt.
    ///
    /// Key, payload bytes, and complete boundary must match for a retry. An exact
    /// retry after revocation only acknowledges an earlier commit; it does not
    /// authorize execution. Conflicting retries and rejected requests consume no
    /// sequence positions. Validation of caller-supplied authority is not
    /// authentication or a refresh from an external authority service.
    ///
    /// Use [`Self::commit_with_outcome`] to distinguish new records from retries.
    pub fn commit(
        &self,
        key: &EvidenceRef,
        boundary: &ExecutionBoundary,
        payload: &[u8],
    ) -> Result<CommitReceipt, CommitGateError> {
        self.commit_with_outcome(key, boundary, payload)
            .map(CommitOutcome::receipt)
    }

    /// Records or replays a request with an explicit local acknowledgement kind.
    ///
    /// Uses the same validation, error precedence, and sequence semantics as
    /// [`Self::commit`]. Exactly one successful caller records a given key; exact
    /// retries replay it, including after revocation. `Recorded` is not a permit
    /// to execute: revocation may occur before the caller even receives it.
    pub fn commit_with_outcome(
        &self,
        key: &EvidenceRef,
        boundary: &ExecutionBoundary,
        payload: &[u8],
    ) -> Result<CommitOutcome, CommitGateError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| CommitGateError::Unavailable)?;
        boundary
            .record()
            .validate()
            .map_err(CommitGateError::InvalidBoundary)?;
        if let Some(committed) = state.commits.get(key.as_str()) {
            return if committed.boundary == *boundary && committed.payload == payload {
                Ok(CommitOutcome::Replayed(committed.receipt))
            } else {
                Err(CommitGateError::IdempotencyConflict)
            };
        }
        if state.revoked_at.is_some() {
            return Err(CommitGateError::Revoked);
        }
        let sequence = state.next_sequence()?;
        let receipt = CommitReceipt { sequence };
        state.commits.insert(
            key.as_str().to_owned(),
            Committed {
                boundary: boundary.clone(),
                payload: payload.to_vec(),
                receipt,
            },
        );
        state.sequence = sequence;
        Ok(CommitOutcome::Recorded(receipt))
    }

    /// Permanently revokes this instance in the same local order as commits.
    ///
    /// Repeated revocation returns the original position without advancing it.
    /// Exhaustion returns an error without changing state; no new commits can
    /// then be recorded either. Revocation does not undo earlier commits.
    pub fn revoke(&self) -> Result<u64, CommitGateError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| CommitGateError::Unavailable)?;
        if let Some(sequence) = state.revoked_at {
            return Ok(sequence);
        }
        let sequence = state.next_sequence()?;
        state.revoked_at = Some(sequence);
        state.sequence = sequence;
        Ok(sequence)
    }
}

#[cfg(test)]
mod tests {
    use super::{CommitGateError, InMemoryCommitGate, State};

    #[test]
    fn exhausted_sequence_does_not_wrap_or_mutate_revocation() {
        let gate = InMemoryCommitGate {
            state: std::sync::Mutex::new(State {
                sequence: u64::MAX,
                ..State::default()
            }),
        };
        assert_eq!(gate.revoke(), Err(CommitGateError::SequenceExhausted));
        let state = gate.state.lock().expect("gate must remain usable");
        assert_eq!(state.sequence, u64::MAX);
        assert_eq!(state.revoked_at, None);
        assert!(state.commits.is_empty());
    }

    #[test]
    fn final_sequence_is_usable_and_revocation_retries_do_not_advance_it() {
        let gate = InMemoryCommitGate {
            state: std::sync::Mutex::new(State {
                sequence: u64::MAX - 1,
                ..State::default()
            }),
        };
        assert_eq!(gate.revoke(), Ok(u64::MAX));
        assert_eq!(gate.revoke(), Ok(u64::MAX));
        assert_eq!(
            gate.state
                .lock()
                .expect("gate remains usable")
                .next_sequence(),
            Err(CommitGateError::SequenceExhausted)
        );
    }

    #[test]
    fn poisoned_mutex_fails_closed() {
        let gate = InMemoryCommitGate::new();
        let _ = std::panic::catch_unwind(|| {
            let _guard = gate.state.lock().expect("gate must start usable");
            panic!("simulate an interrupted operation");
        });
        assert_eq!(gate.revoke(), Err(CommitGateError::Unavailable));
    }
}
