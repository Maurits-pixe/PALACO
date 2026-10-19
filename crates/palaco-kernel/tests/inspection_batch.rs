use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    inspection::{
        PlanInspectionSummary, PlanInspectionSummaryError, PlanInspectionWriteError,
        summarize_plan_iter, summarize_plans, try_summarize_plan_iter,
        try_write_plan_inspections_jsonl, write_plan_inspection_json,
        write_plan_inspection_summary_json, write_plan_inspections_jsonl,
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
fn fallible_summaries_match_successful_sources_and_preserve_source_errors()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    assert_eq!(
        try_summarize_plan_iter(plans.iter().map(Ok::<_, io::Error>))?,
        summarize_plans(&plans)
    );
    assert_eq!(
        try_summarize_plan_iter(std::iter::empty::<Result<&RuntimePlan, io::Error>>())?,
        PlanInspectionSummary::default()
    );
    for completed in [0, 1, plans.len()] {
        let mut input = plans[..completed].iter().map(Ok).chain([
            Err(io::Error::new(io::ErrorKind::InvalidData, "PRIVATE-DETAIL")),
            Ok(&plans[0]),
        ]);
        let error = try_summarize_plan_iter(&mut input).expect_err("source must fail");
        assert_eq!(error.to_string(), "plan inspection summary source failed");
        assert!(std::error::Error::source(&error).is_some());
        match error {
            PlanInspectionSummaryError::Source(error) => {
                assert_eq!(error.kind(), io::ErrorKind::InvalidData);
                assert_eq!(error.to_string(), "PRIVATE-DETAIL");
            }
            PlanInspectionSummaryError::Overflow => panic!("small input cannot overflow"),
        }
        assert!(matches!(input.next(), Some(Ok(plan)) if std::ptr::eq(plan, &plans[0])));
    }
    let overflow = PlanInspectionSummaryError::<io::Error>::Overflow;
    assert_eq!(
        overflow.to_string(),
        "plan inspection summary counter overflow"
    );
    assert!(std::error::Error::source(&overflow).is_none());
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn fallible_summaries_accept_borrowed_opaque_errors_without_read_ahead()
-> Result<(), Box<dyn std::error::Error>> {
    struct OpaqueFailure;
    let failure = OpaqueFailure;
    let plans = plans()?;
    let mut input = [Ok(&plans[0]), Err(&failure), Ok(&plans[1])].into_iter();
    let error = match try_summarize_plan_iter(&mut input) {
        Err(error) => error,
        Ok(_) => panic!("source must fail"),
    };
    assert_eq!(error.to_string(), "plan inspection summary source failed");
    match error {
        PlanInspectionSummaryError::Source(error) => assert!(std::ptr::eq(error, &failure)),
        PlanInspectionSummaryError::Overflow => panic!("small input cannot overflow"),
    }
    assert!(matches!(input.next(), Some(Ok(plan)) if std::ptr::eq(plan, &plans[1])));
    Ok(())
}

#[test]
fn summaries_keep_disposition_and_validation_counts_separate()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    assert_eq!(summarize_plans(&[]), PlanInspectionSummary::default());
    let summary = summarize_plans(&plans);
    assert_eq!(summary.total, 4);
    assert_eq!(summary.execute, 1);
    assert_eq!(summary.hold, 1);
    assert_eq!(summary.deny, 2);
    assert_eq!(summary.contract_valid, 4);
    assert_eq!(summary.contract_invalid, 0);
    assert_eq!(summary.execute + summary.hold + summary.deny, summary.total);
    assert_eq!(
        summary.contract_valid + summary.contract_invalid,
        summary.total
    );

    for (index, plan) in plans.iter().enumerate() {
        let single = summarize_plans(std::slice::from_ref(plan));
        let prefix = summarize_plans(&plans[..index]);
        let suffix = summarize_plans(&plans[index + 1..]);
        assert_eq!(prefix.total + single.total + suffix.total, summary.total);
        assert_eq!(
            prefix.execute + single.execute + suffix.execute,
            summary.execute
        );
        assert_eq!(prefix.hold + single.hold + suffix.hold, summary.hold);
        assert_eq!(prefix.deny + single.deny + suffix.deny, summary.deny);
    }
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn checked_summary_addition_matches_chunks_and_counts_overlapping_observations()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    let whole = summarize_plans(&plans);
    let empty = PlanInspectionSummary::default();
    assert_eq!(whole.checked_add(empty), Some(whole));
    assert_eq!(empty.checked_add(whole), Some(whole));
    for split in 0..=plans.len() {
        let left = summarize_plans(&plans[..split]);
        let right = summarize_plans(&plans[split..]);
        assert_eq!(left.checked_add(right), Some(whole));
        assert_eq!(right.checked_add(left), Some(whole));
    }
    let folded = plans
        .chunks(1)
        .try_fold(empty, |sum, chunk| sum.checked_add(summarize_plans(chunk)));
    assert_eq!(folded, Some(whole));
    let duplicate = [plans[0].clone(), plans[0].clone()];
    let single = summarize_plans(&plans[..1]);
    assert_eq!(
        single.checked_add(single),
        Some(summarize_plans(&duplicate))
    );
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn checked_summary_addition_checks_every_public_counter_without_mutation() {
    fn fields(summary: &mut PlanInspectionSummary) -> [&mut usize; 6] {
        [
            &mut summary.total,
            &mut summary.execute,
            &mut summary.hold,
            &mut summary.deny,
            &mut summary.contract_valid,
            &mut summary.contract_invalid,
        ]
    }

    for index in 0..6 {
        let mut maximum = PlanInspectionSummary::default();
        let mut one = PlanInspectionSummary::default();
        let zero = PlanInspectionSummary::default();
        *fields(&mut maximum)[index] = usize::MAX;
        *fields(&mut one)[index] = 1;
        let original = maximum;
        assert_eq!(maximum.checked_add(zero), Some(maximum));
        assert_eq!(zero.checked_add(maximum), Some(maximum));
        assert_eq!(maximum.checked_add(one), None);
        assert_eq!(one.checked_add(maximum), None);
        assert_eq!(maximum, original);
    }
}

#[test]
fn iterator_summaries_match_slices_and_filtered_borrowed_plans()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    assert_eq!(
        summarize_plan_iter(std::iter::empty()),
        Some(PlanInspectionSummary::default())
    );
    assert_eq!(summarize_plan_iter(&plans), Some(summarize_plans(&plans)));
    for split in 0..=plans.len() {
        assert_eq!(
            summarize_plan_iter(plans[..split].iter()),
            Some(summarize_plans(&plans[..split]))
        );
    }
    let denied = summarize_plan_iter(
        plans
            .iter()
            .filter(|plan| plan.disposition() == palaco_foundation::ContractDisposition::Deny),
    )
    .expect("small filtered input cannot overflow");
    assert_eq!(denied.total, 2);
    assert_eq!(denied.deny, 2);
    assert_eq!(denied.hold, 0);
    assert_eq!(denied.execute, 0);
    assert_eq!(denied.contract_valid, 2);
    assert_eq!(denied.contract_invalid, 0);
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn bounded_iterator_summaries_count_duplicates_without_read_ahead()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    let requested = std::cell::Cell::new(0);
    let mut source = plans.iter().cycle().inspect(|_| {
        requested.set(requested.get() + 1);
    });
    assert_eq!(
        summarize_plan_iter(source.by_ref().take(0)),
        Some(PlanInspectionSummary::default())
    );
    assert_eq!(requested.get(), 0);
    let summary =
        summarize_plan_iter(source.by_ref().take(6)).expect("bounded input cannot overflow");
    let expected = summarize_plans(&plans)
        .checked_add(summarize_plans(&plans[..2]))
        .expect("small summaries cannot overflow");
    assert_eq!(summary, expected);
    assert_eq!(requested.get(), 6);
    assert_eq!(source.next(), Some(&plans[2]));
    assert_eq!(requested.get(), 7);
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn repeated_plans_count_per_entry_and_local_summary_edits_are_isolated()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let repeated = [plans[1].clone(), plans[1].clone(), plans[0].clone()];
    let original = repeated.clone();
    let summary = summarize_plans(&repeated);
    assert_eq!(summary.total, 3);
    assert_eq!(summary.deny, 2);
    assert_eq!(summary.execute, 1);
    assert_eq!(summary.hold, 0);
    assert_eq!(summary.contract_valid, 3);
    let mut local = summary;
    local.execute = 999;
    local.contract_invalid = 999;
    assert_ne!(local, summarize_plans(&repeated));
    assert_eq!(summarize_plans(&repeated), summary);
    assert_eq!(repeated, original);
    Ok(())
}

