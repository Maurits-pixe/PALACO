use palaco_la::identity_issuance::{
    AccountStatus, EvidenceReferenceV01, IIP_REQUEST_SCHEMA_V01, IipRequestV01,
    IssuanceReviewState, ReviewState, evaluate_reference,
};
#[cfg(debug_assertions)]
use palaco_la::identity_issuance::{
    DevelopmentBootstrapPurpose, DevelopmentBootstrapRequestV01, DevelopmentStartupDecision,
    EvidenceAuthenticationState, evaluate_development_bootstrap,
};

fn evidence(reference: &str) -> EvidenceReferenceV01 {
    EvidenceReferenceV01 {
        reference: reference.to_owned(),
        version: "v1".to_owned(),
    }
}

fn valid_request() -> IipRequestV01 {
    let source_state = r#"{"dossier":"synthetic-dossier","review":"source"}"#;
    let digest = sha2::Sha256::digest(source_state.as_bytes());
    let source_state_digest = digest.iter().map(|byte| format!("{byte:02x}")).collect();

    IipRequestV01 {
        schema: IIP_REQUEST_SCHEMA_V01.to_owned(),
        evaluated_at: 1_000,
        account_status: AccountStatus::Active,
        account_blocked: false,
        account_revoked: false,
        dossier_ref: "synthetic-dossier".to_owned(),
        dossier_provisional: true,
        subject_ref: "synthetic-subject".to_owned(),
        requested_scope: "identity:synthetic".to_owned(),
        subject_evidence: evidence("subject-evidence"),
        subject_confirmed: true,
        mailbox_control_only: false,
        owner_evidence: evidence("owner-evidence"),
        owner_dossier_ref: "synthetic-dossier".to_owned(),
        owner_subject_ref: "synthetic-subject".to_owned(),
        owner_confirmed: true,
        consent_evidence: evidence("consent-evidence"),
        consent_dossier_ref: "synthetic-dossier".to_owned(),
        consent_subject_ref: "synthetic-subject".to_owned(),
        consent_scope: "identity:synthetic".to_owned(),
        consent_granted: true,
        consent_expires_at: 2_000,
        consent_revoked: false,
        provenance_evidence: evidence("provenance-evidence"),
        source_state_ref: "source-state-1".to_owned(),
        source_state: source_state.to_owned(),
        source_state_digest,
        provenance_anchor_ref: "anchor-reference-1".to_owned(),
        provenance_anchor_verified: true,
        provenance_history_refs: vec!["history-1".to_owned()],
        issuance_request: evidence("issuance-request"),
        issuance_basis_ref: "basis-1".to_owned(),
        issuance_scope: "identity:synthetic".to_owned(),
        issuer_ref: "synthetic-issuer".to_owned(),
        issuer_evidence: evidence("issuer-evidence"),
        issuer_authorized: true,
        issuer_basis_ref: "basis-1".to_owned(),
        issuer_scopes: vec!["identity:synthetic".to_owned()],
        issuer_expires_at: 2_000,
        issuer_revoked: false,
    }
}

#[test]
fn complete_reference_review_never_creates_an_identity_or_authority() {
    let result = evaluate_reference(&valid_request());

    assert_eq!(result.account_review, ReviewState::Pass);
    assert_eq!(result.dossier_review, ReviewState::Pass);
    assert_eq!(result.subject_review, ReviewState::Pass);
    assert_eq!(result.owner_review, ReviewState::Pass);
    assert_eq!(result.consent_review, ReviewState::Pass);
    assert_eq!(result.provenance_review, ReviewState::Pass);
    assert!(result.identity_validated);
    assert_eq!(
        result.issuance_review,
        IssuanceReviewState::SyntheticApprovalOnly
    );
    assert!(!result.identity_issued);
    assert!(!result.identity_manifest_created);
    assert!(!result.identity_seal_created);
    assert!(!result.authority_granted);
}

#[test]
fn mailbox_control_alone_does_not_confirm_subject() {
    let mut request = valid_request();
    request.mailbox_control_only = true;

    let result = evaluate_reference(&request);

    assert_eq!(result.subject_review, ReviewState::Fail);
    assert!(!result.identity_validated);
    assert_eq!(result.issuance_review, IssuanceReviewState::NotReached);
}

