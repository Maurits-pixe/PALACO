use rio_accounts::endpoint_policy::ENDPOINT_DOCUMENT_LIMIT;
use serde_json::{Value, json};
use std::{
    ffi::OsString,
    io::Write,
    process::{Command, Output, Stdio},
};

const CANARY: &str = "private-endpoint-canary";
const FLAG: &str = "--check-staging-endpoints";
const REJECTED: &[u8] = b"RIO staging endpoint component rejected.\n";

fn document() -> Value {
    let issuer = format!("https://identity-{CANARY}.example.invalid/realms/rio-synthetic-staging");
    json!({
        "bffOrigin": format!("https://rio-{CANARY}.example.invalid"),
        "idpIssuer": issuer,
        "callbackUrl": format!("https://rio-{CANARY}.example.invalid/auth/callback"),
        "discoveryUrl": format!("{issuer}/.well-known/openid-configuration"),
        "authorizationUrl": format!("{issuer}/protocol/openid-connect/auth"),
        "tokenUrl": format!("{issuer}/protocol/openid-connect/token"),
        "jwksUrl": format!("{issuer}/protocol/openid-connect/certs"),
    })
}

fn invoke(input: &[u8], arguments: &[OsString], poisoned_environment: bool) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_rio-accounts-dev"));
    command.env_clear().args(arguments);
    if poisoned_environment {
        for key in [
            "RIO_DEV_MODE",
            "RIO_DEV_CLIENT_SECRET",
            "RIO_DEV_TLS_CERT",
            "RIO_DEV_TLS_KEY",
            "RIO_DEV_DATABASE_URL",
        ] {
            command.env(key, CANARY);
        }
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("checker process must start");
    child
        .stdin
        .take()
        .expect("piped stdin")
        .write_all(input)
        .expect("bounded test input");
    child.wait_with_output().expect("checker must finish")
}

fn expected_summary() -> Value {
    json!({
        "schemaVersion": "RIO_STAGING_ENDPOINT_COMPONENT_V1", "mode": "PLAN_ONLY",
        "checks": {
            "networkProbesPerformed": false, "dnsVerified": false, "tlsVerified": false,
            "providerMetadataVerified": false, "sourceVerified": false, "artifactDigestsVerified": false
        },
        "boundary": {
            "launchSupported": false, "deployAllowed": false, "account1": "HOLD",
            "humanAcceptance": "HOLD", "personalAccounts": false, "publicRegistration": false,
            "contact": false, "operativeAuthority": "NONE", "deployment": "HOLD"
        }
    })
}

fn assert_rejected(input: &[u8]) {
    let output = invoke(input, &[OsString::from(FLAG)], true);
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, REJECTED);
}

#[test]
fn actual_checker_works_without_runtime_configuration_and_keeps_all_authority_closed() {
    for poisoned in [false, true] {
        let output = invoke(
            document().to_string().as_bytes(),
            &[OsString::from(FLAG)],
            poisoned,
        );
        assert!(output.status.success());
        assert!(output.stderr.is_empty());
        assert_eq!(
            serde_json::from_slice::<Value>(&output.stdout).expect("summary JSON"),
            expected_summary()
        );
        assert!(!String::from_utf8_lossy(&output.stdout).contains(CANARY));
        assert!(output.stdout.ends_with(b"\n"));
    }
}

#[test]
fn actual_checker_rejects_malformed_duplicate_unknown_and_private_fields_without_echoing() {
    for input in [
        b"".as_slice(),
        b"{",
        b"null",
        b"[]",
        b"\xff",
        CANARY.as_bytes(),
    ] {
        assert_rejected(input);
    }
    let mut unknown = document();
    unknown["clientSecret"] = json!(CANARY);
    assert_rejected(unknown.to_string().as_bytes());
    let mut missing = document();
    missing.as_object_mut().expect("object").remove("jwksUrl");
    assert_rejected(missing.to_string().as_bytes());
    let raw = document().to_string();
    let duplicate = format!("{},\"bffOrigin\":\"{CANARY}\"}}", &raw[..raw.len() - 1]);
    assert_rejected(duplicate.as_bytes());
}

#[test]
fn actual_checker_rejects_cross_provider_callback_and_noncanonical_origin_substitutions() {
    for (key, value) in [
        ("bffOrigin", "http://rio.example.invalid"),
        ("bffOrigin", "https://rio.example.invalid:443"),
        ("bffOrigin", "https://localhost"),
        (
            "callbackUrl",
            "https://foreign.example.invalid/auth/callback",
        ),
        ("tokenUrl", "https://foreign.example.invalid/token"),
        ("idpIssuer", "https://identity.example.invalid/realms/other"),
    ] {
        let mut invalid = document();
        invalid[key] = json!(value);
        assert_rejected(invalid.to_string().as_bytes());
    }
}

#[test]
fn actual_checker_applies_the_byte_limit_including_whitespace() {
    let mut input = document().to_string().into_bytes();
    input.resize(ENDPOINT_DOCUMENT_LIMIT, b' ');
    let output = invoke(&input, &[OsString::from(FLAG)], false);
    assert!(output.status.success());
    assert_eq!(
        serde_json::from_slice::<Value>(&output.stdout).expect("summary JSON"),
        expected_summary()
    );
    input.push(b' ');
    assert_rejected(&input);
}

#[test]
fn checker_rejects_extra_arguments_without_echoing_or_starting_the_service() {
    for extra in [CANARY, "--recovery-fence", "--serve"] {
        let output = invoke(b"", &[OsString::from(FLAG), OsString::from(extra)], true);
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert_eq!(output.stderr, REJECTED);
    }
}

#[cfg(unix)]
#[test]
fn non_utf8_arguments_cannot_panic_and_disclose_submitted_bytes() {
    use std::os::unix::ffi::OsStringExt;
    let argument = OsString::from_vec([CANARY.as_bytes(), b"\xff"].concat());
    let output = invoke(b"", &[OsString::from(FLAG), argument], true);
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, REJECTED);
}