#[test]
fn summary_json_reports_exact_counts_without_evidence_or_plan_mutations()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let repeated = [plans[1].clone(), plans[1].clone(), plans[0].clone()];
    for (input, counts) in [
        (&[][..], [0, 0, 0, 0, 0, 0]),
        (plans.as_slice(), [4, 1, 1, 2, 4, 0]),
        (&repeated[..], [3, 1, 0, 2, 3, 0]),
    ] {
        let original = input.to_vec();
        let [total, execute, hold, deny, valid, invalid] = counts;
        let expected = format!(
            "{{\"schema_version\":1,\"report_type\":\"plan-inspection-summary\",\"total\":{total},\"execute\":{execute},\"hold\":{hold},\"deny\":{deny},\"contract_valid\":{valid},\"contract_invalid\":{invalid},\"execution_performed\":false,\"authority_verified\":false}}\n"
        );
        let mut destination = Destination {
            bytes: Vec::new(),
            remaining: usize::MAX,
        };
        write_plan_inspection_summary_json(input, &mut destination as &mut dyn Write)?;
        assert_eq!(destination.bytes, expected.as_bytes());
        assert_eq!(input, original);
    }
    Ok(())
}

#[test]
fn summary_json_propagates_write_errors_with_exact_partial_output()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    for input in [&[][..], plans.as_slice()] {
        let mut expected = Vec::new();
        write_plan_inspection_summary_json(input, &mut expected)?;
        for remaining in [0, 7, expected.len() - 1] {
            let mut destination = Destination {
                bytes: Vec::new(),
                remaining,
            };
            let error = write_plan_inspection_summary_json(input, &mut destination)
                .expect_err("destination must fail");
            assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
            assert_eq!(destination.bytes, expected[..remaining]);
        }
    }
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn summary_json_retries_interrupted_writes_and_rejects_zero_progress()
-> Result<(), Box<dyn std::error::Error>> {
    struct InterruptedDestination {
        bytes: Vec<u8>,
        interrupt: bool,
        stop_after: usize,
    }

    impl Write for InterruptedDestination {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.interrupt {
                self.interrupt = false;
                return Err(io::ErrorKind::Interrupted.into());
            }
            self.interrupt = true;
            let count = bytes.len().min(2).min(self.stop_after - self.bytes.len());
            self.bytes.extend_from_slice(&bytes[..count]);
            Ok(count)
        }

        fn flush(&mut self) -> io::Result<()> {
            panic!("summary writer must not flush");
        }
    }

    let plans = plans()?;
    let original = plans.clone();
    for input in [&[][..], plans.as_slice()] {
        let mut expected = Vec::new();
        write_plan_inspection_summary_json(input, &mut expected)?;
        for stop_after in [0, 7, expected.len() - 1, expected.len()] {
            let mut destination = InterruptedDestination {
                bytes: Vec::new(),
                interrupt: true,
                stop_after,
            };
            let result = write_plan_inspection_summary_json(input, &mut destination);
            if stop_after == expected.len() {
                result?;
            } else {
                assert_eq!(
                    result.expect_err("zero progress must fail").kind(),
                    io::ErrorKind::WriteZero
                );
            }
            assert_eq!(destination.bytes, expected[..stop_after]);
        }
    }
    assert_eq!(plans, original);
    Ok(())
}

