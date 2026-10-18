//! Static inspection-interface capabilities, not host health or execution permission.

use std::io::{self, Write};

const FIELDS: [(&str, &str); 6] = [
    ("mode", "local-inspection"),
    ("execution_host", "unavailable"),
    ("authority_provider", "unavailable"),
    ("service_health", "not-checked"),
    ("external_effects", "disabled"),
    ("production_readiness", "not-assessed"),
];

/// Writes the inspection interface's text report, including a trailing newline.
///
/// Performs no health checks, authority validation or execution. Only writes to
/// the supplied destination; the caller owns flushing and persistence.
///
/// # Errors
///
/// Returns the destination's write error. Output may be partial on failure.
pub fn write_status(output: &mut (impl Write + ?Sized)) -> io::Result<()> {
    writeln!(output, "PALACO runtime {}", env!("CARGO_PKG_VERSION"))?;
    for (key, value) in FIELDS {
        writeln!(output, "{key}={value}")?;
    }
    Ok(())
}

/// Writes the schema-version-1 inspection JSON object and a trailing newline.
///
/// Values are fixed inspection-interface descriptors, never caller-provided
/// evidence or authorization. The caller owns flushing and persistence.
///
/// # Errors
///
/// Returns the destination's write error. Output may be partial on failure.
pub fn write_status_json(output: &mut (impl Write + ?Sized)) -> io::Result<()> {
    write!(
        output,
        "{{\"schema_version\":1,\"runtime_version\":\"{}\"",
        env!("CARGO_PKG_VERSION")
    )?;
    for (key, value) in FIELDS {
        write!(output, ",\"{key}\":\"{value}\"")?;
    }
    writeln!(output, "}}")
}
