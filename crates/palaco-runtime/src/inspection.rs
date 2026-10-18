//! Static inspection-interface capabilities, not host health or execution permission.

use std::io::{self, Write};

/// Descriptive inspection data, never evidence, permission or live host health.
///
/// Changing a local copy does not change the interface or authorize execution.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub struct InspectionStatus {
    /// Version of the inspection report contract, not production readiness.
    pub schema_version: u32,
    /// Package version of this runtime library.
    pub runtime_version: &'static str,
    /// Operating mode of the inspection interface.
    pub mode: &'static str,
    /// Whether this interface supplies an execution host.
    pub execution_host: &'static str,
    /// Whether this interface supplies an authority provider.
    pub authority_provider: &'static str,
    /// Whether service health has been checked.
    pub service_health: &'static str,
    /// External-effect policy of this interface, not the embedding application.
    pub external_effects: &'static str,
    /// Production-readiness assessment of this interface.
    pub production_readiness: &'static str,
}

impl InspectionStatus {
    fn fields(self) -> [(&'static str, &'static str); 6] {
        [
            ("mode", self.mode),
            ("execution_host", self.execution_host),
            ("authority_provider", self.authority_provider),
            ("service_health", self.service_health),
            ("external_effects", self.external_effects),
            ("production_readiness", self.production_readiness),
        ]
    }
}

/// Returns fixed inspection descriptors without I/O or host inspection.
///
/// This value describes only the inspection interface. It does not validate a
/// `RuntimePlan`, authenticate evidence or grant execution permission.
pub const fn status() -> InspectionStatus {
    InspectionStatus {
        schema_version: 1,
        runtime_version: env!("CARGO_PKG_VERSION"),
        mode: "local-inspection",
        execution_host: "unavailable",
        authority_provider: "unavailable",
        service_health: "not-checked",
        external_effects: "disabled",
        production_readiness: "not-assessed",
    }
}

/// Writes the inspection interface's text report, including a trailing newline.
///
/// Performs no health checks, authority validation or execution. Only writes to
/// the supplied destination; the caller owns flushing and persistence.
///
/// # Errors
///
/// Returns the destination's write error. Output may be partial on failure.
pub fn write_status(output: &mut (impl Write + ?Sized)) -> io::Result<()> {
    let report = status();
    writeln!(output, "PALACO runtime {}", report.runtime_version)?;
    for (key, value) in report.fields() {
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
    let report = status();
    write!(
        output,
        "{{\"schema_version\":{},\"runtime_version\":\"{}\"",
        report.schema_version, report.runtime_version
    )?;
    for (key, value) in report.fields() {
        write!(output, ",\"{key}\":\"{value}\"")?;
    }
    writeln!(output, "}}")
}
