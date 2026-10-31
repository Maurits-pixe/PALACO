#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Hash-chained execution evidence and its audit metadata.
//!
//! This crate records evidence only. A valid chain does not establish identity,
//! authority, authenticity of an actor, or permission to execute or replay an
//! operation.

use std::{error::Error, fmt};

use palaco_foundation::EvidenceRef;
use sha2::{Digest, Sha256};

const HASH_DOMAIN: &[u8] = b"PALACO-EXECUTION-EVIDENCE-V1";

/// A SHA-256 digest.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EvidenceDigest([u8; 32]);

impl EvidenceDigest {
    /// Calculates the digest of exact bytes.
    #[must_use]
    pub fn calculate(bytes: &[u8]) -> Self {
        let digest = Sha256::digest(bytes);
        let mut value = [0_u8; 32];
        value.copy_from_slice(&digest);
        Self(value)
    }

    /// Returns the digest bytes.
    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

/// Outcome of an execution invariant check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvariantStatus {
    /// All recorded invariants passed.
    Verified,
    /// An invariant failed with the supplied description.
    Failed(String),
}

/// Replay provenance recorded as metadata; it never grants permission to replay.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReplayMetadata {
    /// This execution is not identified as a replay.
    Original,
    /// This execution claims to be a replay of the referenced execution.
    ReplayOf(String),
}

/// Kind of audit event associated with a record.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuditEventKind {
    /// An original execution was recorded.
    EvidenceRecorded,
    /// A replay execution was recorded.
    ReplayRecorded,
    /// Evidence records a failed invariant.
    InvariantFailed,
}

/// Audit event attached to an execution-evidence record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditEvent {
    evidence_ref: EvidenceRef,
    occurred_at_unix_ms: u64,
    kind: AuditEventKind,
}

impl AuditEvent {
    /// Evidence reference associated with this event.
    #[must_use]
    pub fn evidence_ref(&self) -> &EvidenceRef {
        &self.evidence_ref
    }

    /// Event time in Unix milliseconds.
    #[must_use]
    pub const fn occurred_at_unix_ms(&self) -> u64 {
        self.occurred_at_unix_ms
    }

    /// Event classification.
    #[must_use]
    pub const fn kind(&self) -> AuditEventKind {
        self.kind
    }
}

/// Immutable record of one execution's evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionEvidence {
    evidence_ref: EvidenceRef,
    execution_id: String,
    sequence: u64,
    occurred_at_unix_ms: u64,
    contract_hash: EvidenceDigest,
    input_hash: EvidenceDigest,
    invariant_status: InvariantStatus,
    result_hash: EvidenceDigest,
    previous_evidence_hash: Option<EvidenceDigest>,
    replay_metadata: ReplayMetadata,
    audit_event: AuditEvent,
    evidence_hash: EvidenceDigest,
}

