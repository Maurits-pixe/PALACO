//! Synthetic inspection fixtures only: no evidence authentication or execution.

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    inspection::{try_write_plan_inspection_summary_json, try_write_plan_inspections_jsonl},
};
use std::ffi::OsString;
use std::io::{self, BufWriter, Write};

fn summary_mode(args: impl IntoIterator<Item = OsString>) -> Result<bool, &'static str> {
    let mut args = args.into_iter();
    match (args.next(), args.next()) {
        (None, None) => Ok(false),
        (Some(arg), None) if arg == "--summary" => Ok(true),
        _ => Err("usage: synthetic_plan_inspection [--summary]"),
    }
}

fn write_demo(output: &mut impl Write, summary: bool) -> Result<(), Box<dyn std::error::Error>> {
    let plans = [
        AuthorityState::Authorized,
        AuthorityState::Revoked,
        AuthorityState::Expired,
        AuthorityState::InDoubt,
    ]
    .into_iter()
    .map(|authority| {
        let evidence = EvidenceRef::new("SYNTHETIC-DEMO-NOT-AUTHENTICATED")?;
        let event = EventEnvelope::new("synthetic.inspection.only", evidence);
        let record = ProvenanceRecord::new(event, authority);
        Ok(RuntimePlan::new(ExecutionBoundary::new(record)))
    })
    .collect::<Result<Vec<_>, ContractError>>()?;
    write_reports(plans.iter().map(Ok), output, summary)
}

fn write_reports<'a>(
    source: impl IntoIterator<Item = Result<&'a RuntimePlan, ContractError>>,
    output: &mut impl Write,
    summary: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if summary {
        try_write_plan_inspection_summary_json(source, output)?;
    } else {
        try_write_plan_inspections_jsonl(source, output)?;
    }
    output.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let summary = summary_mode(std::env::args_os().skip(1))?;
    let mut output = BufWriter::new(io::stdout().lock());
    write_demo(&mut output, summary)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_emits_exactly_four_synthetic_reports() -> Result<(), Box<dyn std::error::Error>> {
        let mut output = Vec::new();
        write_demo(&mut output, false)?;
        let expected: String = ["execute", "deny", "deny", "hold"]
            .into_iter()
            .map(|disposition| {
                format!(
                    "{{\"schema_version\":1,\"report_type\":\"plan-inspection\",\"disposition\":\"{disposition}\",\"contract_valid\":true,\"execution_performed\":false,\"authority_verified\":false}}\n"
                )
            })
            .collect();
        assert_eq!(output, expected.as_bytes());
        Ok(())
    }

    #[test]
    fn demo_summary_emits_one_observation_report() -> Result<(), Box<dyn std::error::Error>> {
        let mut output = Vec::new();
        write_demo(&mut output, true)?;
        assert_eq!(
            output,
            b"{\"schema_version\":1,\"report_type\":\"plan-inspection-summary\",\"total\":4,\"execute\":1,\"hold\":1,\"deny\":2,\"contract_valid\":4,\"contract_invalid\":0,\"execution_performed\":false,\"authority_verified\":false}\n"
        );
        Ok(())
    }

    #[test]
    fn source_failure_preserves_only_streamed_reports_without_flush_or_read_ahead()
    -> Result<(), Box<dyn std::error::Error>> {
        use palaco_runtime::inspection::{
            PlanInspectionSummaryWriteError, PlanInspectionWriteError, write_plan_inspection_json,
        };

        struct Destination(Vec<u8>);
        impl Write for Destination {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                self.0.extend_from_slice(bytes);
                Ok(bytes.len())
            }
            fn flush(&mut self) -> io::Result<()> {
                panic!("source failure must return before flush");
            }
        }

        let event = EventEnvelope::new("synthetic.source.failure", EvidenceRef::new("SYNTHETIC")?);
        let plan = RuntimePlan::new(ExecutionBoundary::new(ProvenanceRecord::new(
            event,
            AuthorityState::Authorized,
        )));
        let original = plan.clone();
        for summary in [false, true] {
            for completed in [0, 1] {
                let mut source = std::iter::repeat_n(Ok(&plan), completed)
                    .chain([Err(ContractError::MissingEvidence), Ok(&plan)]);
                let mut output = Destination(Vec::new());
                let error = write_reports(&mut source, &mut output, summary)
                    .expect_err("synthetic source must fail");
                if summary {
                    assert!(matches!(
                        error.downcast_ref::<PlanInspectionSummaryWriteError<ContractError>>(),
                        Some(PlanInspectionSummaryWriteError::Source(
                            ContractError::MissingEvidence
                        ))
                    ));
                } else {
                    assert!(matches!(
                        error.downcast_ref::<PlanInspectionWriteError<ContractError>>(),
                        Some(PlanInspectionWriteError::Source(
                            ContractError::MissingEvidence
                        ))
                    ));
                }
                let mut expected = Vec::new();
                if !summary && completed == 1 {
                    write_plan_inspection_json(&plan, &mut expected)?;
                }
                assert_eq!(output.0, expected);
                assert!(matches!(source.next(), Some(Ok(next)) if std::ptr::eq(next, &plan)));
            }
        }
        assert_eq!(plan, original);
        Ok(())
    }

    #[test]
    fn example_accepts_only_default_or_one_summary_flag() {
        assert_eq!(summary_mode([]), Ok(false));
        assert_eq!(summary_mode([OsString::from("--summary")]), Ok(true));
        for args in [
            vec![""],
            vec!["summary"],
            vec!["--unknown"],
            vec!["--summary", "--summary"],
            vec!["--summary", "extra"],
            vec!["extra", "--summary"],
        ] {
            assert!(summary_mode(args.into_iter().map(OsString::from)).is_err());
        }
    }

    #[test]
    fn demo_propagates_buffered_write_and_flush_errors() {
        struct Destination {
            fail_write: bool,
            writes: usize,
            flushes: usize,
        }

        impl Write for Destination {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                self.writes += 1;
                if self.fail_write {
                    return Err(io::ErrorKind::BrokenPipe.into());
                }
                Ok(bytes.len())
            }

            fn flush(&mut self) -> io::Result<()> {
                self.flushes += 1;
                Err(io::ErrorKind::PermissionDenied.into())
            }
        }

        for (summary, fail_write) in [(false, true), (false, false), (true, true), (true, false)] {
            let mut output = BufWriter::with_capacity(
                4096,
                Destination {
                    fail_write,
                    writes: 0,
                    flushes: 0,
                },
            );
            let error = write_demo(&mut output, summary).expect_err("destination must fail");
            let error = error.downcast_ref::<io::Error>().expect("I/O error");
            assert_eq!(
                error.kind(),
                if fail_write {
                    io::ErrorKind::BrokenPipe
                } else {
                    io::ErrorKind::PermissionDenied
                }
            );
            assert_eq!(output.get_ref().writes, 1);
            assert_eq!(output.get_ref().flushes, usize::from(!fail_write));
            let _ = output.into_parts();
        }
    }
}
