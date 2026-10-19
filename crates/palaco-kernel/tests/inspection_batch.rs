use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    inspection::{
        PlanInspectionWriteError, try_write_plan_inspections_jsonl, write_plan_inspection_json,
        write_plan_inspections_jsonl,
    },
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

#[test]
fn source_failure_preserves_buffered_reports_for_explicit_discard()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let mut expected = Vec::new();
    write_plan_inspection_json(&plans[0], &mut expected)?;
    let mut output = BufWriter::with_capacity(
        4096,
        Destination {
            bytes: Vec::new(),
            remaining: usize::MAX,
        },
    );
    let mut input = [Ok(&plans[0]), Err("source failed"), Ok(&plans[1])].into_iter();
    let error = try_write_plan_inspections_jsonl(&mut input, &mut output)
        .expect_err("source must fail after one buffered report");
    assert!(matches!(
        error,
        PlanInspectionWriteError::Source("source failed")
    ));
    assert_eq!(output.buffer(), expected);
    assert!(output.get_ref().bytes.is_empty());
    assert_eq!(input.next(), Some(Ok(&plans[1])));

    let (destination, pending) = output.into_parts();
    assert_eq!(pending.expect("writer did not panic"), expected);
    assert!(destination.bytes.is_empty());
    Ok(())
}

#[test]
fn borrowed_source_errors_need_no_error_debug_or_clone_implementation()
-> Result<(), Box<dyn std::error::Error>> {
    struct SourceFailure {
        detail: String,
    }
    let failure = SourceFailure {
        detail: "caller-owned detail".into(),
    };
    let mut output = Vec::new();
    let result = try_write_plan_inspections_jsonl(
        std::iter::once(Err::<&RuntimePlan, _>(&failure)),
        &mut output,
    );
    let error = match result {
        Err(error) => error,
        Ok(()) => panic!("source error must propagate"),
    };
    assert_eq!(error.to_string(), "plan inspection source failed");
    match error {
        PlanInspectionWriteError::Source(original) => {
            assert!(std::ptr::eq(original, &failure));
            assert_eq!(original.detail, "caller-owned detail");
        }
        PlanInspectionWriteError::Output(_) => panic!("unexpected output error"),
    }
    assert!(output.is_empty());
    Ok(())
}

struct Destination {
    bytes: Vec<u8>,
    remaining: usize,
}

#[test]
fn fallible_success_and_empty_input_match_infallible_writer()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let mut expected = Vec::new();
    write_plan_inspections_jsonl(&plans, &mut expected)?;
    let mut destination = Destination {
        bytes: Vec::new(),
        remaining: usize::MAX,
    };
    try_write_plan_inspections_jsonl(
        plans.iter().map(Ok::<_, io::Error>),
        &mut destination as &mut dyn Write,
    )?;
    assert_eq!(destination.bytes, expected);
    let mut empty = Destination {
        bytes: Vec::new(),
        remaining: 0,
    };
    try_write_plan_inspections_jsonl(
        std::iter::empty::<Result<&RuntimePlan, io::Error>>(),
        &mut empty,
    )?;
    assert!(empty.bytes.is_empty());
    Ok(())
}

#[test]
fn source_failure_stops_without_writing_error_details_or_reading_ahead()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    for completed in [0, 1] {
        let mut input = plans[..completed]
            .iter()
            .map(Ok)
            .chain(std::iter::once(Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "PRIVATE-SOURCE-DETAIL",
            ))))
            .chain(std::iter::once(Ok(&plans[2])));
        let mut output = Vec::new();
        let error = try_write_plan_inspections_jsonl(&mut input, &mut output)
            .expect_err("source must fail");
        assert_eq!(error.to_string(), "plan inspection source failed");
        assert!(std::error::Error::source(&error).is_some());
        match error {
            PlanInspectionWriteError::Source(error) => {
                assert_eq!(error.kind(), io::ErrorKind::InvalidData);
                assert_eq!(error.to_string(), "PRIVATE-SOURCE-DETAIL");
            }
            PlanInspectionWriteError::Output(_) => panic!("expected source error"),
        }
        let mut expected = Vec::new();
        write_plan_inspections_jsonl(&plans[..completed], &mut expected)?;
        assert_eq!(output, expected);
        assert_eq!(input.next().expect("next item retained")?, &plans[2]);
    }
    Ok(())
}

#[test]
fn output_failure_precedes_unread_source_errors() -> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let mut first = Vec::new();
    write_plan_inspection_json(&plans[0], &mut first)?;
    let mut expected = first.clone();
    write_plan_inspection_json(&plans[1], &mut expected)?;
    for capacity in [0, 10, first.len(), first.len() + 10] {
        let mut input = [Ok(&plans[0]), Ok(&plans[1]), Err("unread source error")].into_iter();
        let mut destination = Destination {
            bytes: Vec::new(),
            remaining: capacity,
        };
        let error = try_write_plan_inspections_jsonl(&mut input, &mut destination)
            .expect_err("output must fail first");
        assert_eq!(error.to_string(), "plan inspection output failed");
        match error {
            PlanInspectionWriteError::Output(error) => {
                assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
            }
            PlanInspectionWriteError::Source(_) => panic!("source error read too early"),
        }
        assert_eq!(destination.bytes, expected[..capacity]);
        if capacity < first.len() {
            assert_eq!(input.next().expect("second plan retained"), Ok(&plans[1]));
        }
        assert_eq!(input.next(), Some(Err("unread source error")));
    }
    Ok(())
}

#[test]
fn bounded_batches_preserve_duplicates_and_resume_without_read_ahead()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let sequence = [&plans[2], &plans[0], &plans[2], &plans[3]];
    let mut input = sequence.into_iter().cycle();
    let mut output = Vec::new();

    write_plan_inspections_jsonl(input.by_ref().take(0), &mut output)?;
    assert!(output.is_empty());
    write_plan_inspections_jsonl(input.by_ref().take(3), &mut output)?;
    write_plan_inspections_jsonl(input.by_ref().take(2), &mut output)?;

    let mut expected = Vec::new();
    for plan in [
        sequence[0],
        sequence[1],
        sequence[2],
        sequence[3],
        sequence[0],
    ] {
        write_plan_inspection_json(plan, &mut expected)?;
    }
    assert_eq!(output, expected);
    assert_eq!(input.next(), Some(sequence[1]));
    Ok(())
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