impl ExecutionEvidence {
    /// Creates an evidence record and calculates its hash.
    ///
    /// The sequence and predecessor are checked when the record is appended
    /// to an [`EvidenceChain`].
    ///
    /// # Errors
    ///
    /// Returns [`EvidenceError::EmptyExecutionId`] for an empty execution ID or
    /// [`EvidenceError::EmptyReplaySource`] for an empty replay source ID.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        evidence_ref: EvidenceRef,
        execution_id: impl Into<String>,
        sequence: u64,
        occurred_at_unix_ms: u64,
        contract_hash: EvidenceDigest,
        input_hash: EvidenceDigest,
        invariant_status: InvariantStatus,
        result_hash: EvidenceDigest,
        previous_evidence_hash: Option<EvidenceDigest>,
        replay_metadata: ReplayMetadata,
    ) -> Result<Self, EvidenceError> {
        let execution_id = execution_id.into();
        if execution_id.trim().is_empty() {
            return Err(EvidenceError::EmptyExecutionId);
        }
        if matches!(&replay_metadata, ReplayMetadata::ReplayOf(source) if source.trim().is_empty())
        {
            return Err(EvidenceError::EmptyReplaySource);
        }

        let audit_kind = match (&invariant_status, &replay_metadata) {
            (InvariantStatus::Failed(_), _) => AuditEventKind::InvariantFailed,
            (_, ReplayMetadata::ReplayOf(_)) => AuditEventKind::ReplayRecorded,
            (InvariantStatus::Verified, ReplayMetadata::Original) => {
                AuditEventKind::EvidenceRecorded
            }
        };
        let audit_event = AuditEvent {
            evidence_ref: evidence_ref.clone(),
            occurred_at_unix_ms,
            kind: audit_kind,
        };
        let evidence_hash = Self::calculate_hash(
            &evidence_ref,
            &execution_id,
            sequence,
            occurred_at_unix_ms,
            contract_hash,
            input_hash,
            &invariant_status,
            result_hash,
            previous_evidence_hash,
            &replay_metadata,
            audit_kind,
        );

        Ok(Self {
            evidence_ref,
            execution_id,
            sequence,
            occurred_at_unix_ms,
            contract_hash,
            input_hash,
            invariant_status,
            result_hash,
            previous_evidence_hash,
            replay_metadata,
            audit_event,
            evidence_hash,
        })
    }

    /// Stable evidence reference.
    #[must_use]
    pub fn evidence_ref(&self) -> &EvidenceRef {
        &self.evidence_ref
    }

    /// Execution identifier.
    #[must_use]
    pub fn execution_id(&self) -> &str {
        &self.execution_id
    }

    /// One-based position in the evidence chain.
    #[must_use]
    pub const fn sequence(&self) -> u64 {
        self.sequence
    }

    /// Event time in Unix milliseconds.
    #[must_use]
    pub const fn occurred_at_unix_ms(&self) -> u64 {
        self.occurred_at_unix_ms
    }

    /// Hash of the governing contract.
    #[must_use]
    pub const fn contract_hash(&self) -> EvidenceDigest {
        self.contract_hash
    }

    /// Hash of the execution input.
    #[must_use]
    pub const fn input_hash(&self) -> EvidenceDigest {
        self.input_hash
    }

    /// Recorded invariant result.
    #[must_use]
    pub const fn invariant_status(&self) -> &InvariantStatus {
        &self.invariant_status
    }

    /// Hash of the execution result.
    #[must_use]
    pub const fn result_hash(&self) -> EvidenceDigest {
        self.result_hash
    }

    /// Hash of the immediately preceding record, if any.
    #[must_use]
    pub const fn previous_evidence_hash(&self) -> Option<EvidenceDigest> {
        self.previous_evidence_hash
    }

    /// Replay metadata, which does not establish replay permission.
    #[must_use]
    pub const fn replay_metadata(&self) -> &ReplayMetadata {
        &self.replay_metadata
    }

    /// Audit event derived from the invariant status and replay metadata.
    #[must_use]
    pub const fn audit_event(&self) -> &AuditEvent {
        &self.audit_event
    }

    /// Hash of this complete record.
    #[must_use]
    pub const fn evidence_hash(&self) -> EvidenceDigest {
        self.evidence_hash
    }

    /// Recomputes this record's hash and checks its attached audit metadata.
    #[must_use]
    pub fn verify(&self) -> bool {
        let expected_kind = match (&self.invariant_status, &self.replay_metadata) {
            (InvariantStatus::Failed(_), _) => AuditEventKind::InvariantFailed,
            (_, ReplayMetadata::ReplayOf(_)) => AuditEventKind::ReplayRecorded,
            (InvariantStatus::Verified, ReplayMetadata::Original) => {
                AuditEventKind::EvidenceRecorded
            }
        };
        self.audit_event.evidence_ref == self.evidence_ref
            && self.audit_event.occurred_at_unix_ms == self.occurred_at_unix_ms
            && self.audit_event.kind == expected_kind
            && self.evidence_hash
                == Self::calculate_hash(
                    &self.evidence_ref,
                    &self.execution_id,
                    self.sequence,
                    self.occurred_at_unix_ms,
                    self.contract_hash,
                    self.input_hash,
                    &self.invariant_status,
                    self.result_hash,
                    self.previous_evidence_hash,
                    &self.replay_metadata,
                    expected_kind,
                )
    }

    #[allow(clippy::too_many_arguments)]
    fn calculate_hash(
        evidence_ref: &EvidenceRef,
        execution_id: &str,
        sequence: u64,
        occurred_at_unix_ms: u64,
        contract_hash: EvidenceDigest,
        input_hash: EvidenceDigest,
        invariant_status: &InvariantStatus,
        result_hash: EvidenceDigest,
        previous_evidence_hash: Option<EvidenceDigest>,
        replay_metadata: &ReplayMetadata,
        audit_kind: AuditEventKind,
    ) -> EvidenceDigest {
        let mut hasher = Sha256::new();
        hasher.update(HASH_DOMAIN);
        hash_string(&mut hasher, evidence_ref.as_str());
        hash_string(&mut hasher, execution_id);
        hasher.update(sequence.to_be_bytes());
        hasher.update(occurred_at_unix_ms.to_be_bytes());
        hasher.update(contract_hash.as_bytes());
        hasher.update(input_hash.as_bytes());
        match invariant_status {
            InvariantStatus::Verified => hasher.update([0]),
            InvariantStatus::Failed(reason) => {
                hasher.update([1]);
                hash_string(&mut hasher, reason);
            }
        }
        hasher.update(result_hash.as_bytes());
        match previous_evidence_hash {
            Some(hash) => {
                hasher.update([1]);
                hasher.update(hash.as_bytes());
            }
            None => hasher.update([0]),
        }
        match replay_metadata {
            ReplayMetadata::Original => hasher.update([0]),
            ReplayMetadata::ReplayOf(source) => {
                hasher.update([1]);
                hash_string(&mut hasher, source);
            }
        }
        hasher.update([match audit_kind {
            AuditEventKind::EvidenceRecorded => 0,
            AuditEventKind::ReplayRecorded => 1,
            AuditEventKind::InvariantFailed => 2,
        }]);
        let digest = hasher.finalize();
        let mut value = [0_u8; 32];
        value.copy_from_slice(&digest);
        EvidenceDigest(value)
    }
}

