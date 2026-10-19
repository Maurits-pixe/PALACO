use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    inspection::{write_plan_inspection_json, write_plan_inspections_jsonl},
};
use std::io::{self, BufWriter, Write};

fn plans() -> Result<Vec<RuntimePlan>, ContractError> {
    [
        AuthorityState::Authorized,
        AuthorityState::Revoked,
        AuthorityState::Expired,
        AuthorityState::InDoubt,
    ]
    .into_iter()
    .map(|authority| {
        let event = EventEnvelope::new("synthetic.batch", EvidenceRef::new("SYNTHETIC-BATCH")?);
        Ok(RuntimePlan::new(ExecutionBoundary::new(
            ProvenanceRecord::new(event, authority),
        )))
    })
    .collect()
}

struct Destination {
    bytes: Vec<u8>,
    remaining: usize,
}

impl Write for Destination {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return Err(io::ErrorKind::BrokenPipe.into());
        }
        let count = bytes.len().min(3).min(self.remaining);
        self.bytes.extend_from_slice(&bytes[..count]);
        self.remaining -= count;
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        panic!("batch writer must not flush");
    }
}

#[test]
fn batch_preserves_order_and_plans_with_short_writes() -> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    let mut expected = Vec::new();
    for plan in &plans {
        write_plan_inspection_json(plan, &mut expected)?;
    }
    let mut destination = Destination {
        bytes: Vec::new(),
        remaining: usize::MAX,
    };
    write_plan_inspections_jsonl(&plans, &mut destination as &mut dyn Write)?;
    assert_eq!(destination.bytes, expected);
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn empty_batch_does_not_touch_destination() -> io::Result<()> {
    let mut destination = Destination {
        bytes: Vec::new(),
        remaining: 0,
    };
    write_plan_inspections_jsonl(std::iter::empty(), &mut destination)?;
    assert!(destination.bytes.is_empty());
    Ok(())
}

#[test]
fn failed_batch_does_not_request_later_plans() -> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let mut first = Vec::new();
    write_plan_inspection_json(&plans[0], &mut first)?;
    let mut expected = Vec::new();
    write_plan_inspections_jsonl(&plans, &mut expected)?;

    for (capacity, consumed) in [(0, 1), (10, 1), (first.len(), 2), (first.len() + 10, 2)] {
        let mut requested = 0;
        let mut destination = Destination {
            bytes: Vec::new(),
            remaining: capacity,
        };
        let mut input = plans.iter().inspect(|_| requested += 1);
        let error = write_plan_inspections_jsonl(&mut input, &mut destination)
            .expect_err("bounded destination must fail");
        assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
        assert_eq!(input.next(), Some(&plans[consumed]));
        assert_eq!(requested, consumed + 1);
        assert_eq!(destination.bytes, expected[..capacity]);
    }
    Ok(())
}

#[test]
fn interrupted_short_writes_retry_without_repeating_or_losing_bytes()
-> Result<(), Box<dyn std::error::Error>> {
    struct InterruptedDestination {
        bytes: Vec<u8>,
        interrupt: bool,
        interruptions: usize,
    }

    impl Write for InterruptedDestination {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.interrupt = !self.interrupt;
            if self.interrupt {
                self.interruptions += 1;
                return Err(io::ErrorKind::Interrupted.into());
            }
            let count = bytes.len().min(2);
            self.bytes.extend_from_slice(&bytes[..count]);
            Ok(count)
        }

        fn flush(&mut self) -> io::Result<()> {
            panic!("batch writer must not flush");
        }
    }

    let plans = plans()?;
    let mut expected = Vec::new();
    for plan in &plans {
        write_plan_inspection_json(plan, &mut expected)?;
    }
    let mut destination = InterruptedDestination {
        bytes: Vec::new(),
        interrupt: false,
        interruptions: 0,
    };
    let mut requested = 0;
    write_plan_inspections_jsonl(plans.iter().inspect(|_| requested += 1), &mut destination)?;
    assert_eq!(requested, plans.len());
    assert!(destination.interruptions > plans.len());
    assert_eq!(destination.bytes, expected);
    Ok(())
}

#[test]
fn zero_byte_write_stops_before_requesting_the_next_plan() -> Result<(), Box<dyn std::error::Error>>
{
    struct ZeroDestination;
    impl Write for ZeroDestination {
        fn write(&mut self, _: &[u8]) -> io::Result<usize> {
            Ok(0)
        }
        fn flush(&mut self) -> io::Result<()> {
            panic!("batch writer must not flush");
        }
    }
    let plans = plans()?;
    let mut input = plans.iter();
    let error = write_plan_inspections_jsonl(&mut input, &mut ZeroDestination)
        .expect_err("zero-byte write must not report success");
    assert_eq!(error.kind(), io::ErrorKind::WriteZero);
    assert_eq!(input.next(), Some(&plans[1]));
    Ok(())
}

#[test]
fn buffered_batch_can_consume_all_plans_before_destination_failure()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let mut output = BufWriter::with_capacity(
        4096,
        Destination {
            bytes: Vec::new(),
            remaining: 0,
        },
    );
    let mut requested = 0;
    write_plan_inspections_jsonl(plans.iter().inspect(|_| requested += 1), &mut output)?;
    assert_eq!(requested, plans.len());
    assert!(output.get_ref().bytes.is_empty());
    let mut expected = Vec::new();
    for plan in &plans {
        write_plan_inspection_json(plan, &mut expected)?;
    }
    assert_eq!(output.buffer(), expected);
    let error = output
        .flush()
        .expect_err("underlying destination must fail");
    assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
    assert_eq!(output.buffer(), expected);
    let _ = output.into_parts();
    Ok(())
}
