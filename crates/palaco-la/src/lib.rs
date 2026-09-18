#![forbid(unsafe_code)]

pub mod assessment;
pub mod authorization;
pub mod authorization_replay;
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
pub mod replay;
pub mod revocation;
pub mod signature;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use authorization_replay::{
    AuthorizationReplay, AuthorizationReplayError, replay_authorization_history,
};
pub use domain::{
    AuthorityId, AuthorizationId, AuthorizationStatus, DecisionId, EvidenceId, QuestionId,
};
pub use event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
pub use event_store::{EventStore, EventStoreError};
pub use execution::{
    ExecutionGateError, ExecutionPermit, ExecutionRequest, gate as execution_gate,
};
pub use persistence::postgres::PgEventStore;
pub use receipt::{ExecutionReceipt, ExecutionStatus, ObservationReceipt};
pub use replay::{ReplayError, verify_history};
pub use signature::{CanonicalSigner, CanonicalVerifier};
pub use verification::{CanonicalBytes, Sha256Digest};

pub use authorization::{AUTHORIZATION_ISSUED_EVENT_TYPE, canonical_authorization_issued_payload};
pub use comet::{
    AuthorizationInvalidation, CometError, CometPropagationStatus,
    apply_invalidation as apply_comet_invalidation,
    propagate_revocation as propagate_comet_revocation,
};
pub use consequence::{ConsequenceReceipt, Reassessment, ReassessmentTrigger};
pub use lifecycle::{
    ExecutionDisposition, LifecycleReason, evaluate as evaluate_execution_lifecycle,
};
pub use revocation::{
    PropagationReceipt, PropagationStatus, RevocationReason, RevocationReceipt,
    propagate as propagate_revocation,
};