/// Ordered evidence records with append-time and full-chain validation.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EvidenceChain {
    records: Vec<ExecutionEvidence>,
}

impl EvidenceChain {
    /// Creates an empty evidence chain.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            records: Vec::new(),
        }
    }

    /// Appends a valid record to this chain.
    ///
    /// # Errors
    ///
    /// Returns an error if the record hash, sequence, or predecessor is invalid.
    pub fn append(&mut self, record: ExecutionEvidence) -> Result<(), EvidenceError> {
        if !record.verify() {
            return Err(EvidenceError::HashMismatch);
        }
        match self.records.last() {
            None => {
                if record.sequence != 1 {
                    return Err(EvidenceError::InvalidGenesis);
                }
                if record.previous_evidence_hash.is_some() {
                    return Err(EvidenceError::PreviousHashMismatch);
                }
            }
            Some(previous) => {
                let expected = previous
                    .sequence
                    .checked_add(1)
                    .ok_or(EvidenceError::SequenceOverflow)?;
                if record.sequence != expected {
                    return Err(EvidenceError::InvalidSequence {
                        expected,
                        actual: record.sequence,
                    });
                }
                if record.previous_evidence_hash != Some(previous.evidence_hash) {
                    return Err(EvidenceError::PreviousHashMismatch);
                }
            }
        }
        self.records.push(record);
        Ok(())
    }

    /// Returns the records in chain order.
    #[must_use]
    pub fn records(&self) -> &[ExecutionEvidence] {
        &self.records
    }

    /// Verifies every record and predecessor link in the chain.
    ///
    /// # Errors
    ///
    /// Returns an error at the first invalid record or link.
    pub fn verify(&self) -> Result<(), EvidenceError> {
        let mut previous_hash = None;
        for (index, record) in self.records.iter().enumerate() {
            let expected = u64::try_from(index)
                .ok()
                .and_then(|value| value.checked_add(1))
                .ok_or(EvidenceError::SequenceOverflow)?;
            if record.sequence != expected {
                return Err(EvidenceError::InvalidSequence {
                    expected,
                    actual: record.sequence,
                });
            }
            if record.previous_evidence_hash != previous_hash {
                return Err(EvidenceError::PreviousHashMismatch);
            }
            if !record.verify() {
                return Err(EvidenceError::HashMismatch);
            }
            previous_hash = Some(record.evidence_hash);
        }
        Ok(())
    }
}

/// Failures encountered while creating or validating evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EvidenceError {
    /// Execution identifiers must not be empty.
    EmptyExecutionId,
    /// Replay source identifiers must not be empty.
    EmptyReplaySource,
    /// The first chain record must have sequence one and no predecessor.
    InvalidGenesis,
    /// A record's sequence differs from the expected chain position.
    InvalidSequence {
        /// Expected one-based sequence.
        expected: u64,
        /// Actual sequence in the record.
        actual: u64,
    },
    /// The predecessor hash does not match the previous record.
    PreviousHashMismatch,
    /// The record hash or audit metadata does not verify.
    HashMismatch,
    /// No larger sequence number can be represented.
    SequenceOverflow,
}

impl fmt::Display for EvidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyExecutionId => formatter.write_str("execution ID must not be empty"),
            Self::EmptyReplaySource => formatter.write_str("replay source ID must not be empty"),
            Self::InvalidGenesis => {
                formatter.write_str("genesis evidence must have sequence one and no predecessor")
            }
            Self::InvalidSequence { expected, actual } => {
                write!(
                    formatter,
                    "expected evidence sequence {expected}, got {actual}"
                )
            }
            Self::PreviousHashMismatch => {
                formatter.write_str("previous evidence hash does not match the chain")
            }
            Self::HashMismatch => formatter.write_str("evidence hash or audit metadata is invalid"),
            Self::SequenceOverflow => formatter.write_str("evidence sequence overflow"),
        }
    }
}

impl Error for EvidenceError {}

