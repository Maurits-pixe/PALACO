//! Synthetic, reference-only 6RI9ADE evidence gate.
//!
//! This module can verify signed evidence against a host-supplied trust snapshot.
//! It cannot authenticate that snapshot, open contact, grant authority, or cause
//! external effects. Production use requires an independently trusted snapshot
//! provider and separately reviewed identity, delivery, revocation, and consent
//! services.

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use chrono::{DateTime, SecondsFormat, Utc};
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const REQUEST_SCHEMA_V01: &str = "elixer-6ri9ade-request-v0.1";
pub const SNAPSHOT_SCHEMA_V01: &str = "elixer-6ri9ade-trust-snapshot-v0.1";
pub const EVIDENCE_SCHEMA_V01: &str = "elixer-6ri9ade-evidence-v0.1";
pub const RECEIPT_SCHEMA_V01: &str = "elixer-6ri9ade-human-receipt-v0.1";
const MAX_REQUEST_AGE_MS: i64 = 15 * 60 * 1_000;
const MAX_EVIDENCE_AGE_MS: i64 = 2 * 60 * 1_000;
const MAX_SNAPSHOT_AGE_MS: i64 = 30 * 1_000;
const GUARD_DOMAIN: &[u8] = b"6RI9ADE\0guard-evidence\0v0.1\0";
const RECEIPT_DOMAIN: &[u8] = b"6RI9ADE\0human-receipt\0v0.1\0";

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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceResult {
    Pass,
    Fail,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReceiptStage {
    Initiation,
    NovaAdmission,
    FinalConsent,
}

/// A synthetic request binds the check to both parties and a narrowly scoped
/// text-message intent. Timestamps use RFC 3339.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct RequestV01 {
    pub schema: String,
    pub request_id: String,
    pub sender_id: String,
    pub receiver_id: String,
    pub scope: String,
    pub context: String,
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
    pub external_side_effect: bool,
    pub trace_digest: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct Slot {
    side: Side,
    specialty: Specialty,
}

/// Evaluates a reference-only gate against two host snapshots. Both snapshots
/// must be identical and fresh, preventing a changed revocation/trust view
/// from silently passing during evaluation.
#[must_use]
pub fn evaluate(
    request: &RequestV01,
    initiation: &SignedEnvelopeV01,
    nova_admission: &SignedEnvelopeV01,
    evidence: &[SignedEnvelopeV01],
    final_receipts: &[SignedEnvelopeV01],
    initial_snapshot: &TrustSnapshotV01,
    final_snapshot: &TrustSnapshotV01,
    now: &str,
) -> GateResultV01 {
    let request_digest = digest_serializable(request).unwrap_or_default();
    let mut reasons = Vec::new();
    let mut checks = all_checks(CheckStatus::Hold);
    let now_ms = parse_time(now);

    let Some(now_ms) = now_ms else {
        reasons.push("INVALID_EVALUATION_TIME");
        return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
    };

    let Some(created_ms) = parse_time(&request.created_at) else {
        reasons.push("INVALID_REQUEST_TIME");
        return result(GateStatus::Stop, request_digest, checks, reasons, false, false, false, false);
    };
    let Some(request_expiry_ms) = parse_time(&request.expires_at) else {
        reasons.push("INVALID_REQUEST_TIME");
        return result(GateStatus::Stop, request_digest, checks, reasons, false, false, false, false);
    };
    if request.schema != REQUEST_SCHEMA_V01
        || request.request_id.is_empty()
        || request.sender_id.is_empty()
        || request.receiver_id.is_empty()
        || request.sender_id == request.receiver_id
        || request.scope != "chat:text"
        || request.context.is_empty()
        || created_ms > now_ms
        || request_expiry_ms <= now_ms
        || request_expiry_ms <= created_ms
        || request_expiry_ms - created_ms > MAX_REQUEST_AGE_MS
    {
        reasons.push("INVALID_OR_OUT_OF_SCOPE_REQUEST");
        return result(GateStatus::Stop, request_digest, checks, reasons, false, false, false, false);
    }

    if initial_snapshot != final_snapshot {
        reasons.push("TRUST_SNAPSHOT_CHANGED");
        return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
    }
    let snapshot = initial_snapshot;
    if snapshot.schema != SNAPSHOT_SCHEMA_V01
        || snapshot.request_digest != request_digest
        || snapshot.status != SnapshotStatus::Current
    {
        reasons.push("TRUST_SNAPSHOT_UNAVAILABLE");
        let status = if snapshot.status == SnapshotStatus::Stop { GateStatus::Stop } else { GateStatus::Hold };
        return result(status, request_digest, checks, reasons, false, false, false, false);
    }
    let Some(snapshot_captured_ms) = parse_time(&snapshot.captured_at) else {
        reasons.push("INVALID_TRUST_SNAPSHOT_TIME");
        return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
    };
    let Some(snapshot_expiry_ms) = parse_time(&snapshot.expires_at) else {
        reasons.push("INVALID_TRUST_SNAPSHOT_TIME");
        return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
    };
    if snapshot_captured_ms > now_ms
        || now_ms - snapshot_captured_ms > MAX_SNAPSHOT_AGE_MS
        || snapshot_expiry_ms <= now_ms
    {
        reasons.push("STALE_TRUST_SNAPSHOT");
        return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
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
            return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
        }
    };
    let initiation_digest = envelope_digest(initiation).unwrap_or_default();
    let Some(initiation_time) = parse_time(&initiation_body.issued_at) else {
        reasons.push("INVALID_INITIATION_TIME");
        return result(GateStatus::Hold, request_digest, checks, reasons, false, false, false, false);
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
            return result(GateStatus::Hold, request_digest, checks, reasons, true, false, false, false);
        }
    };
    let admission_digest = envelope_digest(nova_admission).unwrap_or_default();
    let Some(admission_time) = parse_time(&admission_body.issued_at) else {
        reasons.push("INVALID_ADMISSION_TIME");
        return result(GateStatus::Hold, request_digest, checks, reasons, true, false, false, false);
    };
    if admission_time <= initiation_time {
        reasons.push("ADMISSION_PRECEDES_INITIATION");
        return result(GateStatus::Stop, request_digest, checks, reasons, true, false, false, false);
    }

    if evidence.len() > 18 {
        reasons.push("UNEXPECTED_EVIDENCE_COUNT");
        return result(GateStatus::Stop, request_digest, checks, reasons, true, true, false, false);
    }
    let mut seen_slots = BTreeSet::new();
    let mut evidence_ids = BTreeSet::new();
    let mut evidence_invalid = false;
    let mut evidence_failed = false;
    let mut latest_evidence_ms = admission_time;
    let request_context_digest = digest_bytes(request.context.as_bytes());
    for envelope in evidence {
        let body = match parse_evidence_body(envelope) {
            Ok(body) => body,
            Err(()) => {
                evidence_invalid = true;
                continue;
            }
        };
        let slot = Slot { side: body.side, specialty: body.specialty };
        if !seen_slots.insert(slot) || !evidence_ids.insert(body.evidence_id.clone()) {
            evidence_invalid = true;
            continue;
        }
        let Some(issued_ms) = parse_time(&body.issued_at) else {
            evidence_invalid = true;
            continue;
        };
        let signature_valid = verify_evidence(envelope, &body, request, &request_digest, snapshot, now_ms);
        let time_valid = issued_ms > admission_time
            && body.expires_at.as_str() != ""
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
        return result(GateStatus::Stop, request_digest, checks, reasons, true, true, false, false);
    }
    if evidence_invalid {
        reasons.push("EVIDENCE_INVALID_OR_REVOKED");
        return result(GateStatus::Hold, request_digest, checks, reasons, true, true, false, false);
    }
    if seen_slots.len() != 18 {
        reasons.push("SPECIALTY_EVIDENCE_INCOMPLETE");
        return result(GateStatus::PendingEvidence, request_digest, checks, reasons, true, true, false, false);
    }
    if evidence.iter().any(|envelope| {
        parse_evidence_body(envelope).is_ok_and(|body| {
            body.context_digest != request_context_digest
        })
    }) {
        reasons.push("EVIDENCE_CONTEXT_MISMATCH");
        return result(GateStatus::Stop, request_digest, checks, reasons, true, true, false, false);
    }

    let evidence_digest = match evidence_set_digest(evidence) {
        Ok(digest) => digest,
        Err(()) => {
            reasons.push("EVIDENCE_DIGEST_INVALID");
            return result(GateStatus::Hold, request_digest, checks, reasons, true, true, false, false);
        }
    };
    if final_receipts.is_empty() {
        reasons.push("FINAL_CONSENT_PENDING");
        return result(GateStatus::PendingFinalConsent, request_digest, checks, reasons, true, true, false, false);
    }
    if final_receipts.len() != 2 {
        reasons.push("FINAL_CONSENT_RECEIPTS_INCOMPLETE");
        return result(GateStatus::Hold, request_digest, checks, reasons, true, true, false, false);
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
                return result(GateStatus::Hold, request_digest, checks, reasons, true, true, false, false);
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
            return result(GateStatus::Stop, request_digest, checks, reasons, true, true, false, false);
        }
    }
    if !final_participants.contains(&request.sender_id)
        || !final_participants.contains(&request.receiver_id)
    {
        reasons.push("BOTH_FINAL_CONSENTS_REQUIRED");
        return result(GateStatus::Hold, request_digest, checks, reasons, true, true, false, false);
    }

    reasons.push("REFERENCE_CHECKS_PASSED_NO_AUTHORITY_GRANTED");
    result(GateStatus::ReferencePassed, request_digest, checks, reasons, true, true, true, true)
}

