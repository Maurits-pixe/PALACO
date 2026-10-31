use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    inspection::{summarize_plan_iter, write_plan_inspection_json, write_plan_inspections_jsonl},
    scheduling::{AdmissionError, QueueState, RuntimeQueue},
};
use std::io::{self, Write};

fn plan(id: &str, authority: AuthorityState) -> Result<RuntimePlan, ContractError> {
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(
            EventEnvelope::new("synthetic.queue", EvidenceRef::new(id)?),
            authority,
        ),
    )))
}

#[test]
fn head_inspection_and_failed_reporting_preserve_fifo_and_drain() -> Result<(), ContractError> {
    struct FailingOutput;
    impl Write for FailingOutput {
        fn write(&mut self, _: &[u8]) -> io::Result<usize> {
            Err(io::ErrorKind::BrokenPipe.into())
        }
        fn flush(&mut self) -> io::Result<()> {
            panic!("inspection must not flush");
        }
    }
    for draining in [false, true] {
        let first = plan("HEAD-FIRST", AuthorityState::Authorized)?;
        let second = plan("HEAD-SECOND", AuthorityState::Authorized)?;
        let mut queue = RuntimeQueue::new(2);
        assert_eq!(queue.front_plan(), None);
        queue.submit(first.clone()).expect("first admission");
        queue.submit(second.clone()).expect("second admission");
        if draining {
            queue.begin_drain();
        }
        let state = queue.state();
        for _ in 0..2 {
            let head = queue.front_plan().expect("head");
            assert_eq!(head, &first);
            assert!(std::ptr::eq(
                head,
                queue.pending().next().expect("same head")
            ));
            let error =
                write_plan_inspection_json(head, &mut FailingOutput).expect_err("report fails");
            assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
            assert_eq!(queue.len(), 2);
            assert_eq!(queue.state(), state);
        }
        assert_eq!(queue.next_plan(), Some(first));
        assert_eq!(queue.front_plan(), Some(&second));
        assert_eq!(queue.state(), state);
        assert_eq!(queue.next_plans(1).next(), Some(second));
        assert_eq!(queue.front_plan(), None);
        assert_eq!(
            queue.state(),
            if draining {
                QueueState::Stopped
            } else {
                QueueState::Running
            }
        );
    }
    let mut queue = RuntimeQueue::new(1);
    queue
        .submit(plan("DISCARDED-HEAD", AuthorityState::Authorized)?)
        .expect("admission");
    assert_eq!(queue.stop(), 1);
    assert_eq!(queue.front_plan(), None);
    Ok(())
}