fn hash_string(hasher: &mut Sha256, value: &str) {
    hasher.update(value.as_bytes());
    // UTF-8 never contains 0xff, so this separates adjacent strings unambiguously.
    hasher.update([u8::MAX]);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence(
        sequence: u64,
        previous: Option<EvidenceDigest>,
    ) -> Result<ExecutionEvidence, Box<dyn Error>> {
        Ok(ExecutionEvidence::new(
            EvidenceRef::new(format!("evidence-{sequence}"))?,
            format!("execution-{sequence}"),
            sequence,
            sequence * 1_000,
            EvidenceDigest::calculate(b"contract"),
            EvidenceDigest::calculate(b"input"),
            InvariantStatus::Verified,
            EvidenceDigest::calculate(b"result"),
            previous,
            ReplayMetadata::Original,
        )?)
    }

    #[test]
    fn digest_is_deterministic_for_exact_bytes() {
        assert_eq!(
            EvidenceDigest::calculate(b"PALACO"),
            EvidenceDigest::calculate(b"PALACO")
        );
        assert_ne!(
            EvidenceDigest::calculate(b"PALACO"),
            EvidenceDigest::calculate(b"PALACO ")
        );
    }

    #[test]
    fn chain_links_records_and_verifies_them() -> Result<(), Box<dyn Error>> {
        let first = evidence(1, None)?;
        let first_hash = first.evidence_hash();
        let mut chain = EvidenceChain::new();
        chain.append(first)?;
        chain.append(evidence(2, Some(first_hash))?)?;

        assert_eq!(chain.records().len(), 2);
        assert_eq!(chain.verify(), Ok(()));
        Ok(())
    }

    #[test]
    fn chain_rejects_a_broken_predecessor_link() -> Result<(), Box<dyn Error>> {
        let mut chain = EvidenceChain::new();
        chain.append(evidence(1, None)?)?;
        assert_eq!(
            chain.append(evidence(2, Some(EvidenceDigest::calculate(b"wrong")))?),
            Err(EvidenceError::PreviousHashMismatch)
        );
        Ok(())
    }

    #[test]
    fn chain_rejects_a_skipped_sequence() -> Result<(), Box<dyn Error>> {
        let mut chain = EvidenceChain::new();
        assert_eq!(
            chain.append(evidence(2, None)?),
            Err(EvidenceError::InvalidGenesis)
        );
        Ok(())
    }

    #[test]
    fn record_verification_detects_field_changes() -> Result<(), Box<dyn Error>> {
        let mut record = evidence(1, None)?;
        record.execution_id = "changed-execution".to_owned();

        assert!(!record.verify());
        Ok(())
    }

    #[test]
    fn failed_invariant_is_reflected_in_the_audit_event() -> Result<(), Box<dyn Error>> {
        let record = ExecutionEvidence::new(
            EvidenceRef::new("evidence-failure")?,
            "execution-failure",
            1,
            1_000,
            EvidenceDigest::calculate(b"contract"),
            EvidenceDigest::calculate(b"input"),
            InvariantStatus::Failed("contract mismatch".to_owned()),
            EvidenceDigest::calculate(b"result"),
            None,
            ReplayMetadata::Original,
        )?;

        assert_eq!(record.audit_event().kind(), AuditEventKind::InvariantFailed);
        assert!(record.verify());
        Ok(())
    }

    #[test]
    fn replay_metadata_is_recorded_without_granting_execution_authority()
    -> Result<(), Box<dyn Error>> {
        let record = ExecutionEvidence::new(
            EvidenceRef::new("evidence-replay")?,
            "execution-replay",
            1,
            1_000,
            EvidenceDigest::calculate(b"contract"),
            EvidenceDigest::calculate(b"input"),
            InvariantStatus::Verified,
            EvidenceDigest::calculate(b"result"),
            None,
            ReplayMetadata::ReplayOf("execution-original".to_owned()),
        )?;

        assert_eq!(record.audit_event().kind(), AuditEventKind::ReplayRecorded);
        assert_eq!(
            record.replay_metadata(),
            &ReplayMetadata::ReplayOf("execution-original".to_owned())
        );
        Ok(())
    }

    #[test]
    fn empty_execution_and_replay_ids_are_rejected() -> Result<(), Box<dyn Error>> {
        let common_ref = || EvidenceRef::new("evidence");
        let common_hash = || EvidenceDigest::calculate(b"fixture");
        assert_eq!(
            ExecutionEvidence::new(
                common_ref()?,
                " ",
                1,
                1,
                common_hash(),
                common_hash(),
                InvariantStatus::Verified,
                common_hash(),
                None,
                ReplayMetadata::Original,
            ),
            Err(EvidenceError::EmptyExecutionId)
        );
        assert_eq!(
            ExecutionEvidence::new(
                common_ref()?,
                "execution",
                1,
                1,
                common_hash(),
                common_hash(),
                InvariantStatus::Verified,
                common_hash(),
                None,
                ReplayMetadata::ReplayOf(" ".to_owned()),
            ),
            Err(EvidenceError::EmptyReplaySource)
        );
        Ok(())
    }
}
