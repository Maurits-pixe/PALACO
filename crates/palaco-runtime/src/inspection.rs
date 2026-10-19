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

/// Counts of plan observations, never execution or authorization statistics.
///
/// Validation and disposition are independent. A valid contract may still have
/// Hold or Deny disposition. Public copies are descriptive data only.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
#[non_exhaustive]
pub struct PlanInspectionSummary {
    /// Number of slice entries observed, including repeated plans.
    pub total: usize,
    /// Entries carrying Execute, not a count of executed or authenticated plans.
    pub execute: usize,
    /// Entries carrying Hold.
    pub hold: usize,
    /// Entries carrying Deny.
    pub deny: usize,
    /// Entries whose existing contract validation succeeded.
    pub contract_valid: usize,
    /// Entries whose existing contract validation failed.
    pub contract_invalid: usize,
}

impl PlanInspectionSummary {
    /// Adds observation counts field by field, returning `None` on any overflow.
    ///
    /// Allows callers to combine finite chunk summaries without collecting all
    /// plans. Overlapping chunks count observations again; no deduplication,
    /// authentication or consistency validation of public fields is performed.
    /// Inputs are unchanged on success or failure. No execution permission is
    /// granted, and existing JSON writers still inspect plans directly.
    #[must_use]
    pub fn checked_add(self, other: Self) -> Option<Self> {
        Some(Self {
            total: self.total.checked_add(other.total)?,
            execute: self.execute.checked_add(other.execute)?,
            hold: self.hold.checked_add(other.hold)?,
            deny: self.deny.checked_add(other.deny)?,
            contract_valid: self.contract_valid.checked_add(other.contract_valid)?,
            contract_invalid: self.contract_invalid.checked_add(other.contract_invalid)?,
        })
    }
}

/// Summarizes a finite slice without modifying plans, allocating or performing I/O.
///
/// Each entry is inspected once using [`inspect_plan`]. Repeated entries count
/// separately. All counters are bounded by the slice length. No evidence is
/// authenticated, authority refreshed or execution performed. This is not an
/// atomic observation of external authority and grants no permission.
#[must_use]
pub fn summarize_plans(plans: &[RuntimePlan]) -> PlanInspectionSummary {
    let mut summary = PlanInspectionSummary {
        total: plans.len(),
        ..PlanInspectionSummary::default()
    };
    for plan in plans {
        let report = inspect_plan(plan);
        match report.disposition {
            ContractDisposition::Execute => summary.execute += 1,
            ContractDisposition::Hold => summary.hold += 1,
            ContractDisposition::Deny => summary.deny += 1,
        }
        if report.validation.is_ok() {
            summary.contract_valid += 1;
        } else {
            summary.contract_invalid += 1;
        }
    }
    summary
}

/// Writes one schema-version-1 plan-inspection-summary JSON object and a newline.
///
/// Summarizes the supplied slice directly using [`summarize_plans`], never a
/// caller-modified summary. Empty input emits a report with zero counts.
/// Counts describe observations, not executions or independently verified
/// authority. Only fixed descriptors and counts are serialized, not evidence
/// identifiers. Existing per-plan and status JSON contracts are unchanged.
///
/// The caller owns flushing and persistence; success does not imply a buffered
/// destination was flushed.
///
/// # Errors
///
/// Returns the destination's write error; output may be partial on failure.
/// Contract validation failures are counted, not returned as I/O errors.
pub fn write_plan_inspection_summary_json(
    plans: &[RuntimePlan],
    output: &mut (impl Write + ?Sized),
) -> io::Result<()> {
    let summary = summarize_plans(plans);
    writeln!(
        output,
        "{{\"schema_version\":1,\"report_type\":\"plan-inspection-summary\",\"total\":{},\"execute\":{},\"hold\":{},\"deny\":{},\"contract_valid\":{},\"contract_invalid\":{},\"execution_performed\":false,\"authority_verified\":false}}",
        summary.total,
        summary.execute,
        summary.hold,
        summary.deny,
        summary.contract_valid,
        summary.contract_invalid,
    )
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
/// Standard `Interrupted` writes are retried; a zero-byte write becomes
/// `WriteZero`. A buffer may accept all reports before an underlying error is
/// detected during a later caller-owned flush, after all plans were consumed.
pub fn write_plan_inspections_jsonl<'a>(
    plans: impl IntoIterator<Item = &'a RuntimePlan>,
    output: &mut (impl Write + ?Sized),
) -> io::Result<()> {
    for plan in plans {
        write_plan_inspection_json(plan, output)?;
    }
    Ok(())
}

/// Failure of a fallible plan source or its report destination.
///
/// The original errors remain available to the caller; neither is serialized.
#[derive(Debug)]
pub enum PlanInspectionWriteError<E> {
    /// The source could not supply a plan.
    Source(E),
    /// Writing the current plan's report failed.
    Output(io::Error),
}

impl<E> std::fmt::Display for PlanInspectionWriteError<E> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::Source(_) => "plan inspection source failed",
            Self::Output(_) => "plan inspection output failed",
        })
    }
}

impl<E: std::error::Error + 'static> std::error::Error for PlanInspectionWriteError<E> {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Source(error) => Some(error),
            Self::Output(error) => Some(error),
        }
    }
}

/// Writes JSON Lines from a finite, fallible source without skipping errors.
///
/// Like [`write_plan_inspections_jsonl`], this neither collects nor flushes.
/// The iterator may perform caller-owned I/O; no plan is executed or authorized.
///
/// # Errors
///
/// Returns the first source or output error without requesting the next item.
/// The failing item is consumed. Source errors write no report for that item;
/// output errors may leave a partial line. Earlier lines are not rolled back.
/// Errors are returned, never serialized into the report stream. Their `Debug`
/// representation and error chain may contain caller-provided sensitive data.
/// Success still requires a caller-owned flush for buffered destinations.
/// On source failure, earlier reports may remain in a caller-owned buffer.
/// Dropping a `BufWriter` may still write those bytes. Use its `into_parts` to
/// recover and discard pending bytes without flushing; bytes already delivered
/// to the underlying destination cannot be retracted.
pub fn try_write_plan_inspections_jsonl<'a, E>(
    plans: impl IntoIterator<Item = Result<&'a RuntimePlan, E>>,
    output: &mut (impl Write + ?Sized),
) -> Result<(), PlanInspectionWriteError<E>> {
    for plan in plans {
        let plan = plan.map_err(PlanInspectionWriteError::Source)?;
        write_plan_inspection_json(plan, output).map_err(PlanInspectionWriteError::Output)?;
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
