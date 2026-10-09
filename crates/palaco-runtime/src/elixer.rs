#![forbid(unsafe_code)]

//! Synthetic, read-only ELIXER kernel contracts and deterministic runtime.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const MANIFEST_SCHEMA_V01: &str = "elixer-manifest-v0.1";
pub const REQUEST_SCHEMA_V01: &str = "elixer-runtime-request-v0.1";
pub const RESULT_SCHEMA_V01: &str = "elixer-runtime-result-v0.1";
pub const CAPABILITY_POLICY_SCHEMA_V01: &str = "elixer-capability-policy-v0.1";
pub const CONSENT_SCHEMA_V01: &str = "elixer-consent-v0.1";
pub const REVOCATION_SCHEMA_V01: &str = "elixer-revocation-v0.1";
pub const TRACE_RECEIPT_SCHEMA_V01: &str = "elixer-trace-receipt-v0.1";
pub const SURFACE_BINDING_SCHEMA_V01: &str = "elixer-surface-binding-v0.1";

const MVP_PERSONAS: [PersonaId; 3] = [
    PersonaId::Haram,
    PersonaId::ChingChing,
    PersonaId::Hannie,
];

/// Exact persona adapters supported by the synthetic H∆R∆ candidate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PersonaId {
    #[serde(rename = "H∆R∆M")]
    Haram,
    #[serde(rename = "CHING_CHING")]
    ChingChing,
    #[serde(rename = "HANNIE")]
    Hannie,
}

/// Strict, versioned package manifest. Unknown fields are rejected rather than defaulted.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ElixerManifestV01 {
    pub schema: String,
    pub elixer_id: String,
    pub version: String,
    pub package_digest: String,
    pub tenant: String,
    pub world: String,
    pub citadel: String,
    pub policy_version: String,
    pub capabilities: Vec<String>,
    pub dependencies: Vec<String>,
    pub persona_adapters: Vec<PersonaId>,
}

impl ElixerManifestV01 {
    fn validate(&self) -> Result<(), &'static str> {
        if self.schema != MANIFEST_SCHEMA_V01 {
            return Err("unsupported manifest schema");
        }
        if [
            &self.elixer_id,
            &self.version,
            &self.tenant,
            &self.world,
            &self.citadel,
            &self.policy_version,
        ]
        .iter()
        .any(|value| value.trim().is_empty())
        {
            return Err("manifest identity or context is missing");
        }
        if !is_sha256_digest(&self.package_digest) {
            return Err("manifest package digest is malformed");
        }
        if self.capabilities.is_empty()
            || self
                .capabilities
                .iter()
                .any(|capability| capability.trim().is_empty())
        {
            return Err("manifest capabilities are missing or empty");
        }
        if !self.dependencies.is_empty() {
            return Err("synthetic MVP does not resolve external dependencies");
        }
        if self.persona_adapters.len() != MVP_PERSONAS.len()
            || MVP_PERSONAS
                .iter()
                .any(|persona| !self.persona_adapters.contains(persona))
        {
            return Err("manifest must bind the three supported H∆R∆ adapters");
        }
        Ok(())
    }
}

/// Explicit execution intention; requesting execution never commits an external effect.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RuntimeIntent {
    Read,
    Explain,
    Propose,
    Execute,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Surface {
    Elixer,
    Widget,
    Rio,
    CitadelWorld,
}

/// Revocation must be supplied explicitly; unknown state blocks new work.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RevocationState {
    Active,
    Revoked,
    Unknown,
}

/// Read-consent contract, separate from execution authorization.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConsentV01 {
    pub schema: String,
    pub reference: String,
    pub granted: bool,
    pub scopes: Vec<String>,
    pub expires_at: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IdentityContext {
    pub actor: String,
    pub tenant: String,
    pub world: String,
    pub citadel: String,
    /// Synthetic fixture assertion only; this is not an identity verification mechanism.
    pub verified: bool,
}

