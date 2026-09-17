#![forbid(unsafe_code)]

pub mod authorization;
pub mod domain;
pub mod decision;
pub mod event;
pub mod assessment;
pub mod event_store;
pub mod execution;
pub mod persistence;
pub mod consequence;
pub mod receipt;
pub mod revocation;
pub mod lifecycle;
pub mod signature;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use domain::{AuthorityId, AuthorizationId, DecisionId, EvidenceId, QuestionId};
pub use event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
pub use event_store::{EventStore, EventStoreError};
pub use execution::{
    ExecutionGateError, ExecutionPermit, ExecutionRequest, gate as execution_gate,
};
pub use receipt::{ExecutionReceipt, ExecutionStatus, ObservationReceipt};
pub use persistence::postgres::PgEventStore;
pub use signature::{CanonicalSigner, CanonicalVerifier};
pub use verification::{CanonicalBytes, Sha256Digest};

pub use consequence::{ConsequenceReceipt, Reassessment, ReassessmentTrigger};
pub use lifecycle::{
    ExecutionDisposition, LifecycleReason, evaluate as evaluate_execution_lifecycle,
};

pub use revocation::{propagate as propagate_revocation, PropagationReceipt, PropagationStatus, RevocationReason, RevocationReceipt};
