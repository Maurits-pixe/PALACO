#![forbid(unsafe_code)]

pub mod authorization;
pub mod domain;
pub mod decision;
pub mod event;
pub mod assessment;
pub mod event_store;
pub mod execution;
pub mod persistence;
pub mod signature;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use domain::{AuthorizationId, AuthorityId, DecisionId, EvidenceId, QuestionId};
pub use event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
pub use event_store::{EventStore, EventStoreError};
pub use execution::{gate as execution_gate, ExecutionGateError, ExecutionPermit, ExecutionRequest};
pub use persistence::postgres::PgEventStore;
pub use signature::{CanonicalSigner, CanonicalVerifier};
pub use verification::{CanonicalBytes, Sha256Digest};