#[test]
fn summary_json_leaves_buffered_delivery_and_errors_to_the_caller()
-> Result<(), Box<dyn std::error::Error>> {
    let plans = plans()?;
    let original = plans.clone();
    for input in [&[][..], plans.as_slice()] {
        let mut expected = Vec::new();
        write_plan_inspection_summary_json(input, &mut expected)?;
        for remaining in [0, 7, usize::MAX] {
            let mut output = BufWriter::with_capacity(
                expected.len() + 1,
                Destination {
                    bytes: Vec::new(),
                    remaining,
                },
            );
            write_plan_inspection_summary_json(input, &mut output)?;
            assert_eq!(output.buffer(), expected);
            assert!(output.get_ref().bytes.is_empty());
            if remaining != usize::MAX {
                let error = output.flush().expect_err("buffered destination must fail");
                assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
                assert_eq!(output.get_ref().bytes, expected[..remaining]);
                assert_eq!(output.buffer(), &expected[remaining..]);
            }
            let (destination, pending) = output.into_parts();
            let delivered = if remaining == usize::MAX {
                0
            } else {
                remaining
            };
            assert_eq!(destination.bytes, expected[..delivered]);
            assert_eq!(
                pending.expect("writer did not panic"),
                expected[delivered..]
            );
        }
    }
    assert_eq!(plans, original);
    Ok(())
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