/// Produces domain-separated signing bytes for synthetic fixtures and
/// independent test tooling.
pub fn guard_signing_bytes(body: &Value) -> Result<Vec<u8>, serde_json::Error> {
    signing_bytes(GUARD_DOMAIN, body)
}

/// Produces domain-separated signing bytes for synthetic human receipts.
pub fn receipt_signing_bytes(body: &Value) -> Result<Vec<u8>, serde_json::Error> {
    signing_bytes(RECEIPT_DOMAIN, body)
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
        && body.request_digest == request_digest
        && body.context_digest == digest_bytes(request.context.as_bytes())
        && issuer_for_evidence(snapshot, body, now_ms).is_some_and(|issuer| {
            !snapshot.revoked_issuer_ids.contains(&issuer.issuer_id)
                && verify_envelope(envelope, issuer, GUARD_DOMAIN)
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
    let body: HumanReceiptBodyV01 = serde_json::from_value(envelope.body.clone()).map_err(|_| ())?;
    if body.schema != RECEIPT_SCHEMA_V01
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
        || expiry - body_time > MAX_EVIDENCE_AGE_MS
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
    let issuer = snapshot.issuers.iter().find(|issuer| {
        issuer.participant_id == body.participant_id
            && issuer.side == side
            && issuer.specialty.is_none()
            && issuer.receipt_stages.contains(&stage)
            && issuer.valid_from.as_str() <= body.issued_at.as_str()
            && issuer.valid_until.as_str() >= body.expires_at.as_str()
            && !snapshot.revoked_issuer_ids.contains(&issuer.issuer_id)
    }).ok_or(())?;
    if !issuer_current(issuer, now_ms) || !verify_envelope(envelope, issuer, RECEIPT_DOMAIN) {
        return Err(());
    }
    Ok(body)
}

fn issuer_for_evidence<'a>(
    snapshot: &'a TrustSnapshotV01,
    body: &EvidenceBodyV01,
    now_ms: i64,
) -> Option<&'a TrustedIssuerV01> {
    snapshot.issuers.iter().find(|issuer| {
        issuer.side == body.side
            && issuer.specialty == Some(body.specialty)
            && issuer.receipt_stages.is_empty()
            && issuer.participant_id
                == if body.side == Side::Sender {
                    snapshot
                        .issuers
                        .iter()
                        .find(|candidate| candidate.side == Side::Sender && candidate.specialty.is_none())
                        .map_or("", |candidate| candidate.participant_id.as_str())
                } else {
                    snapshot
                        .issuers
                        .iter()
                        .find(|candidate| candidate.side == Side::Receiver && candidate.specialty.is_none())
                        .map_or("", |candidate| candidate.participant_id.as_str())
                }
            && issuer_current(issuer, now_ms)
            && issuer.valid_from.as_str() <= body.issued_at.as_str()
            && issuer.valid_until.as_str() >= body.expires_at.as_str()
    })
}

