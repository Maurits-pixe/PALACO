#![forbid(unsafe_code)]

pub mod domain;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use domain::{AuthorizationId, DecisionId, EvidenceId, QuestionId};
pub use verification::{CanonicalBytes, Sha256Digest};
