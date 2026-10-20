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
    for expected in [first, second] {
        let transferred = queue.next_plan().expect("pending plan");
        assert_eq!(transferred, expected);
        write_plan_inspection_json(&transferred, output)?;
    }
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