fn issuer_current(issuer: &TrustedIssuerV01, now_ms: i64) -> bool {
    parse_time(&issuer.valid_from).is_some_and(|time| time <= now_ms)
        && parse_time(&issuer.valid_until).is_some_and(|time| time > now_ms)
}

fn verify_envelope(
    envelope: &SignedEnvelopeV01,
    issuer: &TrustedIssuerV01,
    domain: &[u8],
) -> bool {
    if envelope.algorithm != "Ed25519" {
        return false;
    }
    let Ok(public_key_bytes) = URL_SAFE_NO_PAD.decode(&issuer.public_key) else {
        return false;
    };
    let Ok(public_key_array) = <[u8; 32]>::try_from(public_key_bytes.as_slice()) else {
        return false;
    };
    let Ok(public_key) = VerifyingKey::from_bytes(&public_key_array) else {
        return false;
    };
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
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => serde_json::to_vec(value),
        Value::Array(values) => {
            let mut output = Vec::from(b"[".as_slice());
            for (index, item) in values.iter().enumerate() {
                if index > 0 {
                    output.push(b',');
                }
                output.extend(canonical_json(item)?);
            }
            output.push(b']');
            Ok(output)
        }
        Value::Object(values) => {
            let sorted: BTreeMap<_, _> = values.iter().collect();
            let mut output = Vec::from(b"{".as_slice());
            for (index, (key, item)) in sorted.iter().enumerate() {
                if index > 0 {
                    output.push(b',');
                }
                output.extend(serde_json::to_vec(key)?);
                output.push(b':');
                output.extend(canonical_json(item)?);
            }
            output.push(b'}');
            Ok(output)
        }
    }
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
            Specialty::ALL.into_iter().map(move |specialty| SpecialtyCheck {
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
        external_side_effect: false,
        trace_digest,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn specialty_inventory_contains_nine_distinct_controls() {
        let unique: BTreeSet<_> = Specialty::ALL.into_iter().collect();
        assert_eq!(unique.len(), 9);
    }

    #[test]
    fn canonical_signing_bytes_ignore_object_insertion_order() -> Result<(), Box<dyn std::error::Error>> {
        let first: Value = serde_json::from_str(r#"{"z":1,"a":{"y":true,"b":"x"}}"#)?;
        let second: Value = serde_json::from_str(r#"{"a":{"b":"x","y":true},"z":1}"#)?;
        assert_eq!(guard_signing_bytes(&first)?, guard_signing_bytes(&second)?);
        Ok(())
    }
}
