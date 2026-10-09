use palaco_runtime::elixer::{
    self, ActivationStatus, AuthorizationStatus, CapabilityPolicyV01, ConsentV01,
    ElixerManifestV01, ExecutionStatus, FreshnessStatus, IdentityContext, PackageStatus, PersonaId,
    ResultKind, RevocationV01, RuntimeIntent, RuntimeRequestV01, Surface, bind_surface,
};
use std::error::Error;

const PACKAGE: &[u8] = b"synthetic HARA package v0.1";

fn fixture() -> Result<(String, CapabilityPolicyV01, RuntimeRequestV01), serde_json::Error> {
    let digest = elixer::sha256_hex(PACKAGE);
    let manifest = ElixerManifestV01 {
        schema: elixer::MANIFEST_SCHEMA_V01.to_owned(),
        elixer_id: "HARA-CANDIDATE".to_owned(),
        version: "0.1.0".to_owned(),
        package_digest: digest.clone(),
        tenant: "synthetic-tenant".to_owned(),
        world: "synthetic-world".to_owned(),
        citadel: "synthetic-citadel".to_owned(),
        policy_version: "policy-0.1".to_owned(),
        capabilities: vec!["read.synthetic".to_owned()],
        dependencies: Vec::new(),
        persona_adapters: vec![PersonaId::Haram, PersonaId::ChingChing, PersonaId::Hannie],
    };
    let policy = CapabilityPolicyV01 {
        schema: elixer::CAPABILITY_POLICY_SCHEMA_V01.to_owned(),
        policy_version: "policy-0.1".to_owned(),
        allowed_scopes: vec!["read.synthetic".to_owned()],
        max_data_age_seconds: 100,
    };
    let request = RuntimeRequestV01 {
        schema: elixer::REQUEST_SCHEMA_V01.to_owned(),
        who: IdentityContext {
            actor: "synthetic-actor".to_owned(),
            tenant: "synthetic-tenant".to_owned(),
            world: "synthetic-world".to_owned(),
            citadel: "synthetic-citadel".to_owned(),
            verified: true,
        },
        what: "synthetic household planning".to_owned(),
        why: "kernel MVP test".to_owned(),
        elixer_id: "HARA-CANDIDATE".to_owned(),
        version: "0.1.0".to_owned(),
        package_digest: digest,
        tenant: "synthetic-tenant".to_owned(),
        world: "synthetic-world".to_owned(),
        citadel: "synthetic-citadel".to_owned(),
        surface: Surface::Elixer,
        source_provenance: Some("fixture-source-001".to_owned()),
        policy_version: "policy-0.1".to_owned(),
        consent: Some(ConsentV01 {
            schema: elixer::CONSENT_SCHEMA_V01.to_owned(),
            reference: "synthetic-consent-001".to_owned(),
            granted: true,
            scopes: vec!["read.synthetic".to_owned()],
            expires_at: 2_000,
        }),
        scope: vec!["read.synthetic".to_owned()],
        authorization: None,
        expires_at: Some(1_500),
        revocation: Some(RevocationV01 {
            schema: elixer::REVOCATION_SCHEMA_V01.to_owned(),
            elixer_id: "HARA-CANDIDATE".to_owned(),
            version: "0.1.0".to_owned(),
            revoked: false,
            observed_at: 900,
        }),
        correlation_id: "synthetic-correlation-001".to_owned(),
        as_of: 1_000,
        data_observed_at: Some(990),
        intent: RuntimeIntent::Read,
    };
    Ok((serde_json::to_string(&manifest)?, policy, request))
}

fn evaluate_fixture() -> Result<
    (
        String,
        CapabilityPolicyV01,
        RuntimeRequestV01,
        palaco_runtime::elixer::RuntimeResultV01,
    ),
    Box<dyn Error>,
> {
    let (manifest, policy, request) = fixture()?;
    let result = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    Ok((manifest, policy, request, result))
}

#[test]
fn strict_manifest_contract_rejects_unknown_fields() -> Result<(), Box<dyn Error>> {
    let (manifest, _, _) = fixture()?;
    let with_extra_field = manifest.trim_end_matches('}').to_owned() + ",\"active\":true}";
    assert!(serde_json::from_str::<ElixerManifestV01>(&with_extra_field).is_err());
    Ok(())
}

#[test]
fn package_digest_is_reproducible_and_checked_before_personas() -> Result<(), Box<dyn Error>> {
    let (manifest, policy, request) = fixture()?;
    assert_eq!(elixer::sha256_hex(PACKAGE), request.package_digest);
    let result = elixer::evaluate(&manifest, b"tampered package", &request, &policy);
    assert_eq!(result.kind, ResultKind::Blocked);
    assert_eq!(result.status.package, PackageStatus::Blocked);
    assert!(result.personas.is_empty());
    Ok(())
}

