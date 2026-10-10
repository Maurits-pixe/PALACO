//! Synthetic, reference-only 6RI9ADE evidence gate.
//!
//! This module can verify signed evidence against a host-supplied trust snapshot.
//! It cannot authenticate that snapshot, open contact, grant authority, or cause
//! external effects. Production use requires an independently trusted snapshot
//! provider and separately reviewed identity, delivery, revocation, and consent
//! services.

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use chrono::DateTime;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

pub const REQUEST_SCHEMA_V01: &str = "elixer-6ri9ade-request-v0.1";
pub const SNAPSHOT_SCHEMA_V01: &str = "elixer-6ri9ade-trust-snapshot-v0.1";
pub const EVIDENCE_SCHEMA_V01: &str = "elixer-6ri9ade-evidence-v0.1";
pub const RECEIPT_SCHEMA_V01: &str = "elixer-6ri9ade-human-receipt-v0.1";
pub const SIGNED_SNAPSHOT_SCHEMA_V01: &str = "elixer-6ri9ade-signed-snapshot-v0.1";
const MAX_REQUEST_AGE_MS: i64 = 15 * 60 * 1_000;
const MAX_EVIDENCE_AGE_MS: i64 = 2 * 60 * 1_000;
const MAX_RECEIPT_AGE_MS: i64 = 15 * 60 * 1_000;
const MAX_SNAPSHOT_AGE_MS: i64 = 30 * 1_000;
const MAX_CANONICAL_BODY_BYTES: usize = 16 * 1_024;
const MAX_SNAPSHOT_ISSUERS: usize = 64;
const MAX_REVOKED_IDS: usize = 512;
const REFERENCE_DOMAIN: &[u8] = b"PALACO/6RI9ADE/REFERENCE-EVIDENCE/v0.1\0";
const SNAPSHOT_DOMAIN: &[u8] = b"PALACO/6RI9ADE/TRUST-SNAPSHOT/v0.1\0";

/// The nine independent controls required for each participant.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Specialty {
    Identity,
    Address,
    HumanConsent,
    ScopePolicy,
    E2eeKeys,
    ContentIntegrity,
    ReplayOrder,
    Privacy,
    DeliveryRevocation,
}