/// Canonical request. Optional evidence remains explicitly absent, never silently inferred.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeRequestV01 {
    pub schema: String,
    pub who: IdentityContext,
    pub what: String,
    pub why: String,
    pub elixer_id: String,
    pub version: String,
    pub package_digest: String,
    pub tenant: String,
    pub world: String,
    pub citadel: String,
    pub surface: Surface,
    pub source_provenance: Option<String>,
    pub policy_version: String,
    pub consent: Option<ConsentV01>,
    pub scope: Vec<String>,
    pub authorization: Option<String>,
    pub expires_at: Option<i64>,
    pub revocation_state: RevocationState,
    pub correlation_id: String,
    pub as_of: i64,
    pub intent: RuntimeIntent,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ResultKind {
    ReadResult,
    Explanation,
    Proposal,
    ReviewRequired,
    Blocked,
    Stale,
    Expired,
    Revoked,
    OfflineReadOnly,
    ExecutionPendingAuthorization,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PackageStatus {
    Unresolved,
    Resolved,
    IntegrityVerified,
    Blocked,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConformanceStatus {
    NotRun,
    Pass,
    Fail,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ActivationStatus {
    Inactive,
    ConsentRequired,
    Active,
    Disabled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FreshnessStatus {
    Current,
    Stale,
    Expired,
    Superseded,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ExecutionStatus {
    NotRequested,
    AuthorizationPending,
    Denied,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EvidenceStatus {
    Unknown,
    ProvidedUnverified,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConsentStatus {
    Missing,
    Granted,
    Denied,
    Expired,
    OutOfScope,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AuthorizationStatus {
    Missing,
    ReferenceProvidedUnverified,
    NotRequested,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StatusAxes {
    pub package: PackageStatus,
    pub conformance: ConformanceStatus,
    pub activation: ActivationStatus,
    pub freshness: FreshnessStatus,
    pub execution: ExecutionStatus,
    pub evidence: EvidenceStatus,
    pub consent: ConsentStatus,
    pub authorization: AuthorizationStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PersonaOutput {
    pub persona: PersonaId,
    pub response: String,
    pub dissent: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TraceReceiptV01 {
    pub schema: String,
    pub correlation_id: String,
    pub events: Vec<String>,
    pub receipt_digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeResultV01 {
    pub schema: String,
    pub kind: ResultKind,
    pub elixer_id: Option<String>,
    pub version: Option<String>,
    pub package_digest: Option<String>,
    pub status: StatusAxes,
    pub allowed_scope: Vec<String>,
    pub limitations: Vec<String>,
    pub personas: Vec<PersonaOutput>,
    pub reason: String,
    pub trace: TraceReceiptV01,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityPolicyV01 {
    pub schema: String,
    pub policy_version: String,
    pub allowed_scopes: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RevocationV01 {
    pub schema: String,
    pub elixer_id: String,
    pub version: String,
    pub revoked: bool,
    pub observed_at: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SurfaceBindingV01 {
    pub schema: String,
    pub surface: Surface,
    pub canonical_receipt_digest: String,
}

/// Evaluates a synthetic candidate. No adapter performs IO or external mutation.
pub fn evaluate(
    manifest_json: &str,
    package_bytes: &[u8],
    request: &RuntimeRequestV01,
    policy: &CapabilityPolicyV01,
) -> RuntimeResultV01 {
    let mut events = vec!["request.received".to_owned(), "identity.context.checked".to_owned()];

    if request.schema != REQUEST_SCHEMA_V01
        || !request.who.verified
        || [
            request.who.actor.as_str(),
            request.who.tenant.as_str(),
            request.who.world.as_str(),
            request.who.citadel.as_str(),
            request.tenant.as_str(),
            request.world.as_str(),
            request.citadel.as_str(),
            request.correlation_id.as_str(),
        ]
        .iter()
        .any(|value| value.trim().is_empty())
    {
        events.push("identity.context.blocked".to_owned());
        return result(
            request,
            None,
            ResultKind::Blocked,
            status(PackageStatus::Unresolved, FreshnessStatus::Unknown),
            Vec::new(),
            Vec::new(),
            "identity or tenant/world/Citadel context is unresolved",
            events,
        );
    }

    let manifest = match serde_json::from_str::<ElixerManifestV01>(manifest_json) {
        Ok(manifest) => manifest,
        Err(_) => {
            events.push("manifest.rejected".to_owned());
            return result(
                request,
                None,
                ResultKind::Blocked,
                status(PackageStatus::Unresolved, FreshnessStatus::Unknown),
                Vec::new(),
                Vec::new(),
                "manifest is not valid elixer-manifest-v0.1",
                events,
            );
        }
    };
    if manifest.validate().is_err() {
        events.push("manifest.rejected".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Blocked,
            status(PackageStatus::Blocked, FreshnessStatus::Unknown),
            Vec::new(),
            Vec::new(),
            "manifest contract validation failed",
            events,
        );
    }
    events.push("manifest.version.resolved".to_owned());

    if request.elixer_id != manifest.elixer_id
        || request.version != manifest.version
        || request.package_digest != manifest.package_digest
        || request.tenant != manifest.tenant
        || request.world != manifest.world
        || request.citadel != manifest.citadel
        || request.who.tenant != request.tenant
        || request.who.world != request.world
        || request.who.citadel != request.citadel
        || request.policy_version != manifest.policy_version
    {
        events.push("context.manifest.binding.blocked".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Blocked,
            status(PackageStatus::Resolved, FreshnessStatus::Unknown),
            Vec::new(),
            Vec::new(),
            "request context, version, or policy does not match the manifest",
            events,
        );
    }

    if sha256_hex(package_bytes) != manifest.package_digest {
        events.push("package.integrity.failed".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Blocked,
            status(PackageStatus::Blocked, FreshnessStatus::Unknown),
            Vec::new(),
            Vec::new(),
            "package digest mismatch; persona adapters were not called",
            events,
        );
    }
    events.push("package.integrity.verified".to_owned());

    let mut axes = status(
        PackageStatus::IntegrityVerified,
        FreshnessStatus::Current,
    );
    axes.evidence = if request
        .source_provenance
        .as_ref()
        .is_some_and(|source| !source.trim().is_empty())
    {
        EvidenceStatus::ProvidedUnverified
    } else {
        EvidenceStatus::Unknown
    };
    if axes.evidence == EvidenceStatus::Unknown {
        events.push("provenance.unknown".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Explanation,
            axes,
            Vec::new(),
            vec!["provenance is unavailable; no verification claim is made".to_owned()],
            "source provenance is missing",
            events,
        );
    }
    events.push("provenance.reference.present.unverified".to_owned());

    if policy.schema != CAPABILITY_POLICY_SCHEMA_V01
        || policy.policy_version != manifest.policy_version
    {
        events.push("policy.unresolved".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::ReviewRequired,
            axes,
            Vec::new(),
            Vec::new(),
            "capability policy is missing, stale, or mismatched",
            events,
        );
    }

    match request.revocation_state {
        RevocationState::Revoked => {
            axes.activation = ActivationStatus::Disabled;
            events.push("revocation.confirmed".to_owned());
            return result(
                request,
                Some(&manifest),
                ResultKind::Revoked,
                axes,
                Vec::new(),
                vec!["historical trace is retained; new actions are blocked".to_owned()],
                "ELIXER version is revoked",
                events,
            );
        }
        RevocationState::Unknown => {
            events.push("revocation.unknown".to_owned());
            return result(
                request,
                Some(&manifest),
                ResultKind::ReviewRequired,
                axes,
                Vec::new(),
                Vec::new(),
                "revocation state cannot be established",
                events,
            );
        }
        RevocationState::Active => {}
    }

    let Some(request_expiry) = request.expires_at else {
        axes.freshness = FreshnessStatus::Unknown;
        events.push("freshness.unknown".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::ReviewRequired,
            axes,
            Vec::new(),
            Vec::new(),
            "request expiry is missing",
            events,
        );
    };
    if request.as_of >= request_expiry {
        axes.freshness = FreshnessStatus::Expired;
        axes.activation = ActivationStatus::Disabled;
        events.push("request.expired".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Expired,
            axes,
            Vec::new(),
            Vec::new(),
            "request has expired",
            events,
        );
    }

    let Some(consent) = &request.consent else {
        axes.consent = ConsentStatus::Missing;
        axes.activation = ActivationStatus::ConsentRequired;
        events.push("consent.missing".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Explanation,
            axes,
            Vec::new(),
            vec!["only non-sensitive public/read-only context is allowed".to_owned()],
            "read consent is missing",
            events,
        );
    };
    if consent.schema != CONSENT_SCHEMA_V01
        || consent.reference.trim().is_empty()
        || !consent.granted
    {
        axes.consent = ConsentStatus::Denied;
        axes.activation = ActivationStatus::ConsentRequired;
        events.push("consent.denied".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Blocked,
            axes,
            Vec::new(),
            Vec::new(),
            "consent is invalid or not granted",
            events,
        );
    }
    if request.as_of >= consent.expires_at {
        axes.consent = ConsentStatus::Expired;
        axes.freshness = FreshnessStatus::Expired;
        axes.activation = ActivationStatus::Disabled;
        events.push("consent.expired".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Expired,
            axes,
            Vec::new(),
            Vec::new(),
            "read consent has expired",
            events,
        );
    }
    if request.scope.is_empty()
        || request.scope.iter().any(|scope| {
            !manifest.capabilities.contains(scope)
                || !policy.allowed_scopes.contains(scope)
                || !consent.scopes.contains(scope)
        })
    {
        axes.consent = ConsentStatus::OutOfScope;
        axes.activation = ActivationStatus::ConsentRequired;
        events.push("scope.denied".to_owned());
        return result(
            request,
            Some(&manifest),
            ResultKind::Blocked,
            axes,
            Vec::new(),
            Vec::new(),
            "requested scope exceeds capability policy or consent",
            events,
        );
    }

    axes.consent = ConsentStatus::Granted;
    axes.activation = ActivationStatus::Active;
    axes.conformance = ConformanceStatus::Pass;
    axes.authorization = if request.authorization.is_some() {
        AuthorizationStatus::ReferenceProvidedUnverified
    } else {
        AuthorizationStatus::Missing
    };
    events.push("policy.consent.scope.allowed".to_owned());
    events.push("persona.adapters.invoked".to_owned());
    let personas = MVP_PERSONAS
        .iter()
        .copied()
        .map(|persona| persona_output(persona, request))
        .collect();

    let kind = match request.intent {
        RuntimeIntent::Read => ResultKind::ReadResult,
        RuntimeIntent::Explain => ResultKind::Explanation,
        RuntimeIntent::Propose => ResultKind::Proposal,
        RuntimeIntent::Execute => {
            axes.execution = ExecutionStatus::AuthorizationPending;
            events.push("authorization.gate.pending".to_owned());
            ResultKind::ExecutionPendingAuthorization
        }
    };
    result(
        request,
        Some(&manifest),
        kind,
        axes,
        request.scope.clone(),
        vec![
            "synthetic adapters only; no production data or external side effects".to_owned(),
            "provenance reference is present but not cryptographically verified".to_owned(),
        ],
        if request.intent == RuntimeIntent::Execute {
            "execution is pending a separate authorization gate; no commit is performed"
        } else {
            "synthetic H∆R∆ candidate result"
        },
        events,
    )
}

/// A surface binding references the same canonical receipt; it carries no independent state.
#[must_use]
pub fn bind_surface(result: &RuntimeResultV01, surface: Surface) -> SurfaceBindingV01 {
    SurfaceBindingV01 {
        schema: SURFACE_BINDING_SCHEMA_V01.to_owned(),
        surface,
        canonical_receipt_digest: result.trace.receipt_digest.clone(),
    }
}

/// Reproducible SHA-256 digest in the manifest wire format.
#[must_use]
pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut encoded = String::with_capacity(71);
    encoded.push_str("sha256:");
    for byte in digest {
        use std::fmt::Write;
        let _ = write!(encoded, "{byte:02x}");
    }
    encoded
}

fn is_sha256_digest(value: &str) -> bool {
    value
        .strip_prefix("sha256:")
        .is_some_and(|hex| hex.len() == 64 && hex.bytes().all(|byte| byte.is_ascii_hexdigit()))
}

fn status(package: PackageStatus, freshness: FreshnessStatus) -> StatusAxes {
    StatusAxes {
        package,
        conformance: ConformanceStatus::NotRun,
        activation: ActivationStatus::Inactive,
        freshness,
        execution: ExecutionStatus::NotRequested,
        evidence: EvidenceStatus::Unknown,
        consent: ConsentStatus::Missing,
        authorization: AuthorizationStatus::NotRequested,
    }
}

fn persona_output(persona: PersonaId, request: &RuntimeRequestV01) -> PersonaOutput {
    let response = match persona {
        PersonaId::Haram => format!("Coordinate and explain the synthetic request: {}", request.what),
        PersonaId::ChingChing => {
            format!("Offer consent-first synthetic advice about: {}", request.what)
        }
        PersonaId::Hannie => {
            format!("Use synthetic household context for: {}; do not mutate an agenda", request.what)
        }
    };
    let dissent = if request.intent == RuntimeIntent::Execute {
        vec!["No persona output authorizes or commits external execution".to_owned()]
    } else {
        Vec::new()
    };
    PersonaOutput {
        persona,
        response,
        dissent,
    }
}

#[allow(clippy::too_many_arguments)]
fn result(
    request: &RuntimeRequestV01,
    manifest: Option<&ElixerManifestV01>,
    kind: ResultKind,
    status: StatusAxes,
    allowed_scope: Vec<String>,
    limitations: Vec<String>,
    reason: &str,
    mut events: Vec<String>,
) -> RuntimeResultV01 {
    events.push(format!("result.{kind:?}"));
    let receipt_digest = trace_digest(
        &request.correlation_id,
        manifest.map_or("", |item| item.elixer_id.as_str()),
        manifest.map_or("", |item| item.version.as_str()),
        kind,
        &events,
    );
    RuntimeResultV01 {
        schema: RESULT_SCHEMA_V01.to_owned(),
        kind,
        elixer_id: manifest.map(|item| item.elixer_id.clone()),
        version: manifest.map(|item| item.version.clone()),
        package_digest: manifest.map(|item| item.package_digest.clone()),
        status,
        allowed_scope,
        limitations,
        personas: Vec::new(),
        reason: reason.to_owned(),
        trace: TraceReceiptV01 {
            schema: TRACE_RECEIPT_SCHEMA_V01.to_owned(),
            correlation_id: request.correlation_id.clone(),
            events,
            receipt_digest,
        },
    }
}

fn trace_digest(
    correlation_id: &str,
    elixer_id: &str,
    version: &str,
    kind: ResultKind,
    events: &[String],
) -> String {
    let mut bytes = Vec::new();
    for field in [correlation_id, elixer_id, version, &format!("{kind:?}")] {
        bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        bytes.extend_from_slice(field.as_bytes());
    }
    for event in events {
        bytes.extend_from_slice(&(event.len() as u64).to_be_bytes());
        bytes.extend_from_slice(event.as_bytes());
    }
    sha256_hex(&bytes)
}
