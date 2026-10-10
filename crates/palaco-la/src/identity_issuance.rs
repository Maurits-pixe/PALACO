use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const IIP_REQUEST_SCHEMA_V01: &str = "iip-1-reference-request-v0.1";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AccountStatus {
    Active,
    Inactive,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceReferenceV01 {
    pub reference: String,
    pub version: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IipRequestV01 {
    pub schema: String,
    pub evaluated_at: i64,
    pub account_status: AccountStatus,
    pub account_blocked: bool,
    pub account_revoked: bool,
    pub dossier_ref: String,
    pub dossier_provisional: bool,
    pub subject_ref: String,
    pub requested_scope: String,
    pub subject_evidence: EvidenceReferenceV01,
    pub subject_confirmed: bool,
    pub mailbox_control_only: bool,
    pub owner_evidence: EvidenceReferenceV01,
    pub owner_dossier_ref: String,
    pub owner_subject_ref: String,
    pub owner_confirmed: bool,
    pub consent_evidence: EvidenceReferenceV01,
    pub consent_dossier_ref: String,
    pub consent_subject_ref: String,
    pub consent_scope: String,
    pub consent_granted: bool,
    pub consent_expires_at: i64,
    pub consent_revoked: bool,
    pub provenance_evidence: EvidenceReferenceV01,
    pub source_state_ref: String,
    pub source_state: String,
    pub source_state_digest: String,
    pub provenance_anchor_ref: String,
    pub provenance_anchor_verified: bool,
    pub provenance_history_refs: Vec<String>,
    pub issuance_request: EvidenceReferenceV01,
    pub issuance_basis_ref: String,
    pub issuance_scope: String,
    pub issuer_ref: String,
    pub issuer_evidence: EvidenceReferenceV01,
    pub issuer_authorized: bool,
    pub issuer_basis_ref: String,
    pub issuer_scopes: Vec<String>,
    pub issuer_expires_at: i64,
    pub issuer_revoked: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReviewState {
    Pass,
    Fail,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum IssuanceReviewState {
    NotReached,
    Denied,
    SyntheticApprovalOnly,
}

#[cfg(debug_assertions)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DevelopmentStartupDecision {
    Blocked,
    ContinueRestricted,
}

#[cfg(debug_assertions)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceAuthenticationState {
    Unverified,
}

#[cfg(debug_assertions)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DevelopmentBootstrapRequestV01 {
    pub allow_unverified_fivecriptie_evidence: bool,
}

#[cfg(debug_assertions)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DevelopmentBootstrapResultV01 {
    pub decision: DevelopmentStartupDecision,
    pub fivecriptie_evidence: EvidenceAuthenticationState,
    pub identity_issuance_enabled: bool,
    pub authority_enabled: bool,
}

