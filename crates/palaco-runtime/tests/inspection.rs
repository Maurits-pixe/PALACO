use palaco_runtime::inspection::{InspectionStatus, status, write_status, write_status_json};
use std::io::{self, Write};

#[test]
fn typed_status_describes_only_the_inspection_interface() {
    const REPORT: InspectionStatus = status();
    assert_eq!(REPORT.schema_version, 1);
    assert_eq!(REPORT.runtime_version, env!("CARGO_PKG_VERSION"));
    assert_eq!(REPORT.mode, "local-inspection");
    assert_eq!(REPORT.execution_host, "unavailable");
    assert_eq!(REPORT.authority_provider, "unavailable");
    assert_eq!(REPORT.service_health, "not-checked");
    assert_eq!(REPORT.external_effects, "disabled");
    assert_eq!(REPORT.production_readiness, "not-assessed");
}

#[test]
fn changing_a_snapshot_does_not_change_future_reports() -> io::Result<()> {
    let original = status();
    let mut text_before = Vec::new();
    let mut json_before = Vec::new();
    write_status(&mut text_before)?;
    write_status_json(&mut json_before)?;

    let mut local = original;
    local.mode = "caller-modified";
    local.schema_version = 99;
    assert_ne!(local, original);
    assert_eq!(status(), original);

    let mut text_after = Vec::new();
    let mut json_after = Vec::new();
    write_status(&mut text_after)?;
    write_status_json(&mut json_after)?;
    assert_eq!(text_before, text_after);
    assert_eq!(json_before, json_after);
    Ok(())
}

struct Destination {
    bytes: Vec<u8>,
    remaining: usize,
}

impl Write for Destination {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return Err(io::Error::from(io::ErrorKind::PermissionDenied));
        }
        let count = bytes.len().min(self.remaining).min(3);
        self.bytes.extend_from_slice(&bytes[..count]);
        self.remaining -= count;
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        panic!("inspection API must leave flushing to its caller");
    }
}

#[test]
fn short_writes_produce_the_complete_report_without_flushing() -> io::Result<()> {
    for json in [false, true] {
        let mut expected = Vec::new();
        let mut destination = Destination {
            bytes: Vec::new(),
            remaining: usize::MAX,
        };
        if json {
            write_status_json(&mut expected)?;
            write_status_json(&mut destination)?;
        } else {
            write_status(&mut expected)?;
            write_status(&mut destination)?;
        }
        assert_eq!(destination.bytes, expected);
    }
    Ok(())
}

#[test]
fn write_failures_propagate_before_and_after_partial_output() {
    for json in [false, true] {
        for remaining in [0, 10] {
            let mut destination = Destination {
                bytes: Vec::new(),
                remaining,
            };
            let result = if json {
                write_status_json(&mut destination)
            } else {
                write_status(&mut destination)
            };
            assert_eq!(
                result.expect_err("destination must fail").kind(),
                io::ErrorKind::PermissionDenied
            );
            assert_eq!(destination.bytes.len(), remaining);
        }
    }
}

#[test]
fn trait_object_destinations_are_supported() -> io::Result<()> {
    let mut text = Vec::new();
    let mut json = Vec::new();
    write_status(&mut text as &mut dyn Write)?;
    write_status_json(&mut json as &mut dyn Write)?;
    assert!(text.starts_with(b"PALACO runtime "));
    assert!(json.starts_with(b"{\"schema_version\":1,"));
    Ok(())
}
