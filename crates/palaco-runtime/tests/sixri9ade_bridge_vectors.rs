use base64::{Engine, engine::general_purpose::STANDARD};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use palaco_runtime::sixri9ade::{
    SignedEnvelopeV01, guard_signing_bytes, reference_canonical_json, reference_digest,
};
use serde::Deserialize;
use serde_json::Value;
use std::error::Error;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Vector {
    schema: String,
    classification: String,
    domain: String,
    seed_hex: String,
    public_key_pem: String,
    body: Value,
    canonical_body: String,
    signing_bytes_hex: String,
    signature: String,
    envelope_digest: String,
}

#[test]
fn matches_node_reference_canonicalization_signature_and_envelope_digest()
-> Result<(), Box<dyn Error>> {
    let vector: Vector =
        serde_json::from_str(include_str!("vectors/6ri9ade-node-reference-v0.1.json"))?;
    assert_eq!(vector.schema, "6ri9ade-cross-language-signing-vector-v0.1");
    assert_eq!(vector.classification, "SYNTHETIC_TEST_ONLY");
    assert_eq!(vector.domain, REFERENCE_DOMAIN);

    let canonical = reference_canonical_json(&vector.body)?;
    assert_eq!(canonical, vector.canonical_body);
    let signing_bytes = guard_signing_bytes(&vector.body)?;
    assert_eq!(hex_encode(&signing_bytes), vector.signing_bytes_hex);
    assert!(signing_bytes.starts_with(vector.domain.as_bytes()));
    let seed: [u8; 32] = hex_decode(&vector.seed_hex)?
        .try_into()
        .map_err(|_| "test seed must contain 32 bytes")?;
    let signing_key = SigningKey::from_bytes(&seed);
    assert_eq!(
        base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode(signing_key.sign(&signing_bytes).to_bytes()),
        vector.signature
    );

    let pem_body = vector
        .public_key_pem
        .lines()
        .filter(|line| !line.starts_with("-----"))
        .collect::<String>();
    let der = STANDARD.decode(pem_body)?;
    let public_key_bytes: [u8; 32] = der
        .get(der.len().saturating_sub(32)..)
        .ok_or("public key is too short")?
        .try_into()?;
    let public_key = VerifyingKey::from_bytes(&public_key_bytes)?;
    let signature_bytes =
        base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(&vector.signature)?;
    let signature = Signature::from_slice(&signature_bytes)?;
    public_key.verify(&signing_bytes, &signature)?;

    let envelope = SignedEnvelopeV01 {
        algorithm: "Ed25519".to_owned(),
        body: vector.body,
        signature: vector.signature,
    };
    assert_eq!(
        reference_digest(&serde_json::to_value(envelope)?)?,
        vector.envelope_digest
    );
    Ok(())
}

const REFERENCE_DOMAIN: &str = "PALACO/6RI9ADE/REFERENCE-EVIDENCE/v0.1\0";

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn hex_decode(value: &str) -> Result<Vec<u8>, Box<dyn Error>> {
    let (pairs, remainder) = value.as_bytes().as_chunks::<2>();
    if !remainder.is_empty() {
        return Err("odd-length hexadecimal value".into());
    }
    pairs
        .iter()
        .map(|pair| {
            let digits = std::str::from_utf8(pair)?;
            Ok(u8::from_str_radix(digits, 16)?)
        })
        .collect()
}