/// Allows a caller to continue development startup without accepting evidence as verified.
///
/// This API is absent from optimized release builds and does not affect IIP evaluation.
#[cfg(debug_assertions)]
#[must_use]
pub fn evaluate_development_bootstrap(
    request: DevelopmentBootstrapRequestV01,
) -> DevelopmentBootstrapResultV01 {
    DevelopmentBootstrapResultV01 {
        decision: if request.allow_unverified_fivecriptie_evidence {
            DevelopmentStartupDecision::ContinueRestricted
        } else {
            DevelopmentStartupDecision::Blocked
        },
        fivecriptie_evidence: EvidenceAuthenticationState::Unverified,
        identity_issuance_enabled: false,
        authority_enabled: false,
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IipReferenceResultV01 {
    pub schema: String,
    pub account_review: ReviewState,
    pub dossier_review: ReviewState,
    pub subject_review: ReviewState,
    pub owner_review: ReviewState,
    pub consent_review: ReviewState,
    pub provenance_review: ReviewState,
    pub identity_validated: bool,
    pub issuance_review: IssuanceReviewState,
    pub identity_issued: bool,
    pub identity_manifest_created: bool,
    pub identity_seal_created: bool,
    pub authority_granted: bool,
}

/// Evaluates synthetic IIP-1 assertions. It cannot create an identity or confer authority.
#[must_use]
pub fn evaluate_reference(request: &IipRequestV01) -> IipReferenceResultV01 {
    let account_review = if request.account_status == AccountStatus::Active
        && !request.account_blocked
        && !request.account_revoked
    {
        ReviewState::Pass
    } else {
        ReviewState::Fail
    };
    let dossier_review = if request.dossier_provisional && valid_identifier(&request.dossier_ref) {
        ReviewState::Pass
    } else {
        ReviewState::Fail
    };
    let subject_review = if request.subject_confirmed
        && !request.mailbox_control_only
        && valid_reference(&request.subject_evidence)
        && valid_identifier(&request.subject_ref)
    {
        ReviewState::Pass
    } else {
        ReviewState::Fail
    };

    let owner_review = if request.owner_confirmed
        && valid_reference(&request.owner_evidence)
        && request.owner_dossier_ref == request.dossier_ref
        && request.owner_subject_ref == request.subject_ref
    {
        ReviewState::Pass
    } else {
        ReviewState::Fail
    };

    let consent_review = if request.consent_granted
        && !request.consent_revoked
        && valid_reference(&request.consent_evidence)
        && request.consent_dossier_ref == request.dossier_ref
        && request.consent_subject_ref == request.subject_ref
        && request.consent_scope == request.requested_scope
        && valid_identifier(&request.requested_scope)
        && request.consent_expires_at > request.evaluated_at
    {
        ReviewState::Pass
    } else {
        ReviewState::Fail
    };

    let provenance_review = if valid_reference(&request.provenance_evidence)
        && valid_identifier(&request.source_state_ref)
        && valid_identifier(&request.source_state)
        && valid_identifier(&request.provenance_anchor_ref)
        && request.provenance_anchor_verified
        && !request.provenance_history_refs.is_empty()
        && request
            .provenance_history_refs
            .iter()
            .all(|reference| valid_identifier(reference))
        && request.source_state_digest == sha256_hex(request.source_state.as_bytes())
    {
        ReviewState::Pass
    } else {
        ReviewState::Fail
    };

    let identity_validated = request.schema == IIP_REQUEST_SCHEMA_V01
        && account_review == ReviewState::Pass
        && dossier_review == ReviewState::Pass
        && subject_review == ReviewState::Pass
        && owner_review == ReviewState::Pass
        && consent_review == ReviewState::Pass
        && provenance_review == ReviewState::Pass;

    let issuance_review = if !identity_validated {
        IssuanceReviewState::NotReached
    } else if valid_reference(&request.issuance_request)
        && valid_reference(&request.issuer_evidence)
        && valid_identifier(&request.issuer_ref)
        && valid_identifier(&request.issuance_basis_ref)
        && request.issuer_basis_ref == request.issuance_basis_ref
        && request.issuance_scope == request.requested_scope
        && request.issuer_scopes.contains(&request.issuance_scope)
        && request.issuer_authorized
        && !request.issuer_revoked
        && request.issuer_expires_at > request.evaluated_at
    {
        IssuanceReviewState::SyntheticApprovalOnly
    } else {
        IssuanceReviewState::Denied
    };

    IipReferenceResultV01 {
        schema: "iip-1-reference-result-v0.1".to_owned(),
        account_review,
        dossier_review,
        subject_review,
        owner_review,
        consent_review,
        provenance_review,
        identity_validated,
        issuance_review,
        identity_issued: false,
        identity_manifest_created: false,
        identity_seal_created: false,
        authority_granted: false,
    }
}

fn valid_reference(reference: &EvidenceReferenceV01) -> bool {
    valid_identifier(&reference.reference) && valid_identifier(&reference.version)
}

fn valid_identifier(value: &str) -> bool {
    !value.trim().is_empty() && value.trim() == value
}

fn sha256_hex(value: &[u8]) -> String {
    let digest = Sha256::digest(value);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}
