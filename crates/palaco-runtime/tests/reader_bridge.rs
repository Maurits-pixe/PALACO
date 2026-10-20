//! End-to-end fixture: actual Python pinned reader -> bytes -> Rust BG05 -> HOLD.

use std::{path::Path, process::Command};

use palaco_runtime::brigade_staging::{
    AdapterError, Binding, Checkpoint, ClockSample, Coverage, Finding, Mode, Observation,
    ObservationAdapter, Party, Registration, Role, evaluate, key_registry::KeyRegistryAdapter,
};

const PYTHON_FIXTURE: &str = r#"
import hashlib, json, pathlib, runpy, sys, tempfile, time
reader = runpy.run_path(sys.argv[1])
now = int(time.time())
snapshot = {
    "schema": reader["SCHEMA"], "revision": "fixture-r1", "mode": sys.argv[2],
    "issued_at": now, "expires_at": now + 60,
    "records": [{
        "tenant": "tenant", "actor": "actor", "device": "device",
        "key_ref": "key", "epoch": 1, "valid_from": now, "expires_at": now + 60,
        "revoked": sys.argv[3] == "1",
    }],
}
with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / "register.json"
    raw = json.dumps(snapshot).encode()
    path.write_bytes(raw)
    sys.stdout.buffer.write(reader["read_bridge"](
        str(path), hashlib.sha256(raw).hexdigest(), "fixture-r1", sys.argv[2],
    ))
"#;

struct Captured(Observation);

impl ObservationAdapter for Captured {
    fn observe(&self, _: &Binding) -> Result<Observation, AdapterError> {
        Ok(self.0.clone())
    }
}

#[test]
fn real_reader_exports_both_modes_and_revocation_without_authority() {
    let reader = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../verification/brigade-staging/register_reader.py");
    let binding = Binding {
        challenge: "fixture-challenge".into(),
        contract_digest: "fixture-digest".into(),
        sender: "actor".into(),
        recipient: "recipient".into(),
        sender_device: "device".into(),
        recipient_device: "other-device".into(),
        tenant_context: "tenant".into(),
        policy_version: "policy".into(),
        key_epoch: 1,
        checkpoint: Checkpoint::ServiceCommit,
    };
    for (mode_name, mode) in [
        ("Synthetic", Mode::Synthetic),
        ("LocalObservation", Mode::LocalObservation),
    ] {
        for revoked in [false, true] {
            let output = Command::new("python3")
                .args(["-I", "-c", PYTHON_FIXTURE])
                .arg(&reader)
                .arg(mode_name)
                .arg(if revoked { "1" } else { "0" })
                .output()
                .expect("Python 3.11+ is required for the reader integration test");
            assert!(output.status.success(), "Python fixture reader failed");
            let adapter = KeyRegistryAdapter::from_reader_bytes(
                &output.stdout,
                "fixture-r1",
                mode,
                &binding,
                "key",
            )
            .expect("unverified bridge import");
            let finding = if revoked {
                Finding::Negative
            } else {
                Finding::Positive
            };
            let observation = adapter.observe(&binding).expect("fresh record");
            assert_eq!(observation.finding, finding);
            let clock = ClockSample {
                unix_seconds: observation.issued_at,
            };
            let captured = Captured(observation);
            let report = evaluate(
                mode,
                &binding,
                Ok(clock),
                &[Registration {
                    role: Role::Bg05,
                    party: Party::Sender,
                    adapter: &captured,
                }],
            );
            assert_eq!(report.controls[4].coverage, Coverage::Unverified(finding));
            assert_eq!(
                report
                    .controls
                    .iter()
                    .filter(|c| c.coverage == Coverage::Unknown)
                    .count(),
                17
            );
            assert_eq!(report.disposition(), "HOLD");
            assert_eq!(report.operative_authority(), "NONE");
            assert!(!report.can_open_contact());
            assert!(!report.runtime_connected());
            assert!(!report.external_side_effect());
            let other_mode = if mode == Mode::Synthetic {
                Mode::LocalObservation
            } else {
                Mode::Synthetic
            };
            assert!(
                KeyRegistryAdapter::from_reader_bytes(
                    &output.stdout,
                    "fixture-r1",
                    other_mode,
                    &binding,
                    "key",
                )
                .is_err()
            );
        }
    }
}
