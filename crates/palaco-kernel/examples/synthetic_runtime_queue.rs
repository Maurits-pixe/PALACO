//! Local queue lifecycle demonstration only, never execution or authorization.

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    inspection::write_plan_inspection_json,
    scheduling::{AdmissionError, QueueState, RuntimeQueue},
};
use std::io::{self, BufWriter, Write};

fn plan(id: &str, authority: AuthorityState) -> Result<RuntimePlan, ContractError> {
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(
            EventEnvelope::new("synthetic.queue.only", EvidenceRef::new(id)?),
            authority,
        ),
    )))
}

fn write_batch(queue: &mut RuntimeQueue, limit: usize, output: &mut impl Write) -> io::Result<()> {
    for transferred in queue.next_plans(limit) {
        write_plan_inspection_json(&transferred, output)?;
    }
    Ok(())
}

fn write_demo(output: &mut impl Write) -> Result<(), Box<dyn std::error::Error>> {
    let first = plan("SYNTHETIC-FIRST", AuthorityState::Authorized)?;
    let second = plan("SYNTHETIC-SECOND", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(2);
    for (authority, expected) in [
        (AuthorityState::Revoked, AdmissionError::Denied),
        (AuthorityState::Expired, AdmissionError::Denied),
        (AuthorityState::InDoubt, AdmissionError::Held),
    ] {
        let rejected = queue
            .submit(plan("SYNTHETIC-REJECTED", authority)?)
            .expect_err("non-Execute plan must be rejected");
        assert_eq!(rejected.reason(), expected);
    }
    queue.submit(first.clone()).expect("first admission");
    queue.submit(second.clone()).expect("second admission");
    let rejected = queue.submit(first.clone()).expect_err("capacity reached");
    assert_eq!(rejected.reason(), AdmissionError::Full);
    assert_eq!(rejected.into_plan(), first);
    queue.begin_drain();
    assert_eq!(queue.state(), QueueState::Draining);
    let rejected = queue.submit(first.clone()).expect_err("admission closed");
    assert_eq!(rejected.reason(), AdmissionError::Draining);
    assert_eq!(queue.pending().collect::<Vec<_>>(), vec![&first, &second]);
    write_batch(&mut queue, 1, output)?;
    assert_eq!(queue.state(), QueueState::Draining);
    assert_eq!(queue.pending().collect::<Vec<_>>(), vec![&second]);
    write_batch(&mut queue, usize::MAX, output)?;
    assert!(queue.is_empty());
    assert_eq!(queue.state(), QueueState::Stopped);
    assert_eq!(queue.next_plan(), None);
    assert_eq!(queue.stop(), 0);
    queue.begin_drain();
    let rejected = queue.submit(rejected.into_plan()).expect_err("no restart");
    assert_eq!(rejected.reason(), AdmissionError::Stopped);
    output.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    if std::env::args_os().nth(1).is_some() {
        return Err("usage: synthetic_runtime_queue".into());
    }
    write_demo(&mut BufWriter::new(io::stdout().lock()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failed_batch_preserves_unrequested_plans_and_exact_output_prefix()
    -> Result<(), ContractError> {
        struct Destination {
            bytes: Vec<u8>,
            remaining: usize,
            zero_progress: bool,
        }
        impl Write for Destination {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                if self.remaining == 0 {
                    return if self.zero_progress {
                        Ok(0)
                    } else {
                        Err(io::ErrorKind::BrokenPipe.into())
                    };
                }
                let written = bytes.len().min(self.remaining).min(3);
                self.bytes.extend_from_slice(&bytes[..written]);
                self.remaining -= written;
                Ok(written)
            }
            fn flush(&mut self) -> io::Result<()> {
                panic!("batch helper must leave flushing to the caller");
            }
        }
        let first = plan("BATCH-FIRST", AuthorityState::Authorized)?;
        let second = plan("BATCH-SECOND", AuthorityState::Authorized)?;
        let third = plan("BATCH-THIRD", AuthorityState::Authorized)?;
        let mut report = Vec::new();
        write_plan_inspection_json(&first, &mut report).expect("reference report");
        for zero_progress in [false, true] {
            for budget in [0, 7, report.len(), report.len() + 7] {
                let mut queue = RuntimeQueue::new(3);
                for pending in [&first, &second, &third] {
                    queue.submit(pending.clone()).expect("admission");
                }
                queue.begin_drain();
                let mut output = Destination {
                    bytes: Vec::new(),
                    remaining: budget,
                    zero_progress,
                };
                write_batch(&mut queue, 0, &mut output).expect("zero batch performs no I/O");
                assert_eq!(queue.len(), 3);
                let error =
                    write_batch(&mut queue, usize::MAX, &mut output).expect_err("output fails");
                assert_eq!(
                    error.kind(),
                    if zero_progress {
                        io::ErrorKind::WriteZero
                    } else {
                        io::ErrorKind::BrokenPipe
                    }
                );
                assert_eq!(output.bytes, report.repeat(2)[..budget]);
                assert_eq!(queue.state(), QueueState::Draining);
                let expected = if budget < report.len() {
                    vec![&second, &third]
                } else {
                    vec![&third]
                };
                assert_eq!(queue.pending().collect::<Vec<_>>(), expected);
                let mut resumed = Vec::new();
                write_batch(&mut queue, usize::MAX, &mut resumed).expect("resume remaining plans");
                assert_eq!(resumed, report.repeat(expected.len()));
                assert_eq!(queue.state(), QueueState::Stopped);
            }
        }
        Ok(())
    }

    #[test]
    fn demo_reports_only_two_transferred_synthetic_plans() -> Result<(), Box<dyn std::error::Error>>
    {
        let mut output = Vec::new();
        write_demo(&mut output)?;
        let line = "{\"schema_version\":1,\"report_type\":\"plan-inspection\",\"disposition\":\"execute\",\"contract_valid\":true,\"execution_performed\":false,\"authority_verified\":false}\n";
        assert_eq!(output, line.repeat(2).as_bytes());
        Ok(())
    }

    #[test]
    fn demo_propagates_write_and_flush_failures() {
        struct Destination(bool);
        impl Write for Destination {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                if self.0 {
                    Err(io::ErrorKind::BrokenPipe.into())
                } else {
                    Ok(bytes.len().min(3))
                }
            }
            fn flush(&mut self) -> io::Result<()> {
                if self.0 {
                    panic!("write failure must return before flush");
                }
                Err(io::ErrorKind::PermissionDenied.into())
            }
        }
        for fail_write in [false, true] {
            let error = write_demo(&mut Destination(fail_write)).expect_err("destination fails");
            assert_eq!(
                error.downcast_ref::<io::Error>().expect("I/O error").kind(),
                if fail_write {
                    io::ErrorKind::BrokenPipe
                } else {
                    io::ErrorKind::PermissionDenied
                }
            );
        }
    }
}
