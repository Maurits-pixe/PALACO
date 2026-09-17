#![forbid(unsafe_code)]

pub mod domain;
pub mod event;
pub mod assessment;
pub mod event_store;
pub mod persistence;
pub mod signature;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use domain::{AuthorizationId, DecisionId, EvidenceId, QuestionId};
pub use event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
pub use event_store::{EventStore, EventStoreError};
pub use persistence::postgres::PgEventStore;
pub use signature::{CanonicalSigner, CanonicalVerifier};
pub use verification::{CanonicalBytes, Sha256Digest};