#[test]
fn short_action_sequences_match_an_independent_fifo_lifecycle_model() -> Result<(), ContractError> {
    const ACTIONS: usize = 11;
    const DEPTH: u32 = 4;
    let authorities = [
        AuthorityState::Authorized,
        AuthorityState::Revoked,
        AuthorityState::Expired,
        AuthorityState::InDoubt,
    ];
    for capacity in 0..=3 {
        for sequence in 0..ACTIONS.pow(DEPTH) {
            let mut queue = RuntimeQueue::new(capacity);
            let mut expected = Vec::new();
            let mut admission_closed = false;
            let mut remaining_actions = sequence;
            for step in 0..DEPTH {
                let action = remaining_actions % ACTIONS;
                remaining_actions /= ACTIONS;
                let context = (capacity, sequence, step, action);
                match action {
                    0..=3 => {
                        let supplied =
                            plan(&format!("MODEL-{step}-{action}"), authorities[action])?;
                        let reason = if admission_closed {
                            Some(if expected.is_empty() {
                                AdmissionError::Stopped
                            } else {
                                AdmissionError::Draining
                            })
                        } else {
                            match action {
                                1 | 2 => Some(AdmissionError::Denied),
                                3 => Some(AdmissionError::Held),
                                _ if expected.len() == capacity => Some(AdmissionError::Full),
                                _ => None,
                            }
                        };
                        match (queue.submit(supplied.clone()), reason) {
                            (Ok(()), None) => expected.push(supplied),
                            (Err(rejected), Some(reason)) => {
                                assert_eq!(rejected.reason(), reason, "{context:?}");
                                assert_eq!(rejected.into_plan(), supplied, "{context:?}");
                            }
                            (actual, reason) => {
                                panic!("admission mismatch {context:?}: {actual:?}, {reason:?}");
                            }
                        }
                    }
                    4 => {
                        let transferred = if expected.is_empty() {
                            None
                        } else {
                            Some(expected.remove(0))
                        };
                        assert_eq!(queue.next_plan(), transferred, "{context:?}");
                    }
                    5..=7 => {
                        let limit = match action {
                            5 => 0,
                            6 => 1,
                            _ => usize::MAX,
                        };
                        let count = limit.min(expected.len());
                        let transferred: Vec<_> = expected.drain(..count).collect();
                        assert_eq!(
                            queue.next_plans(limit).collect::<Vec<_>>(),
                            transferred,
                            "{context:?}"
                        );
                    }
                    8 => {
                        admission_closed = true;
                        queue.begin_drain();
                    }
                    9 => {
                        admission_closed = true;
                        let discarded = expected.len();
                        expected.clear();
                        assert_eq!(queue.stop(), discarded, "{context:?}");
                    }
                    _ => {
                        let summary =
                            summarize_plan_iter(queue.pending()).expect("bounded summary");
                        assert_eq!(summary.total, expected.len(), "{context:?}");
                        assert_eq!(summary.execute, expected.len(), "{context:?}");
                    }
                }
                let state = if !admission_closed {
                    QueueState::Running
                } else if expected.is_empty() {
                    QueueState::Stopped
                } else {
                    QueueState::Draining
                };
                assert_eq!(queue.state(), state, "{context:?}");
                assert_eq!(
                    queue.is_stopped(),
                    state == QueueState::Stopped,
                    "{context:?}"
                );
                assert_eq!(queue.capacity(), capacity, "{context:?}");
                assert_eq!(queue.len(), expected.len(), "{context:?}");
                assert_eq!(queue.front_plan(), expected.first(), "{context:?}");
                assert_eq!(queue.is_empty(), expected.is_empty(), "{context:?}");
                assert!(queue.len() <= capacity, "{context:?}");
                assert_eq!(
                    queue.pending().collect::<Vec<_>>(),
                    expected.iter().collect::<Vec<_>>(),
                    "{context:?}"
                );
            }
        }
    }
    Ok(())
}

#[test]
fn batch_lengths_track_actual_transfers_without_consuming_on_inspection()
-> Result<(), ContractError> {
    fn assert_fused<I: std::iter::FusedIterator>(_: &I) {}
    for draining in [false, true] {
        for limit in [0, 1, 2, 3, usize::MAX] {
            let plans = [
                plan("SIZED-FIRST", AuthorityState::Authorized)?,
                plan("SIZED-SECOND", AuthorityState::Authorized)?,
            ];
            let mut queue = RuntimeQueue::new(2);
            for pending in &plans {
                queue.submit(pending.clone()).expect("admission");
            }
            if draining {
                queue.begin_drain();
            }
            let count = limit.min(plans.len());
            {
                let mut batch = queue.next_plans(limit);
                assert_fused(&batch);
                for (index, expected) in plans.iter().take(count).enumerate() {
                    for _ in 0..2 {
                        assert_eq!(batch.len(), count - index);
                        assert_eq!(batch.size_hint(), (count - index, Some(count - index)));
                    }
                    assert_eq!(batch.next(), Some(expected.clone()));
                }
                for _ in 0..3 {
                    assert_eq!(batch.len(), 0);
                    assert_eq!(batch.size_hint(), (0, Some(0)));
                    assert_eq!(batch.next(), None);
                }
            }
            assert_eq!(queue.len(), plans.len() - count);
            assert_eq!(
                queue.state(),
                if !draining {
                    QueueState::Running
                } else if count == plans.len() {
                    QueueState::Stopped
                } else {
                    QueueState::Draining
                }
            );
            assert_eq!(
                queue.pending().collect::<Vec<_>>(),
                plans[count..].iter().collect::<Vec<_>>()
            );
        }
    }
    for capacity in [0, usize::MAX] {
        let mut queue = RuntimeQueue::new(capacity);
        assert_eq!(queue.next_plans(usize::MAX).len(), 0);
        assert_eq!(queue.state(), QueueState::Running);
        queue.begin_drain();
        assert_eq!(queue.next_plans(usize::MAX).len(), 0);
        assert_eq!(queue.state(), QueueState::Stopped);
    }
    Ok(())
}

