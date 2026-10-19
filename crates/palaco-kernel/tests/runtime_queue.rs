use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    scheduling::{AdmissionError, QueueState, RuntimeQueue},
};

fn plan(id: &str, authority: AuthorityState) -> Result<RuntimePlan, ContractError> {
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(
            EventEnvelope::new("synthetic.queue", EvidenceRef::new(id)?),
            authority,
        ),
    )))
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
