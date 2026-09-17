#![forbid(unsafe_code)]

pub mod assessment;
pub mod authorization;
pub mod comet;
pub mod consequence;
pub mod decision;
pub mod domain;
pub mod event;
pub mod event_store;
pub mod execution;
pub mod lifecycle;
pub mod persistence;
pub mod receipt;
pub mod revocation;
pub mod signature;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use domain::{
    AuthorityId, AuthorizationId, AuthorizationStatus, DecisionId, EvidenceId, QuestionId,
};
pub use event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
pub use event_store::{EventStore, EventStoreError};
pub use execution::{
    gate as execution_gate, ExecutionGateError, ExecutionPermit, ExecutionRequest,
};
pub use receipt::{ExecutionReceipt, ExecutionStatus, ObservationReceipt};
pub use persistence::postgres::PgEventStore;
pub use signature::{CanonicalSigner, CanonicalVerifier};
pub use verification::{CanonicalBytes, Sha256Digest};

pub use consequence::{ConsequenceReceipt, Reassessment, ReassessmentTrigger};
pub use lifecycle::{
    evaluate as evaluate_execution_lifecycle, ExecutionDisposition, LifecycleReason,
};
pub use revocation::{
    propagate as propagate_revocation, PropagationReceipt, PropagationStatus, RevocationReason,
    RevocationReceipt,
};
pub use comet::{
    apply_invalidation as apply_comet_invalidation, propagate_revocation as propagate_comet_revocation,
    AuthorizationInvalidation, CometError, CometPropagationStatus,
};
