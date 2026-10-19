//! Read-only plan inspection and static interface descriptors, never execution permission.

use crate::RuntimePlan;
use palaco_foundation::{ContractDisposition, ContractError, Validatable};
use std::io::{self, Write};

/// Observation of an existing plan, not an authorization receipt.
///
/// Contract validity and disposition are separate: a denied or held plan may
/// validate successfully. Neither field authenticates evidence or host authority.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub struct PlanInspection {
    /// Disposition already carried by the supplied plan.
    pub disposition: ContractDisposition,
    /// Result of the plan's existing `Validatable` implementation.
    pub validation: Result<(), ContractError>,
}

/// Observes a plan without changing it, executing it or performing I/O.
///
/// Validation delegates to the existing contract chain; it is not independent
/// evidence authentication, authority refresh or a live revocation check.
/// Even `Execute` plus `Ok(())` does not supply an execution host or a new
/// permission. The report contains no evidence identifiers.
#[must_use]
pub fn inspect_plan(plan: &RuntimePlan) -> PlanInspection {
    PlanInspection {
        disposition: plan.disposition(),
        validation: plan.validate(),
    }
}

/// Writes one schema-version-1 plan-inspection JSON object and a newline.
///
/// Observes the supplied plan directly, never a caller-modified report copy.
/// Only fixed descriptors are serialized; evidence identifiers are excluded.
/// `contract_valid` records validation success, not execution permission:
/// held and denied plans may be valid. No execution or independent authority
/// verification is performed. This is not an authorization receipt.
///
/// The caller owns flushing and persistence. For validation error details, use
/// [`inspect_plan`] instead. The status-JSON contract is unaffected.
///
/// # Errors
///
/// Returns the destination's write error; output may be partial on failure.
/// Contract validation failure is represented by `contract_valid: false`, not
/// an I/O error.
pub fn write_plan_inspection_json(
    plan: &RuntimePlan,
    output: &mut (impl Write + ?Sized),
) -> io::Result<()> {
    let report = inspect_plan(plan);
    let disposition = match report.disposition {
        ContractDisposition::Execute => "execute",
        ContractDisposition::Hold => "hold",
        ContractDisposition::Deny => "deny",
    };
    writeln!(
        output,
        "{{\"schema_version\":1,\"report_type\":\"plan-inspection\",\"disposition\":\"{disposition}\",\"contract_valid\":{},\"execution_performed\":false,\"authority_verified\":false}}",
        report.validation.is_ok()
    )
}

/// Writes plan observations in iterator order as JSON Lines.
///
/// Delegates each borrowed plan to [`write_plan_inspection_json`] without
/// collecting plans or reports. Empty input writes nothing. The caller supplies
/// a finite iterator and owns flushing and persistence. Iterator side effects
/// belong to the caller; this function does not execute plans or verify authority.
///
/// # Errors
///
/// Stops on the first write error without requesting the next plan. The failing
/// plan has already been consumed from the iterator. Output is not atomic:
/// previous lines and a partial final line may remain, even on error.
/// Success does not imply that a buffered destination was flushed.
pub fn write_plan_inspections_jsonl<'a>(
    plans: impl IntoIterator<Item = &'a RuntimePlan>,
    output: &mut (impl Write + ?Sized),
) -> io::Result<()> {
    for plan in plans {
        write_plan_inspection_json(plan, output)?;
    }
    Ok(())
}

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
///
/// # Examples
///
/// Read descriptors directly without parsing a report or inspecting the host:
///
/// ```
/// use palaco_runtime::inspection::{status, InspectionStatus};
///
/// const REPORT: InspectionStatus = status();
/// assert_eq!(REPORT.schema_version, 1);
/// assert_eq!(REPORT.mode, "local-inspection");
/// assert_eq!(REPORT.execution_host, "unavailable");
/// assert_eq!(REPORT.authority_provider, "unavailable");
/// ```
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
///
/// # Examples
///
/// Flush a caller-owned buffer explicitly and propagate both write and flush
/// errors before consuming the complete result:
///
/// ```
/// use palaco_runtime::inspection::write_status;
/// use std::io::{self, BufWriter, Write};
///
/// let mut bytes = Vec::new();
/// {
///     let mut output = BufWriter::new(&mut bytes);
///     write_status(&mut output)?;
///     output.flush()?;
/// }
/// assert!(bytes.starts_with(b"PALACO runtime "));
/// assert!(bytes.ends_with(b"production_readiness=not-assessed\n"));
/// # Ok::<(), io::Error>(())
/// ```
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
///
/// # Examples
///
/// A caller may use a fixed-size destination instead of allocating a buffer.
/// An undersized slice fails with `WriteZero`; discard its partial report:
///
/// ```
/// use palaco_runtime::inspection::write_status_json;
/// use std::io;
///
/// let mut storage = [0_u8; 4096];
/// let capacity = storage.len();
/// let mut destination = &mut storage[..];
/// write_status_json(&mut destination)?;
/// let used = capacity - destination.len();
/// assert!(storage[..used].starts_with(b"{\"schema_version\":1,"));
/// assert!(storage[..used].ends_with(b"}\n"));
///
/// let mut too_small = [0_u8; 8];
/// let error = write_status_json(&mut &mut too_small[..])
///     .expect_err("a partial report must not be treated as success");
/// assert_eq!(error.kind(), io::ErrorKind::WriteZero);
/// # Ok::<(), io::Error>(())
/// ```
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