#[test]
fn historic_or_revoked_consent_fails_closed() {
    let mut expired = valid_request();
    expired.consent_expires_at = expired.evaluated_at;
    assert_eq!(
        evaluate_reference(&expired).consent_review,
        ReviewState::Fail
    );

    let mut revoked = valid_request();
    revoked.consent_revoked = true;
    assert_eq!(
        evaluate_reference(&revoked).consent_review,
        ReviewState::Fail
    );
}

#[test]
fn provenance_requires_anchored_identifiable_source_history_and_matching_digest() {
    let mut unanchored = valid_request();
    unanchored.provenance_anchor_verified = false;
    assert_eq!(
        evaluate_reference(&unanchored).provenance_review,
        ReviewState::Fail
    );

    let mut no_history = valid_request();
    no_history.provenance_history_refs.clear();
    assert_eq!(
        evaluate_reference(&no_history).provenance_review,
        ReviewState::Fail
    );

    let mut mismatched_digest = valid_request();
    mismatched_digest.source_state_digest = "0".repeat(64);
    assert_eq!(
        evaluate_reference(&mismatched_digest).provenance_review,
        ReviewState::Fail
    );
}

#[test]
fn account_and_ownership_are_independent_gates() {
    let mut blocked = valid_request();
    blocked.account_blocked = true;
    let blocked_result = evaluate_reference(&blocked);
    assert_eq!(blocked_result.account_review, ReviewState::Fail);
    assert!(!blocked_result.identity_validated);

    let mut inactive = valid_request();
    inactive.account_status = AccountStatus::Inactive;
    assert_eq!(
        evaluate_reference(&inactive).account_review,
        ReviewState::Fail
    );

    let mut non_provisional = valid_request();
    non_provisional.dossier_provisional = false;
    assert_eq!(
        evaluate_reference(&non_provisional).dossier_review,
        ReviewState::Fail
    );

    let mut wrong_owner = valid_request();
    wrong_owner.owner_dossier_ref = "another-dossier".to_owned();
    let result = evaluate_reference(&wrong_owner);
    assert_eq!(result.owner_review, ReviewState::Fail);
    assert!(!result.identity_validated);
}

#[test]
fn issuer_scope_basis_expiry_and_revocation_are_required_for_reference_approval() {
    let mut wrong_basis = valid_request();
    wrong_basis.issuer_basis_ref = "different-basis".to_owned();
    assert_eq!(
        evaluate_reference(&wrong_basis).issuance_review,
        IssuanceReviewState::Denied
    );

    let mut expired_issuer = valid_request();
    expired_issuer.issuer_expires_at = expired_issuer.evaluated_at;
    assert_eq!(
        evaluate_reference(&expired_issuer).issuance_review,
        IssuanceReviewState::Denied
    );

    let mut revoked_issuer = valid_request();
    revoked_issuer.issuer_revoked = true;
    assert_eq!(
        evaluate_reference(&revoked_issuer).issuance_review,
        IssuanceReviewState::Denied
    );
}

#[test]
fn strict_request_contract_rejects_unknown_fields() {
    let serialized = serde_json::to_string(&valid_request()).expect("serialize fixture");
    let with_unknown = serialized.trim_end_matches('}').to_owned() + ",\"account_activated\":true}";

    assert!(serde_json::from_str::<IipRequestV01>(&with_unknown).is_err());
}

#[cfg(debug_assertions)]
#[test]
fn development_startup_override_is_opt_in_and_never_authenticates_or_issues() {
    let blocked = evaluate_development_bootstrap(DevelopmentBootstrapRequestV01 {
        purpose: DevelopmentBootstrapPurpose::RioMessageServiceTest,
        allow_unverified_fivecriptie_evidence: false,
    });
    assert_eq!(blocked.decision, DevelopmentStartupDecision::Blocked);

    let continued = evaluate_development_bootstrap(DevelopmentBootstrapRequestV01 {
        purpose: DevelopmentBootstrapPurpose::RioMessageServiceTest,
        allow_unverified_fivecriptie_evidence: true,
    });
    assert_eq!(
        continued.decision,
        DevelopmentStartupDecision::ContinueRestricted
    );
    assert!(continued.rio_message_service_test_enabled);
    assert!(!continued.external_message_delivery_enabled);
    assert_eq!(
        continued.fivecriptie_evidence,
        EvidenceAuthenticationState::Unverified
    );
    assert!(!continued.identity_issuance_enabled);
    assert!(!continued.authority_enabled);
}

use sha2::Digest;