#[test]
fn missing_provenance_is_unknown_and_never_verified() -> Result<(), Box<dyn Error>> {
    let (manifest, policy, mut request) = fixture()?;
    request.source_provenance = None;
    let result = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(result.kind, ResultKind::Explanation);
    assert_eq!(result.status.evidence, elixer::EvidenceStatus::Unknown);
    assert!(result.personas.is_empty());
    assert!(
        result
            .limitations
            .iter()
            .any(|item| item.contains("no verification claim"))
    );
    Ok(())
}

#[test]
fn expired_and_revoked_inputs_fail_closed() -> Result<(), Box<dyn Error>> {
    let (manifest, policy, mut request) = fixture()?;
    request.expires_at = Some(request.as_of);
    let expired = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(expired.kind, ResultKind::Expired);
    assert_eq!(expired.status.freshness, FreshnessStatus::Expired);

    request.expires_at = Some(1_500);
    if let Some(revocation) = &mut request.revocation {
        revocation.revoked = true;
    }
    let revoked = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(revoked.kind, ResultKind::Revoked);
    assert!(revoked.personas.is_empty());
    Ok(())
}

#[test]
fn stale_or_unknown_freshness_never_reaches_personas() -> Result<(), Box<dyn Error>> {
    let (manifest, policy, mut request) = fixture()?;
    request.data_observed_at = Some(800);
    let stale = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(stale.kind, ResultKind::Stale);
    assert_eq!(stale.status.freshness, FreshnessStatus::Stale);
    assert!(stale.personas.is_empty());

    request.data_observed_at = None;
    let unknown = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(unknown.kind, ResultKind::ReviewRequired);
    assert_eq!(unknown.status.freshness, FreshnessStatus::Unknown);
    Ok(())
}

#[test]
fn consent_and_scope_are_separate_from_execution_authorization() -> Result<(), Box<dyn Error>> {
    let (manifest, policy, mut request) = fixture()?;
    request.authorization = Some("unverified-authorization-reference".to_owned());
    request.intent = RuntimeIntent::Execute;
    let result = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(result.kind, ResultKind::ExecutionPendingAuthorization);
    assert_eq!(result.status.conformance, elixer::ConformanceStatus::NotRun);
    assert_eq!(result.status.activation, ActivationStatus::Inactive);
    assert_eq!(
        result.status.execution,
        ExecutionStatus::AuthorizationPending
    );
    assert_eq!(
        result.status.authorization,
        AuthorizationStatus::ReferenceProvidedUnverified
    );
    assert_eq!(result.personas.len(), 3);
    assert!(result.personas.iter().all(|item| !item.dissent.is_empty()));

    request.consent = None;
    let no_consent = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(no_consent.kind, ResultKind::Explanation);
    assert_eq!(
        no_consent.status.activation,
        ActivationStatus::ConsentRequired
    );
    assert!(no_consent.personas.is_empty());

    request.consent = fixture()?.2.consent;
    request.scope = vec!["agenda.mutate".to_owned()];
    let out_of_scope = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(out_of_scope.kind, ResultKind::Blocked);
    assert!(out_of_scope.personas.is_empty());
    Ok(())
}

#[test]
fn all_surfaces_bind_to_one_canonical_state() -> Result<(), Box<dyn Error>> {
    let (_, _, _, result) = evaluate_fixture()?;
    assert_eq!(result.kind, ResultKind::ReadResult);
    assert_eq!(result.personas.len(), 3);
    assert_eq!(result.personas[0].persona, PersonaId::Haram);
    assert_eq!(result.personas[1].persona, PersonaId::ChingChing);
    assert_eq!(result.personas[2].persona, PersonaId::Hannie);
    assert!(!result.personas[2].dissent.is_empty());
    let elixer = bind_surface(&result, Surface::Elixer);
    let widget = bind_surface(&result, Surface::Widget);
    let rio = bind_surface(&result, Surface::Rio);
    assert_eq!(
        elixer.canonical_receipt_digest,
        widget.canonical_receipt_digest
    );
    assert_eq!(
        widget.canonical_receipt_digest,
        rio.canonical_receipt_digest
    );
    Ok(())
}

#[test]
fn unresolved_identity_and_revocation_never_call_personas() -> Result<(), Box<dyn Error>> {
    let (manifest, policy, mut request) = fixture()?;
    request.who.verified = false;
    let unresolved = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(unresolved.kind, ResultKind::Blocked);
    assert!(unresolved.personas.is_empty());

    request.who.verified = true;
    request.revocation = None;
    let unknown_revocation = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_eq!(unknown_revocation.kind, ResultKind::ReviewRequired);
    assert!(unknown_revocation.personas.is_empty());
    Ok(())
}

#[test]
fn trace_receipt_is_stable_and_binds_persona_results() -> Result<(), Box<dyn Error>> {
    let (_, _, _, first) = evaluate_fixture()?;
    let (_, _, _, replay) = evaluate_fixture()?;
    assert_eq!(first.trace.receipt_digest, replay.trace.receipt_digest);

    let (manifest, policy, mut request) = fixture()?;
    request.what = "different synthetic request".to_owned();
    let changed = elixer::evaluate(&manifest, PACKAGE, &request, &policy);
    assert_ne!(first.trace.receipt_digest, changed.trace.receipt_digest);
    Ok(())
}