#[test]
fn bounded_transfers_are_lazy_and_preserve_unrequested_fifo_entries() -> Result<(), ContractError> {
    let first = plan("BATCH-FIRST", AuthorityState::Authorized)?;
    let second = plan("BATCH-SECOND", AuthorityState::Authorized)?;
    let third = plan("BATCH-THIRD", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(3);
    for pending in [&first, &second, &third] {
        queue.submit(pending.clone()).expect("admission");
    }
    {
        let _unused = queue.next_plans(usize::MAX);
    }
    assert_eq!(queue.len(), 3);
    assert_eq!(queue.next_plans(0).next(), None);
    assert_eq!(queue.len(), 3);
    {
        let mut batch = queue.next_plans(3);
        assert_eq!(batch.len(), 3);
        assert_eq!(batch.next(), Some(first));
        assert_eq!(batch.len(), 2);
    }
    assert_eq!(queue.len(), 2);
    assert_eq!(queue.state(), QueueState::Running);
    assert_eq!(queue.next_plans(1).collect::<Vec<_>>(), vec![second]);
    assert_eq!(queue.len(), 1);
    assert_eq!(queue.next_plan(), Some(third));
    assert!(queue.is_empty());
    Ok(())
}

#[test]
fn bounded_drain_completes_only_on_actual_last_transfer() -> Result<(), ContractError> {
    let first = plan("DRAIN-BATCH-FIRST", AuthorityState::Authorized)?;
    let second = plan("DRAIN-BATCH-SECOND", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(2);
    queue.submit(first.clone()).expect("admission");
    queue.submit(second.clone()).expect("admission");
    queue.begin_drain();
    assert_eq!(queue.next_plans(0).next(), None);
    assert_eq!(queue.state(), QueueState::Draining);
    assert_eq!(queue.next_plans(1).collect::<Vec<_>>(), vec![first]);
    assert_eq!(queue.state(), QueueState::Draining);
    assert_eq!(queue.len(), 1);
    assert_eq!(
        queue.next_plans(usize::MAX).collect::<Vec<_>>(),
        vec![second]
    );
    assert_eq!(queue.state(), QueueState::Stopped);
    assert_eq!(queue.next_plans(1).next(), None);
    assert_eq!(queue.stop(), 0);
    Ok(())
}

#[test]
fn stop_discards_only_unrequested_batch_remainder() -> Result<(), ContractError> {
    let original = plan("TRANSFER-BEFORE-STOP", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(2);
    queue.submit(original.clone()).expect("first");
    queue.submit(original.clone()).expect("second");
    queue.begin_drain();
    let transferred = queue.next_plans(2).next().expect("first transfer");
    assert_eq!(queue.len(), 1);
    assert_eq!(queue.stop(), 1);
    assert_eq!(transferred, original);
    assert_eq!(queue.next_plans(usize::MAX).next(), None);
    Ok(())
}

#[test]
fn queue_preserves_fifo_and_reuses_freed_capacity() -> Result<(), ContractError> {
    let first = plan("FIRST", AuthorityState::Authorized)?;
    let second = plan("SECOND", AuthorityState::Authorized)?;
    let third = plan("THIRD", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(2);
    assert_eq!(queue.capacity(), 2);
    assert!(queue.is_empty());
    assert!(!queue.is_stopped());
    assert_eq!(queue.next_plan(), None);
    queue.submit(first.clone()).expect("first admission");
    queue.submit(second.clone()).expect("second admission");
    assert_eq!(queue.len(), 2);
    let rejected = queue.submit(third.clone()).expect_err("queue is full");
    assert_eq!(rejected.reason(), AdmissionError::Full);
    assert_eq!(rejected.into_plan(), third);
    assert_eq!(queue.len(), 2);
    assert_eq!(queue.next_plan(), Some(first));
    queue.submit(third.clone()).expect("freed slot");
    assert_eq!(queue.next_plan(), Some(second));
    assert_eq!(queue.next_plan(), Some(third));
    assert!(queue.is_empty());
    Ok(())
}

#[test]
fn non_execute_plans_are_rejected_even_when_full() -> Result<(), ContractError> {
    for capacity in [0, 1] {
        let mut queue = RuntimeQueue::new(capacity);
        if capacity == 1 {
            queue
                .submit(plan("PENDING", AuthorityState::Authorized)?)
                .expect("admission");
        }
        for (authority, reason) in [
            (AuthorityState::Revoked, AdmissionError::Denied),
            (AuthorityState::Expired, AdmissionError::Denied),
            (AuthorityState::InDoubt, AdmissionError::Held),
        ] {
            let original = plan("REJECTED", authority)?;
            let rejected = queue.submit(original.clone()).expect_err("not Execute");
            assert_eq!(rejected.reason(), reason);
            assert_eq!(rejected.into_plan(), original);
            assert_eq!(queue.len(), capacity);
        }
    }
    Ok(())
}

#[test]
fn zero_capacity_never_admits_and_large_capacity_is_not_preallocated() -> Result<(), ContractError>
{
    let mut zero = RuntimeQueue::new(0);
    let rejected = zero
        .submit(plan("ZERO", AuthorityState::Authorized)?)
        .expect_err("zero limit");
    assert_eq!(rejected.reason(), AdmissionError::Full);
    assert!(zero.is_empty());
    let mut large = RuntimeQueue::new(usize::MAX);
    assert!(large.is_empty());
    large
        .submit(rejected.into_plan())
        .expect("one slot is sufficient");
    assert_eq!(large.len(), 1);
    Ok(())
}

#[test]
fn stop_discards_only_pending_plans_and_cannot_be_reversed() -> Result<(), ContractError> {
    let mut queue = RuntimeQueue::new(3);
    let transferred = plan("TRANSFERRED", AuthorityState::Authorized)?;
    queue.submit(transferred.clone()).expect("admission");
    queue
        .submit(plan("PENDING", AuthorityState::Authorized)?)
        .expect("admission");
    let owned = queue.next_plan().expect("oldest plan");
    assert_eq!(queue.stop(), 1);
    assert!(queue.is_stopped());
    assert!(queue.is_empty());
    assert_eq!(queue.next_plan(), None);
    assert_eq!(queue.stop(), 0);
    assert_eq!(owned, transferred);
    for authority in [
        AuthorityState::Authorized,
        AuthorityState::Revoked,
        AuthorityState::Expired,
        AuthorityState::InDoubt,
    ] {
        let original = plan("AFTER-STOP", authority)?;
        let rejected = queue.submit(original.clone()).expect_err("stopped");
        assert_eq!(rejected.reason(), AdmissionError::Stopped);
        assert_eq!(rejected.into_plan(), original);
    }
    Ok(())
}

#[test]
fn repeated_plans_are_distinct_pending_entries() -> Result<(), ContractError> {
    let original = plan("REPEAT", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(2);
    queue.submit(original.clone()).expect("first");
    queue.submit(original.clone()).expect("second");
    assert_eq!(queue.next_plan(), Some(original.clone()));
    assert_eq!(queue.next_plan(), Some(original));
    assert_eq!(queue.next_plan(), None);
    Ok(())
}

#[test]
fn pending_inspection_preserves_fifo_duplicates_and_drain_state()
-> Result<(), Box<dyn std::error::Error>> {
    let first = plan("INSPECT-FIRST", AuthorityState::Authorized)?;
    let second = plan("INSPECT-SECOND", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(3);
    assert_eq!(queue.pending().len(), 0);
    queue.submit(first.clone()).expect("first");
    queue.submit(second.clone()).expect("second");
    assert_eq!(queue.next_plan(), Some(first.clone()));
    queue.submit(first.clone()).expect("reuse freed slot");
    queue.submit(first.clone()).expect("duplicate observation");
    for draining in [false, true] {
        if draining {
            queue.begin_drain();
        }
        let state = queue.state();
        let mut pending = queue.pending();
        assert_eq!(pending.len(), 3);
        assert_eq!(pending.next(), Some(&second));
        assert_eq!(pending.next_back(), Some(&first));
        assert_eq!(pending.len(), 1);
        assert_eq!(pending.next(), Some(&first));
        assert_eq!(pending.next(), None);
        let summary = summarize_plan_iter(queue.pending()).expect("bounded queue");
        assert_eq!(summary.total, 3);
        assert_eq!(summary.execute, 3);
        assert_eq!(summary.contract_valid, 3);
        let mut actual = Vec::new();
        write_plan_inspections_jsonl(queue.pending(), &mut actual)?;
        let mut expected = Vec::new();
        for plan in [&second, &first, &first] {
            write_plan_inspection_json(plan, &mut expected)?;
        }
        assert_eq!(actual, expected);
        assert_eq!(queue.len(), 3);
        assert_eq!(queue.state(), state);
    }
    assert_eq!(queue.next_plan(), Some(second));
    assert_eq!(queue.next_plan(), Some(first.clone()));
    assert_eq!(queue.next_plan(), Some(first));
    assert_eq!(queue.state(), QueueState::Stopped);
    assert_eq!(queue.pending().len(), 0);
    Ok(())
}

#[test]
fn failed_pending_report_does_not_consume_or_stop_the_queue()
-> Result<(), Box<dyn std::error::Error>> {
    struct FailAfter {
        bytes: Vec<u8>,
        remaining: usize,
    }
    impl Write for FailAfter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.remaining == 0 {
                return Err(io::ErrorKind::BrokenPipe.into());
            }
            let count = bytes.len().min(self.remaining);
            self.bytes.extend_from_slice(&bytes[..count]);
            self.remaining -= count;
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            panic!("inspection must not flush");
        }
    }
    let original = plan("UNCONSUMED", AuthorityState::Authorized)?;
    for draining in [false, true] {
        let mut queue = RuntimeQueue::new(1);
        queue.submit(original.clone()).expect("admission");
        if draining {
            queue.begin_drain();
        }
        let state = queue.state();
        let mut output = FailAfter {
            bytes: Vec::new(),
            remaining: 7,
        };
        let error = write_plan_inspections_jsonl(queue.pending(), &mut output)
            .expect_err("partial output failure");
        assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
        assert_eq!(output.bytes.len(), 7);
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.state(), state);
        assert_eq!(queue.next_plan(), Some(original.clone()));
        assert_eq!(
            queue.state(),
            if draining {
                QueueState::Stopped
            } else {
                QueueState::Running
            }
        );
    }
    let mut stopped = RuntimeQueue::new(1);
    stopped.submit(original).expect("admission");
    stopped.stop();
    assert_eq!(stopped.pending().next(), None);
    Ok(())
}

#[test]
fn graceful_drain_closes_admission_and_transfers_fifo_before_stopping() -> Result<(), ContractError>
{
    let first = plan("FIRST-DRAIN", AuthorityState::Authorized)?;
    let second = plan("SECOND-DRAIN", AuthorityState::Authorized)?;
    let mut queue = RuntimeQueue::new(2);
    assert_eq!(queue.state(), QueueState::Running);
    queue.submit(first.clone()).expect("first");
    queue.submit(second.clone()).expect("second");
    queue.begin_drain();
    queue.begin_drain();
    assert_eq!(queue.state(), QueueState::Draining);
    assert!(!queue.is_stopped());
    for authority in [
        AuthorityState::Authorized,
        AuthorityState::Revoked,
        AuthorityState::Expired,
        AuthorityState::InDoubt,
    ] {
        let original = plan("CLOSED", authority)?;
        let rejected = queue
            .submit(original.clone())
            .expect_err("admission closed");
        assert_eq!(rejected.reason(), AdmissionError::Draining);
        assert_eq!(rejected.into_plan(), original);
        assert_eq!(queue.len(), 2);
    }
    assert_eq!(queue.next_plan(), Some(first));
    assert_eq!(queue.state(), QueueState::Draining);
    let rejected = queue
        .submit(second.clone())
        .expect_err("freed slot remains closed");
    assert_eq!(rejected.reason(), AdmissionError::Draining);
    assert_eq!(queue.next_plan(), Some(second));
    assert_eq!(queue.state(), QueueState::Stopped);
    assert!(queue.is_stopped());
    assert!(queue.is_empty());
    queue.begin_drain();
    assert_eq!(queue.next_plan(), None);
    assert_eq!(queue.stop(), 0);
    assert_eq!(queue.state(), QueueState::Stopped);
    let rejected = queue
        .submit(rejected.into_plan())
        .expect_err("cannot restart");
    assert_eq!(rejected.reason(), AdmissionError::Stopped);
    Ok(())
}

#[test]
fn empty_drain_stops_immediately_and_stop_can_interrupt_drain() -> Result<(), ContractError> {
    for capacity in [0, 2] {
        let mut queue = RuntimeQueue::new(capacity);
        queue.begin_drain();
        assert!(queue.is_stopped());
        assert_eq!(queue.state(), QueueState::Stopped);
        assert_eq!(queue.next_plan(), None);
        assert_eq!(queue.stop(), 0);
    }
    let mut queue = RuntimeQueue::new(2);
    queue
        .submit(plan("DISCARD", AuthorityState::Authorized)?)
        .expect("admit");
    queue.begin_drain();
    assert_eq!(queue.state(), QueueState::Draining);
    assert_eq!(queue.stop(), 1);
    queue.begin_drain();
    assert_eq!(queue.state(), QueueState::Stopped);
    assert_eq!(queue.next_plan(), None);
    assert_eq!(queue.stop(), 0);
    Ok(())
}
