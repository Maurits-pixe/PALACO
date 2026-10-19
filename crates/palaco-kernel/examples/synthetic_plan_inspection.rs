//! Synthetic inspection fixtures only: no evidence authentication or execution.

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{RuntimePlan, inspection::write_plan_inspections_jsonl};
use std::io::{self, BufWriter, Write};

fn write_demo(output: &mut impl Write) -> Result<(), Box<dyn std::error::Error>> {
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
    write_plan_inspections_jsonl(&plans, output)?;
    output.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut output = BufWriter::new(io::stdout().lock());
    write_demo(&mut output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_emits_exactly_four_synthetic_reports() -> Result<(), Box<dyn std::error::Error>> {
        let mut output = Vec::new();
        write_demo(&mut output)?;
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

        for fail_write in [true, false] {
            let mut output = BufWriter::with_capacity(
                4096,
                Destination {
                    fail_write,
                    writes: 0,
                    flushes: 0,
                },
            );
            let error = write_demo(&mut output).expect_err("destination must fail");
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
