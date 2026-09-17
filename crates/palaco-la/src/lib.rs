#![forbid(unsafe_code)]

pub mod domain;
pub mod signature;
pub mod verification;

#[cfg(test)]
mod architecture_tests;

pub use domain::{AuthorizationId, DecisionId, EvidenceId, QuestionId};
pub use signature::{CanonicalSigner, CanonicalVerifier};
pub use verification::{CanonicalBytes, Sha256Digest};