impl Specialty {
    pub const ALL: [Self; 9] = [
        Self::Identity,
        Self::Address,
        Self::HumanConsent,
        Self::ScopePolicy,
        Self::E2eeKeys,
        Self::ContentIntegrity,
        Self::ReplayOrder,
        Self::Privacy,
        Self::DeliveryRevocation,
    ];
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Side {
    Sender,
    Receiver,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceResult {
    Pass,
    Fail,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReceiptStage {
    Initiation,
    NovaAdmission,
    FinalConsent,
}

/// A synthetic request binds the check to both parties and a narrowly scoped
/// text-message intent. Only a context digest is accepted, never message
/// content. Timestamps use RFC 3339.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct RequestV01 {
    pub schema: String,
    pub request_id: String,
    pub sender_id: String,
    pub receiver_id: String,
    pub scope: String,
    pub context_digest: String,
    pub created_at: String,
    pub expires_at: String,
}

/// A signed envelope carries the canonical JSON body and an unpadded base64url
/// Ed25519 signature over its domain-separated canonical representation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SignedEnvelopeV01 {
    pub algorithm: String,
    pub body: Value,
    pub signature: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct EvidenceBodyV01 {
    pub schema: String,
    pub issuer_id: String,
    pub key_id: String,
    pub evidence_id: String,
    pub request_digest: String,
    pub context_digest: String,
    pub side: Side,
    pub specialty: Specialty,
    pub result: EvidenceResult,
    pub issued_at: String,
    pub expires_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct HumanReceiptBodyV01 {
    pub schema: String,
    pub issuer_id: String,
    pub key_id: String,
    pub receipt_id: String,
    pub request_digest: String,
    pub stage: ReceiptStage,
    pub participant_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub initiation_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub admission_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence_set_digest: Option<String>,
    pub issued_at: String,
    pub expires_at: String,
}

/// A trust snapshot is supplied by the host, never by the request or an
/// evidence signer. The evaluator can check its shape and freshness, not its
/// authenticity; production callers must obtain it from a trusted provider.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct TrustSnapshotV01 {
    pub schema: String,
    pub revision: String,
    pub request_digest: String,
    pub captured_at: String,
    pub expires_at: String,
    pub status: SnapshotStatus,
    pub issuers: Vec<TrustedIssuerV01>,
    pub revoked_evidence_ids: Vec<String>,
    pub revoked_issuer_ids: Vec<String>,
}

/// A provider-signed snapshot. Its signature authenticates the bytes only when
/// the configured anchor is itself provisioned through a trusted host channel.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SignedTrustSnapshotV01 {
    pub schema: String,
    pub provider_id: String,
    pub key_id: String,
    pub snapshot: TrustSnapshotV01,
    pub signature: String,
}

/// Host-configured trust anchor. The evaluator cannot establish how the host
/// obtained or protected this key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SnapshotTrustAnchorV01 {
    pub provider_id: String,
    pub key_id: String,
    pub public_key: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotProviderError {
    Unavailable,
    Invalid,
}

/// Host-owned synchronous snapshot and clock source. Implementations must read
/// the authoritative source on every call; this trait is an integration
/// boundary, not a trusted implementation or production provider.
pub trait TrustSnapshotProvider {
    fn current_time(&self) -> Result<String, SnapshotProviderError>;
    fn load_snapshot(
        &self,
        request_digest: &str,
    ) -> Result<SignedTrustSnapshotV01, SnapshotProviderError>;
}

#[derive(Debug, Clone, Copy)]
pub struct GateEvidenceInputV01<'a> {
    pub request: &'a RequestV01,
    pub initiation: &'a SignedEnvelopeV01,
    pub nova_admission: &'a SignedEnvelopeV01,
    pub evidence: &'a [SignedEnvelopeV01],
    pub final_receipts: &'a [SignedEnvelopeV01],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SnapshotStatus {
    Current,
    Hold,
    Stop,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct TrustedIssuerV01 {
    pub issuer_id: String,
    pub participant_id: String,
    pub side: Side,
    pub specialty: Option<Specialty>,
    pub receipt_stages: Vec<ReceiptStage>,
    pub key_id: String,
    pub public_key: String,
    pub valid_from: String,
    pub valid_until: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum GateStatus {
    Hold,
    Stop,
    PendingEvidence,
    PendingFinalConsent,
    ReferencePassed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CheckStatus {
    Pass,
    Hold,
    Stop,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SpecialtyCheck {
    pub side: Side,
    pub specialty: Specialty,
    pub status: CheckStatus,
    pub evidence_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct GateResultV01 {
    pub schema: String,
    pub mode: String,
    pub classification: String,
    pub status: GateStatus,
    pub request_digest: String,
    pub specialty_checks: Vec<SpecialtyCheck>,
    pub reason_codes: Vec<String>,
    pub initiation_accepted: bool,
    pub nova_admission_accepted: bool,
    pub final_sender_consent: bool,
    pub final_receiver_consent: bool,
    pub can_open_contact: bool,
    pub operative_authority: String,
    pub runtime_connected: bool,
    pub external_side_effect: bool,
    pub trace_digest: String,
}

/// Inputs for one deterministic reference-gate evaluation.
#[derive(Debug, Clone, Copy)]
pub struct GateInputV01<'a> {
    pub request: &'a RequestV01,
    pub initiation: &'a SignedEnvelopeV01,
    pub nova_admission: &'a SignedEnvelopeV01,
    pub evidence: &'a [SignedEnvelopeV01],
    pub final_receipts: &'a [SignedEnvelopeV01],
    pub initial_snapshot: &'a TrustSnapshotV01,
    pub final_snapshot: &'a TrustSnapshotV01,
}

/// Strict JSON input accepted by the standalone reference evaluator.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct GateBundleV01 {
    pub schema: String,
    pub request: RequestV01,
    pub initiation: SignedEnvelopeV01,
    pub nova_admission: SignedEnvelopeV01,
    pub evidence: Vec<SignedEnvelopeV01>,
    pub final_receipts: Vec<SignedEnvelopeV01>,
    pub initial_snapshot: TrustSnapshotV01,
    pub final_snapshot: TrustSnapshotV01,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct Slot {
    side: Side,
    specialty: Specialty,
}

/// Evaluates a reference-only gate against two independently loaded host
/// snapshots and a host-supplied current time. Both snapshots must be identical
/// and fresh; callers are responsible for supplying trusted clock and snapshot
/// reads. No execution or contact side effect is possible through this API.
#[must_use]
pub fn evaluate(input: GateInputV01<'_>, now: &str) -> GateResultV01 {
    let GateInputV01 {
        request,
        initiation,
        nova_admission,
        evidence,
        final_receipts,
        initial_snapshot,
        final_snapshot,
    } = input;
    let request_digest = digest_serializable(request).unwrap_or_default();
    let mut reasons = Vec::new();
    let mut checks = all_checks(CheckStatus::Hold);
    let now_ms = parse_time(now);

    let Some(now_ms) = now_ms else {
        reasons.push("INVALID_EVALUATION_TIME");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    };

    let Some(created_ms) = parse_time(&request.created_at) else {
        reasons.push("INVALID_REQUEST_TIME");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    };
    let Some(request_expiry_ms) = parse_time(&request.expires_at) else {
        reasons.push("INVALID_REQUEST_TIME");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    };
    if request.schema != REQUEST_SCHEMA_V01
        || !has_identifier(&request.request_id)
        || !has_identifier(&request.sender_id)
        || !has_identifier(&request.receiver_id)
        || request.sender_id == request.receiver_id
        || request.scope != "chat:text"
        || !is_sha256_digest(&request.context_digest)
        || created_ms > now_ms
        || request_expiry_ms <= now_ms
        || request_expiry_ms <= created_ms
        || request_expiry_ms - created_ms > MAX_REQUEST_AGE_MS
    {
        reasons.push("INVALID_OR_OUT_OF_SCOPE_REQUEST");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    }

    if initial_snapshot != final_snapshot {
        reasons.push("TRUST_SNAPSHOT_CHANGED");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    }
    let snapshot = initial_snapshot;
    if snapshot.schema != SNAPSHOT_SCHEMA_V01
        || snapshot.request_digest != request_digest
        || snapshot.status != SnapshotStatus::Current
        || !valid_snapshot_registry(snapshot)
    {
        reasons.push("TRUST_SNAPSHOT_UNAVAILABLE");
        let status = if snapshot.status == SnapshotStatus::Stop {
            GateStatus::Stop
        } else {
            GateStatus::Hold
        };
        return result(
            status,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    }
    let Some(snapshot_captured_ms) = parse_time(&snapshot.captured_at) else {
        reasons.push("INVALID_TRUST_SNAPSHOT_TIME");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    };
    let Some(snapshot_expiry_ms) = parse_time(&snapshot.expires_at) else {
        reasons.push("INVALID_TRUST_SNAPSHOT_TIME");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    };
    if snapshot_captured_ms > now_ms
        || snapshot_captured_ms < created_ms
        || snapshot_expiry_ms <= snapshot_captured_ms
        || now_ms - snapshot_captured_ms > MAX_SNAPSHOT_AGE_MS
        || snapshot_expiry_ms <= now_ms
    {
        reasons.push("STALE_TRUST_SNAPSHOT");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    }

    let initiation_body = match verify_receipt(
        initiation,
        ReceiptStage::Initiation,
        request,
        &request_digest,
        snapshot,
        now_ms,
    ) {
        Ok(body)
            if body.participant_id == request.sender_id
                && body.initiation_digest.is_none()
                && body.admission_digest.is_none()
                && body.evidence_set_digest.is_none() =>
        {
            body
        }
        _ => {
            reasons.push("INITIATION_MISSING_OR_INVALID");
            return result(
                GateStatus::Hold,
                request_digest,
                checks,
                reasons,
                false,
                false,
                false,
                false,
            );
        }
    };
    let initiation_digest = envelope_digest(initiation).unwrap_or_default();
    let Some(initiation_time) = parse_time(&initiation_body.issued_at) else {
        reasons.push("INVALID_INITIATION_TIME");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            false,
            false,
            false,
            false,
        );
    };

    let admission_body = match verify_receipt(
        nova_admission,
        ReceiptStage::NovaAdmission,
        request,
        &request_digest,
        snapshot,
        now_ms,
    ) {
        Ok(body)
            if body.participant_id == request.receiver_id
                && body.initiation_digest.as_deref() == Some(&initiation_digest)
                && body.admission_digest.is_none()
                && body.evidence_set_digest.is_none() =>
        {
            body
        }
        _ => {
            reasons.push("NOVA_ADMISSION_MISSING_OR_INVALID");
            return result(
                GateStatus::Hold,
                request_digest,
                checks,
                reasons,
                true,
                false,
                false,
                false,
            );
        }
    };
    let admission_digest = envelope_digest(nova_admission).unwrap_or_default();
    let Some(admission_time) = parse_time(&admission_body.issued_at) else {
        reasons.push("INVALID_ADMISSION_TIME");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            true,
            false,
            false,
            false,
        );
    };
    if admission_time <= initiation_time {
        reasons.push("ADMISSION_PRECEDES_INITIATION");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            true,
            false,
            false,
            false,
        );
    }

    if evidence.len() > 18 {
        reasons.push("UNEXPECTED_EVIDENCE_COUNT");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }
    let mut seen_slots = BTreeSet::new();
    let mut evidence_ids = BTreeSet::new();
    let mut evidence_invalid = false;
    let mut evidence_failed = false;
    let mut latest_evidence_ms = admission_time;
    let request_context_digest = request.context_digest.as_str();
    for envelope in evidence {
        let body = match parse_evidence_body(envelope) {
            Ok(body) => body,
            Err(()) => {
                evidence_invalid = true;
                continue;
            }
        };
        let slot = Slot {
            side: body.side,
            specialty: body.specialty,
        };
        if !seen_slots.insert(slot) || !evidence_ids.insert(body.evidence_id.clone()) {
            evidence_invalid = true;
            continue;
        }
        let Some(issued_ms) = parse_time(&body.issued_at) else {
            evidence_invalid = true;
            continue;
        };
        let signature_valid =
            verify_evidence(envelope, &body, request, &request_digest, snapshot, now_ms);
        let time_valid = issued_ms > admission_time
            && parse_time(&body.expires_at).is_some_and(|expires_ms| {
                issued_ms <= now_ms
                    && expires_ms > now_ms
                    && expires_ms <= request_expiry_ms
                    && expires_ms > issued_ms
                    && expires_ms - issued_ms <= MAX_EVIDENCE_AGE_MS
            });
        if snapshot.revoked_evidence_ids.contains(&body.evidence_id) {
            evidence_invalid = true;
        } else if signature_valid && time_valid {
            latest_evidence_ms = latest_evidence_ms.max(issued_ms);
            if body.result == EvidenceResult::Fail {
                evidence_failed = true;
                set_check(&mut checks, slot, CheckStatus::Stop, Some(body.evidence_id));
            } else {
                set_check(&mut checks, slot, CheckStatus::Pass, Some(body.evidence_id));
            }
        } else {
            evidence_invalid = true;
            set_check(&mut checks, slot, CheckStatus::Hold, Some(body.evidence_id));
        }
    }
    if evidence_failed {
        reasons.push("SPECIALTY_EVIDENCE_FAILED");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }
    if evidence_invalid {
        reasons.push("EVIDENCE_INVALID_OR_REVOKED");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }
    if seen_slots.len() != 18 {
        reasons.push("SPECIALTY_EVIDENCE_INCOMPLETE");
        return result(
            GateStatus::PendingEvidence,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }
    if evidence.iter().any(|envelope| {
        parse_evidence_body(envelope)
            .is_ok_and(|body| body.context_digest != request_context_digest)
    }) {
        reasons.push("EVIDENCE_CONTEXT_MISMATCH");
        return result(
            GateStatus::Stop,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }

    let evidence_digest = match evidence_set_digest(evidence) {
        Ok(digest) => digest,
        Err(()) => {
            reasons.push("EVIDENCE_DIGEST_INVALID");
            return result(
                GateStatus::Hold,
                request_digest,
                checks,
                reasons,
                true,
                true,
                false,
                false,
            );
        }
    };
    if final_receipts.is_empty() {
        reasons.push("FINAL_CONSENT_PENDING");
        return result(
            GateStatus::PendingFinalConsent,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }
    if final_receipts.len() != 2 {
        reasons.push("FINAL_CONSENT_RECEIPTS_INCOMPLETE");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }
    let mut final_participants = BTreeSet::new();
    for envelope in final_receipts {
        let body = match verify_receipt(
            envelope,
            ReceiptStage::FinalConsent,
            request,
            &request_digest,
            snapshot,
            now_ms,
        ) {
            Ok(body) => body,
            Err(()) => {
                reasons.push("FINAL_CONSENT_INVALID");
                return result(
                    GateStatus::Hold,
                    request_digest,
                    checks,
                    reasons,
                    true,
                    true,
                    false,
                    false,
                );
            }
        };
        let participant_is_party =
            body.participant_id == request.sender_id || body.participant_id == request.receiver_id;
        if !participant_is_party
            || !final_participants.insert(body.participant_id.clone())
            || body.initiation_digest.as_deref() != Some(&initiation_digest)
            || body.admission_digest.as_deref() != Some(&admission_digest)
            || body.evidence_set_digest.as_deref() != Some(&evidence_digest)
            || parse_time(&body.issued_at).is_none_or(|time| time <= latest_evidence_ms)
        {
            reasons.push("FINAL_CONSENT_BINDING_MISMATCH");
            return result(
                GateStatus::Stop,
                request_digest,
                checks,
                reasons,
                true,
                true,
                false,
                false,
            );
        }
    }
    if !final_participants.contains(&request.sender_id)
        || !final_participants.contains(&request.receiver_id)
    {
        reasons.push("BOTH_FINAL_CONSENTS_REQUIRED");
        return result(
            GateStatus::Hold,
            request_digest,
            checks,
            reasons,
            true,
            true,
            false,
            false,
        );
    }

    reasons.push("REFERENCE_CHECKS_PASSED_NO_AUTHORITY_GRANTED");
    result(
        GateStatus::ReferencePassed,
        request_digest,
        checks,
        reasons,
        true,
        true,
        true,
        true,
    )
}

/// Loads and verifies two independent signed snapshots before evaluating.
/// Any unavailable or invalid trust/clock input returns HOLD. A successful
/// signature only proves that the configured anchor signed the snapshot; the
/// host remains responsible for securely provisioning that anchor and provider.
#[must_use]
pub fn evaluate_with_snapshot_provider(
    input: GateEvidenceInputV01<'_>,
    provider: &impl TrustSnapshotProvider,
    anchor: &SnapshotTrustAnchorV01,
) -> GateResultV01 {
    let request_digest = digest_serializable(input.request).unwrap_or_default();
    let hold = || {
        result(
            GateStatus::Hold,
            request_digest.clone(),
            all_checks(CheckStatus::Hold),
            vec!["TRUST_SNAPSHOT_UNAVAILABLE_OR_UNTRUSTED"],
            false,
            false,
            false,
            false,
        )
    };

    let Ok(time_before) = provider.current_time() else {
        return hold();
    };
    let Some(time_before_ms) = parse_time(&time_before) else {
        return hold();
    };
    let Ok(first) = provider.load_snapshot(&request_digest) else {
        return hold();
    };
    let Ok(second) = provider.load_snapshot(&request_digest) else {
        return hold();
    };
    let Ok(time_after) = provider.current_time() else {
        return hold();
    };
    let Some(time_after_ms) = parse_time(&time_after) else {
        return hold();
    };
    if time_after_ms < time_before_ms {
        return hold();
    }

    let Some(first_snapshot) = verify_signed_snapshot(&first, anchor) else {
        return hold();
    };
    let Some(second_snapshot) = verify_signed_snapshot(&second, anchor) else {
        return hold();
    };

    evaluate(
        GateInputV01 {
            request: input.request,
            initiation: input.initiation,
            nova_admission: input.nova_admission,
            evidence: input.evidence,
            final_receipts: input.final_receipts,
            initial_snapshot: &first_snapshot,
            final_snapshot: &second_snapshot,
        },
        &time_after,
    )
}

/// Produces domain-separated signing bytes for synthetic fixtures and
/// independent test tooling. This uses the Node reference's evidence domain.
pub fn guard_signing_bytes(body: &Value) -> Result<Vec<u8>, serde_json::Error> {
    reference_signing_bytes(body)
}

/// Produces domain-separated signing bytes for synthetic human receipts.
pub fn receipt_signing_bytes(body: &Value) -> Result<Vec<u8>, serde_json::Error> {
    reference_signing_bytes(body)
}

/// Canonical Node-reference signing bytes for a JSON evidence or receipt body.
pub fn reference_signing_bytes(body: &Value) -> Result<Vec<u8>, serde_json::Error> {
    signing_bytes(REFERENCE_DOMAIN, body)
}

/// Canonical JSON used by this Rust bridge, tested against shared Node vectors.
pub fn reference_canonical_json(value: &Value) -> Result<String, serde_json::Error> {
    String::from_utf8(canonical_json(value)?)
        .map_err(<serde_json::Error as serde::ser::Error>::custom)
}

/// SHA-256 of the bridge's canonical JSON representation.
pub fn reference_digest(value: &Value) -> Result<String, serde_json::Error> {
    Ok(digest_bytes(&canonical_json(value)?))
}

/// Produces the signed bytes for the Rust bridge's provider snapshot envelope.
pub fn trust_snapshot_signing_bytes(
    envelope: &SignedTrustSnapshotV01,
) -> Result<Vec<u8>, serde_json::Error> {
    let payload = serde_json::json!({
        "schema": envelope.schema,
        "providerId": envelope.provider_id,
        "keyId": envelope.key_id,
        "snapshot": envelope.snapshot,
    });
    signing_bytes(SNAPSHOT_DOMAIN, &payload)
}

fn verify_signed_snapshot(
    envelope: &SignedTrustSnapshotV01,
    anchor: &SnapshotTrustAnchorV01,
) -> Option<TrustSnapshotV01> {
    if envelope.schema != SIGNED_SNAPSHOT_SCHEMA_V01
        || envelope.provider_id != anchor.provider_id
        || envelope.key_id != anchor.key_id
        || !has_identifier(&anchor.provider_id)
        || !has_identifier(&anchor.key_id)
        || anchor.public_key.len() != 43
        || envelope.signature.len() != 86
    {
        return None;
    }
    let public_key_bytes = URL_SAFE_NO_PAD.decode(&anchor.public_key).ok()?;
    if public_key_bytes.len() != 32
        || URL_SAFE_NO_PAD.encode(&public_key_bytes) != anchor.public_key
    {
        return None;
    }
    let public_key_array = <[u8; 32]>::try_from(public_key_bytes.as_slice()).ok()?;
    let public_key = VerifyingKey::from_bytes(&public_key_array).ok()?;
    let signature_bytes = URL_SAFE_NO_PAD.decode(&envelope.signature).ok()?;
    if signature_bytes.len() != 64 || URL_SAFE_NO_PAD.encode(&signature_bytes) != envelope.signature
    {
        return None;
    }
    let signature = Signature::from_slice(&signature_bytes).ok()?;
    let bytes = trust_snapshot_signing_bytes(envelope).ok()?;
    public_key.verify(&bytes, &signature).ok()?;
    Some(envelope.snapshot.clone())
}

fn verify_evidence(
    envelope: &SignedEnvelopeV01,
    body: &EvidenceBodyV01,
    request: &RequestV01,
    request_digest: &str,
    snapshot: &TrustSnapshotV01,
    now_ms: i64,
) -> bool {
    body.schema == EVIDENCE_SCHEMA_V01
        && has_identifier(&body.evidence_id)
        && has_identifier(&body.issuer_id)
        && has_identifier(&body.key_id)
        && body.request_digest == request_digest
        && body.context_digest == request.context_digest
        && issuer_for_evidence(snapshot, body, request, now_ms).is_some_and(|issuer| {
            !snapshot.revoked_issuer_ids.contains(&issuer.issuer_id)
                && verify_envelope(envelope, issuer, REFERENCE_DOMAIN)
        })
}

fn verify_receipt(
    envelope: &SignedEnvelopeV01,
    stage: ReceiptStage,
    request: &RequestV01,
    request_digest: &str,
    snapshot: &TrustSnapshotV01,
    now_ms: i64,
) -> Result<HumanReceiptBodyV01, ()> {
    if envelope.algorithm != "Ed25519" {
        return Err(());
    }
    let body: HumanReceiptBodyV01 =
        serde_json::from_value(envelope.body.clone()).map_err(|_| ())?;
    if body.schema != RECEIPT_SCHEMA_V01
        || !has_identifier(&body.receipt_id)
        || !has_identifier(&body.issuer_id)
        || !has_identifier(&body.key_id)
        || !has_identifier(&body.participant_id)
        || body.stage != stage
        || body.request_digest != request_digest
        || snapshot.revoked_evidence_ids.contains(&body.receipt_id)
    {
        return Err(());
    }
    let body_time = parse_time(&body.issued_at).ok_or(())?;
    let expiry = parse_time(&body.expires_at).ok_or(())?;
    if body_time > now_ms
        || expiry <= now_ms
        || expiry > parse_time(&request.expires_at).ok_or(())?
        || expiry <= body_time
        || expiry - body_time > MAX_RECEIPT_AGE_MS
    {
        return Err(());
    }
    let side = if body.participant_id == request.sender_id {
        Side::Sender
    } else if body.participant_id == request.receiver_id {
        Side::Receiver
    } else {
        return Err(());
    };
    let issuer = snapshot
        .issuers
        .iter()
        .find(|issuer| {
            issuer.issuer_id == body.issuer_id
                && issuer.key_id == body.key_id
                && issuer.participant_id == body.participant_id
                && issuer.side == side
                && issuer.specialty.is_none()
                && issuer.receipt_stages.contains(&stage)
                && issuer_valid_for(issuer, body_time, expiry, now_ms)
                && !snapshot.revoked_issuer_ids.contains(&issuer.issuer_id)
        })
        .ok_or(())?;
    if !verify_envelope(envelope, issuer, REFERENCE_DOMAIN) {
        return Err(());
    }
    Ok(body)
}

fn issuer_for_evidence<'a>(
    snapshot: &'a TrustSnapshotV01,
    body: &EvidenceBodyV01,
    request: &RequestV01,
    now_ms: i64,
) -> Option<&'a TrustedIssuerV01> {
    let participant_id = match body.side {
        Side::Sender => &request.sender_id,
        Side::Receiver => &request.receiver_id,
    };
    let issued_ms = parse_time(&body.issued_at)?;
    let expires_ms = parse_time(&body.expires_at)?;
    snapshot.issuers.iter().find(|issuer| {
        issuer.issuer_id == body.issuer_id
            && issuer.key_id == body.key_id
            && issuer.participant_id.as_str() == participant_id.as_str()
            && issuer.side == body.side
            && issuer.specialty == Some(body.specialty)
            && issuer.receipt_stages.is_empty()
            && issuer_valid_for(issuer, issued_ms, expires_ms, now_ms)
    })
}

fn issuer_valid_for(
    issuer: &TrustedIssuerV01,
    issued_ms: i64,
    expires_ms: i64,
    now_ms: i64,
) -> bool {
    parse_time(&issuer.valid_from).is_some_and(|time| time <= issued_ms && time <= now_ms)
        && parse_time(&issuer.valid_until).is_some_and(|time| time >= expires_ms && time > now_ms)
}

fn valid_snapshot_registry(snapshot: &TrustSnapshotV01) -> bool {
    if !has_identifier(&snapshot.revision)
        || snapshot.issuers.is_empty()
        || snapshot.issuers.len() > MAX_SNAPSHOT_ISSUERS
        || snapshot.revoked_evidence_ids.len() > MAX_REVOKED_IDS
        || snapshot.revoked_issuer_ids.len() > MAX_REVOKED_IDS
        || snapshot
            .revoked_evidence_ids
            .iter()
            .chain(&snapshot.revoked_issuer_ids)
            .any(|id| !has_identifier(id))
    {
        return false;
    }
    let mut issuer_keys = BTreeSet::new();
    let mut specialties = BTreeSet::new();
    let mut receipt_stages = BTreeSet::new();
    for issuer in &snapshot.issuers {
        let Some(valid_from) = parse_time(&issuer.valid_from) else {
            return false;
        };
        let Some(valid_until) = parse_time(&issuer.valid_until) else {
            return false;
        };
        if issuer.public_key.len() != 43 {
            return false;
        }
        let Ok(public_key) = URL_SAFE_NO_PAD.decode(&issuer.public_key) else {
            return false;
        };
        if !has_identifier(&issuer.issuer_id)
            || !has_identifier(&issuer.key_id)
            || !has_identifier(&issuer.participant_id)
            || valid_until <= valid_from
            || public_key.len() != 32
            || URL_SAFE_NO_PAD.encode(&public_key) != issuer.public_key
            || !issuer_keys.insert((issuer.issuer_id.as_str(), issuer.key_id.as_str()))
        {
            return false;
        }
        if let Some(specialty) = issuer.specialty {
            if !issuer.receipt_stages.is_empty() || !specialties.insert((issuer.side, specialty)) {
                return false;
            }
        } else {
            if issuer.receipt_stages.is_empty()
                || issuer
                    .receipt_stages
                    .iter()
                    .any(|stage| !receipt_stages.insert((issuer.side, *stage)))
            {
                return false;
            }
        }
    }
    [Side::Sender, Side::Receiver].into_iter().all(|side| {
        Specialty::ALL
            .into_iter()
            .all(|specialty| specialties.contains(&(side, specialty)))
    }) && [
        (Side::Sender, ReceiptStage::Initiation),
        (Side::Sender, ReceiptStage::FinalConsent),
        (Side::Receiver, ReceiptStage::NovaAdmission),
        (Side::Receiver, ReceiptStage::FinalConsent),
    ]
    .into_iter()
    .all(|stage| receipt_stages.contains(&stage))
}

fn verify_envelope(envelope: &SignedEnvelopeV01, issuer: &TrustedIssuerV01, domain: &[u8]) -> bool {
    if envelope.algorithm != "Ed25519" {
        return false;
    }
    if issuer.public_key.len() != 43 {
        return false;
    }
    let Ok(public_key_bytes) = URL_SAFE_NO_PAD.decode(&issuer.public_key) else {
        return false;
    };
    if URL_SAFE_NO_PAD.encode(&public_key_bytes) != issuer.public_key {
        return false;
    }
    let Ok(public_key_array) = <[u8; 32]>::try_from(public_key_bytes.as_slice()) else {
        return false;
    };
    let Ok(public_key) = VerifyingKey::from_bytes(&public_key_array) else {
        return false;
    };
    if envelope.signature.len() != 86 {
        return false;
    }
    let Ok(signature_bytes) = URL_SAFE_NO_PAD.decode(&envelope.signature) else {
        return false;
    };
    if URL_SAFE_NO_PAD.encode(&signature_bytes) != envelope.signature {
        return false;
    }
    let Ok(signature) = Signature::from_slice(&signature_bytes) else {
        return false;
    };
    let Ok(bytes) = signing_bytes(domain, &envelope.body) else {
        return false;
    };
    public_key.verify(&bytes, &signature).is_ok()
}

fn parse_evidence_body(envelope: &SignedEnvelopeV01) -> Result<EvidenceBodyV01, ()> {
    if envelope.algorithm != "Ed25519" {
        return Err(());
    }
    let body: EvidenceBodyV01 = serde_json::from_value(envelope.body.clone()).map_err(|_| ())?;
    if body.schema != EVIDENCE_SCHEMA_V01 {
        return Err(());
    }
    Ok(body)
}

fn evidence_set_digest(evidence: &[SignedEnvelopeV01]) -> Result<String, ()> {
    let mut digests = evidence
        .iter()
        .map(envelope_digest)
        .collect::<Result<Vec<_>, _>>()?;
    digests.sort();
    digest_serializable(&digests).map_err(|_| ())
}

fn envelope_digest(envelope: &SignedEnvelopeV01) -> Result<String, ()> {
    digest_serializable(envelope).map_err(|_| ())
}

fn digest_serializable<T: Serialize>(value: &T) -> Result<String, serde_json::Error> {
    let value = serde_json::to_value(value)?;
    let canonical = canonical_json(&value)?;
    Ok(digest_bytes(&canonical))
}

fn digest_bytes(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn signing_bytes(domain: &[u8], body: &Value) -> Result<Vec<u8>, serde_json::Error> {
    let canonical = canonical_json(body)?;
    let mut bytes = Vec::with_capacity(domain.len() + canonical.len());
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&canonical);
    Ok(bytes)
}

fn canonical_json(value: &Value) -> Result<Vec<u8>, serde_json::Error> {
    canonical_json_at_depth(value, 0)
}

fn canonical_json_at_depth(value: &Value, depth: usize) -> Result<Vec<u8>, serde_json::Error> {
    if depth > 64 {
        return Err(canonical_error("JSON nesting exceeds the contract limit"));
    }
    match value {
        Value::Null | Value::Bool(_) => serde_json::to_vec(value),
        Value::Number(number) => {
            let safe_integer = number.as_i64().is_some_and(|integer| {
                (-9_007_199_254_740_991..=9_007_199_254_740_991).contains(&integer)
            }) || number
                .as_u64()
                .is_some_and(|integer| integer <= 9_007_199_254_740_991);
            if safe_integer {
                serde_json::to_vec(value)
            } else {
                Err(canonical_error(
                    "Only interoperable JSON integers are accepted",
                ))
            }
        }
        Value::String(string) => {
            if string.len() > MAX_CANONICAL_BODY_BYTES {
                return Err(canonical_error("JSON string exceeds the contract limit"));
            }
            serde_json::to_vec(value)
        }
        Value::Array(values) => {
            let mut output = Vec::from(b"[".as_slice());
            for (index, item) in values.iter().enumerate() {
                if index > 0 {
                    output.push(b',');
                }
                output.extend(canonical_json_at_depth(item, depth + 1)?);
                if output.len() > MAX_CANONICAL_BODY_BYTES {
                    return Err(canonical_error("JSON body exceeds the contract limit"));
                }
            }
            output.push(b']');
            Ok(output)
        }
        Value::Object(values) => {
            let mut sorted: Vec<_> = values.iter().collect();
            sorted.sort_by(|(left, _), (right, _)| left.encode_utf16().cmp(right.encode_utf16()));
            let mut output = Vec::from(b"{".as_slice());
            for (index, (key, item)) in sorted.iter().enumerate() {
                if index > 0 {
                    output.push(b',');
                }
                if key.len() > MAX_CANONICAL_BODY_BYTES {
                    return Err(canonical_error(
                        "JSON property name exceeds the contract limit",
                    ));
                }
                output.extend(serde_json::to_vec(key)?);
                output.push(b':');
                output.extend(canonical_json_at_depth(item, depth + 1)?);
                if output.len() > MAX_CANONICAL_BODY_BYTES {
                    return Err(canonical_error("JSON body exceeds the contract limit"));
                }
            }
            output.push(b'}');
            Ok(output)
        }
    }
}

fn canonical_error(message: &str) -> serde_json::Error {
    <serde_json::Error as serde::ser::Error>::custom(message)
}

fn has_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.:".contains(&byte))
}

fn is_sha256_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn parse_time(timestamp: &str) -> Option<i64> {
    DateTime::parse_from_rfc3339(timestamp)
        .ok()
        .map(|value| value.timestamp_millis())
}

fn all_checks(status: CheckStatus) -> Vec<SpecialtyCheck> {
    [Side::Sender, Side::Receiver]
        .into_iter()
        .flat_map(|side| {
            Specialty::ALL
                .into_iter()
                .map(move |specialty| SpecialtyCheck {
                    side,
                    specialty,
                    status,
                    evidence_id: None,
                })
        })
        .collect()
}

fn set_check(
    checks: &mut [SpecialtyCheck],
    slot: Slot,
    status: CheckStatus,
    evidence_id: Option<String>,
) {
    if let Some(check) = checks
        .iter_mut()
        .find(|check| check.side == slot.side && check.specialty == slot.specialty)
    {
        check.status = status;
        check.evidence_id = evidence_id;
    }
}

#[allow(clippy::too_many_arguments)]
fn result(
    status: GateStatus,
    request_digest: String,
    specialty_checks: Vec<SpecialtyCheck>,
    reason_codes: Vec<&str>,
    initiation_accepted: bool,
    nova_admission_accepted: bool,
    final_sender_consent: bool,
    final_receiver_consent: bool,
) -> GateResultV01 {
    let trace_body = (
        status,
        &request_digest,
        &specialty_checks,
        &reason_codes,
        initiation_accepted,
        nova_admission_accepted,
        final_sender_consent,
        final_receiver_consent,
    );
    let trace_digest = digest_serializable(&trace_body).unwrap_or_default();
    GateResultV01 {
        schema: "elixer-6ri9ade-result-v0.1".to_owned(),
        mode: "REFERENCE_ONLY".to_owned(),
        classification: "SYNTHETIC_ONLY".to_owned(),
        status,
        request_digest,
        specialty_checks,
        reason_codes: reason_codes.into_iter().map(str::to_owned).collect(),
        initiation_accepted,
        nova_admission_accepted,
        final_sender_consent,
        final_receiver_consent,
        can_open_contact: false,
        operative_authority: "NONE".to_owned(),
        runtime_connected: false,
        external_side_effect: false,
        trace_digest,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use std::cell::Cell;
    use std::collections::BTreeMap;
    use std::error::Error;

    #[test]
    fn specialty_inventory_contains_nine_distinct_controls() {
        let unique: BTreeSet<_> = Specialty::ALL.into_iter().collect();
        assert_eq!(unique.len(), 9);
    }

    #[test]
    fn canonical_signing_bytes_ignore_object_insertion_order()
    -> Result<(), Box<dyn std::error::Error>> {
        let first: Value = serde_json::from_str(r#"{"z":1,"a":{"y":true,"b":"x"}}"#)?;
        let second: Value = serde_json::from_str(r#"{"a":{"b":"x","y":true},"z":1}"#)?;
        assert_eq!(guard_signing_bytes(&first)?, guard_signing_bytes(&second)?);
        Ok(())
    }

    struct Fixture {
        request: RequestV01,
        snapshot: TrustSnapshotV01,
        initiation: SignedEnvelopeV01,
        nova_admission: SignedEnvelopeV01,
        evidence: Vec<SignedEnvelopeV01>,
        final_receipts: Vec<SignedEnvelopeV01>,
        keys: BTreeMap<String, SigningKey>,
    }

    impl Fixture {
        fn new() -> Result<Self, Box<dyn Error>> {
            let request = RequestV01 {
                schema: REQUEST_SCHEMA_V01.to_owned(),
                request_id: "synthetic-request-001".to_owned(),
                sender_id: "synthetic-sender".to_owned(),
                receiver_id: "synthetic-receiver".to_owned(),
                scope: "chat:text".to_owned(),
                context_digest: digest_bytes(b"synthetic-context-001"),
                created_at: "2030-01-01T00:00:00Z".to_owned(),
                expires_at: "2030-01-01T00:10:00Z".to_owned(),
            };
            let request_digest = digest_serializable(&request)?;
            let mut issuers = Vec::new();
            let mut keys = BTreeMap::new();
            let mut seed = 1_u8;
            for (side, participant_id, stages) in [
                (
                    Side::Sender,
                    request.sender_id.as_str(),
                    vec![ReceiptStage::Initiation, ReceiptStage::FinalConsent],
                ),
                (
                    Side::Receiver,
                    request.receiver_id.as_str(),
                    vec![ReceiptStage::NovaAdmission, ReceiptStage::FinalConsent],
                ),
            ] {
                let (issuer, key) = Self::issuer(&mut seed, participant_id, side, None, stages);
                keys.insert(issuer.issuer_id.clone(), key);
                issuers.push(issuer);
            }
            for side in [Side::Sender, Side::Receiver] {
                let participant_id = match side {
                    Side::Sender => request.sender_id.as_str(),
                    Side::Receiver => request.receiver_id.as_str(),
                };
                for specialty in Specialty::ALL {
                    let (issuer, key) =
                        Self::issuer(&mut seed, participant_id, side, Some(specialty), Vec::new());
                    keys.insert(issuer.issuer_id.clone(), key);
                    issuers.push(issuer);
                }
            }
            let snapshot = TrustSnapshotV01 {
                schema: SNAPSHOT_SCHEMA_V01.to_owned(),
                revision: "synthetic-snapshot-001".to_owned(),
                request_digest: request_digest.clone(),
                captured_at: "2030-01-01T00:04:40Z".to_owned(),
                expires_at: "2030-01-01T00:06:00Z".to_owned(),
                status: SnapshotStatus::Current,
                issuers,
                revoked_evidence_ids: Vec::new(),
                revoked_issuer_ids: Vec::new(),
            };
            let mut fixture = Self {
                request,
                snapshot,
                initiation: Self::placeholder(),
                nova_admission: Self::placeholder(),
                evidence: Vec::new(),
                final_receipts: Vec::new(),
                keys,
            };
            fixture.initiation = fixture.receipt(
                "synthetic-initiation-001",
                ReceiptStage::Initiation,
                "synthetic-sender",
                None,
                None,
                None,
                "2030-01-01T00:01:00Z",
            )?;
            let initiation_digest =
                envelope_digest(&fixture.initiation).map_err(|_| "invalid initiation digest")?;
            fixture.nova_admission = fixture.receipt(
                "synthetic-nova-001",
                ReceiptStage::NovaAdmission,
                "synthetic-receiver",
                Some(initiation_digest),
                None,
                None,
                "2030-01-01T00:02:00Z",
            )?;
            let request_digest = digest_serializable(&fixture.request)?;
            let context_digest = fixture.request.context_digest.clone();
            for side in [Side::Sender, Side::Receiver] {
                for specialty in Specialty::ALL {
                    let issuer = fixture
                        .snapshot
                        .issuers
                        .iter()
                        .find(|issuer| issuer.side == side && issuer.specialty == Some(specialty))
                        .ok_or("missing synthetic issuer")?
                        .clone();
                    let body = EvidenceBodyV01 {
                        schema: EVIDENCE_SCHEMA_V01.to_owned(),
                        issuer_id: issuer.issuer_id.clone(),
                        key_id: issuer.key_id.clone(),
                        evidence_id: format!("evidence-{}-{specialty:?}", side_code(side)),
                        request_digest: request_digest.clone(),
                        context_digest: context_digest.clone(),
                        side,
                        specialty,
                        result: EvidenceResult::Pass,
                        issued_at: "2030-01-01T00:03:50Z".to_owned(),
                        expires_at: "2030-01-01T00:05:45Z".to_owned(),
                    };
                    let envelope = fixture.sign(body, &issuer.issuer_id, false)?;
                    fixture.evidence.push(envelope);
                }
            }
            let evidence_digest =
                evidence_set_digest(&fixture.evidence).map_err(|_| "invalid evidence digest")?;
            let initiation_digest =
                envelope_digest(&fixture.initiation).map_err(|_| "invalid initiation digest")?;
            let admission_digest =
                envelope_digest(&fixture.nova_admission).map_err(|_| "invalid admission digest")?;
            for participant_id in ["synthetic-sender", "synthetic-receiver"] {
                fixture.final_receipts.push(fixture.receipt(
                    &format!("final-{participant_id}"),
                    ReceiptStage::FinalConsent,
                    participant_id,
                    Some(initiation_digest.clone()),
                    Some(admission_digest.clone()),
                    Some(evidence_digest.clone()),
                    "2030-01-01T00:04:55Z",
                )?);
            }
            Ok(fixture)
        }

        fn issuer(
            seed: &mut u8,
            participant_id: &str,
            side: Side,
            specialty: Option<Specialty>,
            receipt_stages: Vec<ReceiptStage>,
        ) -> (TrustedIssuerV01, SigningKey) {
            let key = SigningKey::from_bytes(&[*seed; 32]);
            let issuer_id = format!("issuer-{}", *seed);
            let key_id = format!("key-{}", *seed);
            *seed = seed.saturating_add(1);
            let issuer = TrustedIssuerV01 {
                issuer_id,
                participant_id: participant_id.to_owned(),
                side,
                specialty,
                receipt_stages,
                key_id,
                public_key: URL_SAFE_NO_PAD.encode(key.verifying_key().to_bytes()),
                valid_from: "2030-01-01T00:00:00Z".to_owned(),
                valid_until: "2030-01-01T00:09:00Z".to_owned(),
            };
            (issuer, key)
        }

        fn placeholder() -> SignedEnvelopeV01 {
            SignedEnvelopeV01 {
                algorithm: "Ed25519".to_owned(),
                body: Value::Null,
                signature: String::new(),
            }
        }

        #[allow(clippy::too_many_arguments)]
        fn receipt(
            &self,
            receipt_id: &str,
            stage: ReceiptStage,
            participant_id: &str,
            initiation_digest: Option<String>,
            admission_digest: Option<String>,
            evidence_set_digest: Option<String>,
            issued_at: &str,
        ) -> Result<SignedEnvelopeV01, Box<dyn Error>> {
            let side = if participant_id == self.request.sender_id {
                Side::Sender
            } else {
                Side::Receiver
            };
            let issuer = self
                .snapshot
                .issuers
                .iter()
                .find(|issuer| {
                    issuer.participant_id == participant_id
                        && issuer.side == side
                        && issuer.specialty.is_none()
                        && issuer.receipt_stages.contains(&stage)
                })
                .ok_or("missing receipt issuer")?;
            self.sign(
                HumanReceiptBodyV01 {
                    schema: RECEIPT_SCHEMA_V01.to_owned(),
                    issuer_id: issuer.issuer_id.clone(),
                    key_id: issuer.key_id.clone(),
                    receipt_id: receipt_id.to_owned(),
                    request_digest: digest_serializable(&self.request)?,
                    stage,
                    participant_id: participant_id.to_owned(),
                    initiation_digest,
                    admission_digest,
                    evidence_set_digest,
                    issued_at: issued_at.to_owned(),
                    expires_at: "2030-01-01T00:06:00Z".to_owned(),
                },
                &issuer.issuer_id,
                true,
            )
        }

        fn sign<T: Serialize>(
            &self,
            body: T,
            issuer_id: &str,
            receipt: bool,
        ) -> Result<SignedEnvelopeV01, Box<dyn Error>> {
            let body = serde_json::to_value(body)?;
            let bytes = if receipt {
                receipt_signing_bytes(&body)?
            } else {
                guard_signing_bytes(&body)?
            };
            let key = self.keys.get(issuer_id).ok_or("missing signing key")?;
            Ok(SignedEnvelopeV01 {
                algorithm: "Ed25519".to_owned(),
                body,
                signature: URL_SAFE_NO_PAD.encode(key.sign(&bytes).to_bytes()),
            })
        }

        fn result(&self) -> GateResultV01 {
            evaluate(self.input(), "2030-01-01T00:04:57Z")
        }

        fn input(&self) -> GateInputV01<'_> {
            GateInputV01 {
                request: &self.request,
                initiation: &self.initiation,
                nova_admission: &self.nova_admission,
                evidence: &self.evidence,
                final_receipts: &self.final_receipts,
                initial_snapshot: &self.snapshot,
                final_snapshot: &self.snapshot,
            }
        }
    }

    fn side_code(side: Side) -> &'static str {
        match side {
            Side::Sender => "sender",
            Side::Receiver => "receiver",
        }
    }

    struct TestSnapshotProvider {
        snapshots: Vec<Result<SignedTrustSnapshotV01, SnapshotProviderError>>,
        times: Vec<Result<String, SnapshotProviderError>>,
        snapshot_calls: Cell<usize>,
        time_calls: Cell<usize>,
    }

    impl TestSnapshotProvider {
        fn new(
            snapshots: Vec<Result<SignedTrustSnapshotV01, SnapshotProviderError>>,
            times: Vec<Result<String, SnapshotProviderError>>,
        ) -> Self {
            Self {
                snapshots,
                times,
                snapshot_calls: Cell::new(0),
                time_calls: Cell::new(0),
            }
        }
    }

    impl TrustSnapshotProvider for TestSnapshotProvider {
        fn current_time(&self) -> Result<String, SnapshotProviderError> {
            let index = self.time_calls.get();
            self.time_calls.set(index + 1);
            self.times
                .get(index)
                .cloned()
                .unwrap_or(Err(SnapshotProviderError::Unavailable))
        }

        fn load_snapshot(
            &self,
            _request_digest: &str,
        ) -> Result<SignedTrustSnapshotV01, SnapshotProviderError> {
            let index = self.snapshot_calls.get();
            self.snapshot_calls.set(index + 1);
            self.snapshots
                .get(index)
                .cloned()
                .unwrap_or(Err(SnapshotProviderError::Unavailable))
        }
    }

    fn sign_snapshot(
        snapshot: TrustSnapshotV01,
        key: &SigningKey,
    ) -> Result<SignedTrustSnapshotV01, Box<dyn Error>> {
        let mut envelope = SignedTrustSnapshotV01 {
            schema: SIGNED_SNAPSHOT_SCHEMA_V01.to_owned(),
            provider_id: "synthetic-host-snapshot-provider".to_owned(),
            key_id: "synthetic-host-root-v1".to_owned(),
            snapshot,
            signature: String::new(),
        };
        envelope.signature = URL_SAFE_NO_PAD.encode(
            key.sign(&trust_snapshot_signing_bytes(&envelope)?)
                .to_bytes(),
        );
        Ok(envelope)
    }

    fn test_anchor(key: &SigningKey) -> SnapshotTrustAnchorV01 {
        SnapshotTrustAnchorV01 {
            provider_id: "synthetic-host-snapshot-provider".to_owned(),
            key_id: "synthetic-host-root-v1".to_owned(),
            public_key: URL_SAFE_NO_PAD.encode(key.verifying_key().to_bytes()),
        }
    }

    fn evaluate_from_provider(
        fixture: &Fixture,
        provider: &TestSnapshotProvider,
        anchor: &SnapshotTrustAnchorV01,
    ) -> GateResultV01 {
        evaluate_with_snapshot_provider(
            GateEvidenceInputV01 {
                request: &fixture.request,
                initiation: &fixture.initiation,
                nova_admission: &fixture.nova_admission,
                evidence: &fixture.evidence,
                final_receipts: &fixture.final_receipts,
            },
            provider,
            anchor,
        )
    }

    #[test]
    fn all_eighteen_signed_checks_and_separate_human_gates_pass_without_authority()
    -> Result<(), Box<dyn Error>> {
        let fixture = Fixture::new()?;
        let first_body =
            parse_evidence_body(&fixture.evidence[0]).map_err(|_| "invalid test evidence body")?;
        assert!(
            verify_evidence(
                &fixture.evidence[0],
                &first_body,
                &fixture.request,
                &digest_serializable(&fixture.request)?,
                &fixture.snapshot,
                parse_time("2030-01-01T00:04:57Z").ok_or("invalid test time")?,
            ),
            "evidence signature or issuer binding rejected"
        );
        let result = fixture.result();
        assert_eq!(
            result.status,
            GateStatus::ReferencePassed,
            "{:?}",
            result.reason_codes
        );
        assert_eq!(result.specialty_checks.len(), 18);
        assert!(
            result
                .specialty_checks
                .iter()
                .all(|check| check.status == CheckStatus::Pass)
        );
        assert!(result.initiation_accepted);
        assert!(result.nova_admission_accepted);
        assert!(result.final_sender_consent);
        assert!(result.final_receiver_consent);
        assert!(!result.can_open_contact);
        assert_eq!(result.operative_authority, "NONE");
        assert!(!result.external_side_effect);
        Ok(())
    }

    #[test]
    fn missing_evidence_waits_and_never_opens_contact() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        fixture.evidence.pop();
        let result = fixture.result();
        assert_eq!(
            result.status,
            GateStatus::PendingEvidence,
            "{:?}",
            result.reason_codes
        );
        assert!(!result.can_open_contact);
        assert!(!result.external_side_effect);
        Ok(())
    }

    #[test]
    fn changed_signed_evidence_fails_closed() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let body = fixture.evidence[0]
            .body
            .as_object_mut()
            .ok_or("evidence body must be an object")?;
        body.insert("result".to_owned(), Value::String("FAIL".to_owned()));
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn revoked_evidence_holds_even_when_its_signature_is_valid() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let body: EvidenceBodyV01 = serde_json::from_value(fixture.evidence[0].body.clone())?;
        fixture.snapshot.revoked_evidence_ids.push(body.evidence_id);
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn revoked_issuer_holds_even_when_evidence_is_current() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let body: EvidenceBodyV01 = serde_json::from_value(fixture.evidence[0].body.clone())?;
        fixture.snapshot.revoked_issuer_ids.push(body.issuer_id);
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn signed_but_expired_evidence_holds() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let mut body: EvidenceBodyV01 = serde_json::from_value(fixture.evidence[0].body.clone())?;
        body.expires_at = "2030-01-01T00:04:56Z".to_owned();
        fixture.evidence[0] = fixture.sign(body.clone(), &body.issuer_id, false)?;
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn signed_context_mismatch_holds() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let mut body: EvidenceBodyV01 = serde_json::from_value(fixture.evidence[0].body.clone())?;
        body.context_digest = digest_bytes(b"different synthetic context");
        fixture.evidence[0] = fixture.sign(body.clone(), &body.issuer_id, false)?;
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn signed_failure_result_stops() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let mut body: EvidenceBodyV01 = serde_json::from_value(fixture.evidence[0].body.clone())?;
        body.result = EvidenceResult::Fail;
        fixture.evidence[0] = fixture.sign(body.clone(), &body.issuer_id, false)?;
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Stop);
        assert!(!result.can_open_contact);
        assert!(!result.external_side_effect);
        Ok(())
    }

    #[test]
    fn changed_trust_snapshot_holds() -> Result<(), Box<dyn Error>> {
        let fixture = Fixture::new()?;
        let mut changed_snapshot = fixture.snapshot.clone();
        changed_snapshot.revision = "replacement-revision".to_owned();
        let result = evaluate(
            GateInputV01 {
                final_snapshot: &changed_snapshot,
                ..fixture.input()
            },
            "2030-01-01T00:04:57Z",
        );
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn final_receipts_must_bind_the_exact_evidence_set() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        let body = fixture.final_receipts[0]
            .body
            .as_object_mut()
            .ok_or("receipt body must be an object")?;
        body.insert(
            "evidenceSetDigest".to_owned(),
            Value::String("different-evidence-set".to_owned()),
        );
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn expired_request_stops() -> Result<(), Box<dyn Error>> {
        let fixture = Fixture::new()?;
        let result = evaluate(fixture.input(), "2030-01-01T00:11:00Z");
        assert_eq!(result.status, GateStatus::Stop);
        assert!(!result.can_open_contact);
        assert!(!result.external_side_effect);
        Ok(())
    }

    #[test]
    fn missing_final_consent_remains_pending() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        fixture.final_receipts.clear();
        let result = fixture.result();
        assert_eq!(
            result.status,
            GateStatus::PendingFinalConsent,
            "{:?}",
            result.reason_codes
        );
        assert!(!result.final_sender_consent);
        assert!(!result.final_receiver_consent);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn invalid_nova_signature_does_not_admit_receiver() -> Result<(), Box<dyn Error>> {
        let mut fixture = Fixture::new()?;
        fixture.nova_admission.signature = URL_SAFE_NO_PAD.encode([0_u8; 64]);
        let result = fixture.result();
        assert_eq!(result.status, GateStatus::Hold);
        assert!(result.initiation_accepted, "{:?}", result.reason_codes);
        assert!(!result.nova_admission_accepted);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn trusted_provider_requires_two_identical_signed_snapshots() -> Result<(), Box<dyn Error>> {
        let fixture = Fixture::new()?;
        let key = SigningKey::from_bytes(&[91_u8; 32]);
        let signed = sign_snapshot(fixture.snapshot.clone(), &key)?;
        let provider = TestSnapshotProvider::new(
            vec![Ok(signed.clone()), Ok(signed)],
            vec![
                Ok("2030-01-01T00:04:56Z".to_owned()),
                Ok("2030-01-01T00:04:57Z".to_owned()),
            ],
        );
        let result = evaluate_from_provider(&fixture, &provider, &test_anchor(&key));
        assert_eq!(result.status, GateStatus::ReferencePassed);
        assert_eq!(provider.snapshot_calls.get(), 2);
        assert_eq!(provider.time_calls.get(), 2);
        assert!(!result.can_open_contact);
        assert_eq!(result.operative_authority, "NONE");
        assert!(!result.external_side_effect);
        Ok(())
    }

    #[test]
    fn untrusted_or_changed_snapshot_returns_hold() -> Result<(), Box<dyn Error>> {
        let fixture = Fixture::new()?;
        let trusted_key = SigningKey::from_bytes(&[92_u8; 32]);
        let other_key = SigningKey::from_bytes(&[93_u8; 32]);
        let trusted = sign_snapshot(fixture.snapshot.clone(), &trusted_key)?;
        let untrusted = sign_snapshot(fixture.snapshot.clone(), &other_key)?;
        let provider = TestSnapshotProvider::new(
            vec![Ok(trusted), Ok(untrusted)],
            vec![
                Ok("2030-01-01T00:04:56Z".to_owned()),
                Ok("2030-01-01T00:04:57Z".to_owned()),
            ],
        );
        let result = evaluate_from_provider(&fixture, &provider, &test_anchor(&trusted_key));
        assert_eq!(result.status, GateStatus::Hold);
        assert!(!result.can_open_contact);
        Ok(())
    }

    #[test]
    fn unavailable_snapshot_or_non_monotonic_clock_returns_hold() -> Result<(), Box<dyn Error>> {
        let fixture = Fixture::new()?;
        let key = SigningKey::from_bytes(&[94_u8; 32]);
        let signed = sign_snapshot(fixture.snapshot.clone(), &key)?;
        let unavailable = TestSnapshotProvider::new(
            vec![Err(SnapshotProviderError::Unavailable)],
            vec![
                Ok("2030-01-01T00:04:56Z".to_owned()),
                Ok("2030-01-01T00:04:57Z".to_owned()),
            ],
        );
        assert_eq!(
            evaluate_from_provider(&fixture, &unavailable, &test_anchor(&key)).status,
            GateStatus::Hold
        );
        let clock_reversed = TestSnapshotProvider::new(
            vec![Ok(signed.clone()), Ok(signed)],
            vec![
                Ok("2030-01-01T00:04:57Z".to_owned()),
                Ok("2030-01-01T00:04:56Z".to_owned()),
            ],
        );
        assert_eq!(
            evaluate_from_provider(&fixture, &clock_reversed, &test_anchor(&key)).status,
            GateStatus::Hold
        );
        Ok(())
    }
}
