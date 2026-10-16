use std::sync::{Arc, Barrier};

use palaco_citadel::{CommitGateError, CommitOutcome, ExecutionBoundary, InMemoryCommitGate};
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, ContractError, EvidenceRef};
use palaco_quay::ProvenanceRecord;

fn key(value: &str) -> EvidenceRef {
    EvidenceRef::new(value).expect("test reference must be nonempty")
}

fn boundary(evidence: &str, authority: AuthorityState) -> ExecutionBoundary {
    ExecutionBoundary::new(ProvenanceRecord::new(
        EventEnvelope::new("execution.requested", key(evidence)),
        authority,
    ))
}

#[test]
fn explicit_outcomes_preserve_receipts_across_both_apis_and_revocation() {
    let gate = InMemoryCommitGate::new();
    let boundary = boundary("evidence-1", AuthorityState::Authorized);
    let outcome = gate
        .commit_with_outcome(&key("key-1"), &boundary, b"payload")
        .expect("record");
    let receipt = outcome.receipt();
    assert_eq!(outcome, CommitOutcome::Recorded(receipt));
    assert_eq!(receipt.sequence(), 1);
    assert_eq!(
        gate.commit(&key("key-1"), &boundary, b"payload"),
        Ok(receipt)
    );
    assert_eq!(
        gate.commit_with_outcome(&key("key-1"), &boundary, b"payload"),
        Ok(CommitOutcome::Replayed(receipt))
    );
    let legacy_receipt = gate
        .commit(&key("key-2"), &boundary, b"legacy")
        .expect("legacy record");
    assert_eq!(legacy_receipt.sequence(), 2);
    assert_eq!(
        gate.commit_with_outcome(&key("key-2"), &boundary, b"legacy"),
        Ok(CommitOutcome::Replayed(legacy_receipt))
    );
    assert_eq!(gate.revoke(), Ok(3));
    assert_eq!(
        gate.commit_with_outcome(&key("key-1"), &boundary, b"payload"),
        Ok(CommitOutcome::Replayed(receipt))
    );
    assert_eq!(
        gate.commit_with_outcome(&key("key-2"), &boundary, b"legacy"),
        Ok(CommitOutcome::Replayed(legacy_receipt))
    );
    assert_eq!(gate.revoke(), Ok(3));
}

#[test]
fn both_apis_preserve_error_precedence_without_consuming_sequences() {
    let gate = InMemoryCommitGate::new();
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    gate.commit(&key("key-1"), &authorized, b"payload")
        .expect("commit");
    for (authority, error) in [
        (AuthorityState::Revoked, ContractError::RevokedAuthority),
        (AuthorityState::Expired, ContractError::ExpiredAuthority),
        (AuthorityState::InDoubt, ContractError::AuthorityInDoubt),
    ] {
        let invalid = boundary("evidence-1", authority);
        assert_eq!(
            gate.commit_with_outcome(&key("key-1"), &invalid, b"payload"),
            Err(CommitGateError::InvalidBoundary(error))
        );
    }
    for revoked in [false, true] {
        if revoked {
            assert_eq!(gate.revoke(), Ok(2));
        }
        for request in [
            (&authorized, b"changed".as_slice()),
            (
                &boundary("different-evidence", AuthorityState::Authorized),
                b"payload".as_slice(),
            ),
            (
                &boundary("evidence-1", AuthorityState::Revoked),
                b"payload".as_slice(),
            ),
        ] {
            assert_eq!(
                gate.commit_with_outcome(&key("key-1"), request.0, request.1)
                    .map(CommitOutcome::receipt),
                gate.commit(&key("key-1"), request.0, request.1)
            );
        }
    }
    assert_eq!(
        gate.commit_with_outcome(&key("new-key"), &authorized, b"payload"),
        Err(CommitGateError::Revoked)
    );
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn concurrent_outcomes_classify_exactly_one_record_and_preserve_conflicts() {
    let gate = Arc::new(InMemoryCommitGate::new());
    let barrier = Arc::new(Barrier::new(8));
    let threads: Vec<_> = (0..8)
        .map(|_| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                gate.commit_with_outcome(
                    &key("same-key"),
                    &boundary("evidence-1", AuthorityState::Authorized),
                    b"payload",
                )
            })
        })
        .collect();
    let mut recorded = 0;
    let mut replayed = 0;
    for thread in threads {
        let outcome = thread.join().expect("worker").expect("commit");
        assert_eq!(outcome.receipt().sequence(), 1);
        match outcome {
            CommitOutcome::Recorded(_) => recorded += 1,
            CommitOutcome::Replayed(_) => replayed += 1,
        }
    }
    assert_eq!((recorded, replayed), (1, 7));
    assert_eq!(
        gate.commit_with_outcome(
            &key("same-key"),
            &boundary("evidence-1", AuthorityState::Authorized),
            b"different",
        ),
        Err(CommitGateError::IdempotencyConflict)
    );
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn retries_are_exact_and_do_not_advance_the_local_order() {
    let gate = InMemoryCommitGate::new();
    let boundary = boundary("evidence-1", AuthorityState::Authorized);
    let first = gate
        .commit(&key("key-1"), &boundary, b"payload")
        .expect("commit");
    assert_eq!(first.sequence(), 1);
    assert_eq!(gate.commit(&key("key-1"), &boundary, b"payload"), Ok(first));
    assert_eq!(
        gate.commit(&key("key-1"), &boundary, b"changed"),
        Err(CommitGateError::IdempotencyConflict)
    );
    assert_eq!(
        gate.commit(
            &key("key-1"),
            &crate::boundary("evidence-2", AuthorityState::Authorized),
            b"payload",
        ),
        Err(CommitGateError::IdempotencyConflict)
    );
    let changed_topic = ExecutionBoundary::new(ProvenanceRecord::new(
        EventEnvelope::new("different.topic", key("evidence-1")),
        AuthorityState::Authorized,
    ));
    assert_eq!(
        gate.commit(&key("key-1"), &changed_topic, b"payload"),
        Err(CommitGateError::IdempotencyConflict)
    );
    assert_eq!(
        gate.commit(&key("key-2"), &boundary, b"")
            .expect("second commit")
            .sequence(),
        2
    );
    assert_eq!(gate.revoke(), Ok(3));
}

#[test]
fn revocation_blocks_new_commits_but_preserves_historical_receipts() {
    let gate = InMemoryCommitGate::new();
    let boundary = boundary("evidence-1", AuthorityState::Authorized);
    let receipt = gate
        .commit(&key("key-1"), &boundary, b"payload")
        .expect("commit");
    assert_eq!(gate.revoke(), Ok(2));
    assert_eq!(gate.revoke(), Ok(2));
    assert_eq!(
        gate.commit(&key("key-1"), &boundary, b"payload"),
        Ok(receipt)
    );
    assert_eq!(
        gate.commit(&key("key-1"), &boundary, b"changed"),
        Err(CommitGateError::IdempotencyConflict)
    );
    assert_eq!(
        gate.commit(&key("key-2"), &boundary, b"payload"),
        Err(CommitGateError::Revoked)
    );
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn revoke_before_any_commit_and_independent_instances() {
    let gate = InMemoryCommitGate::new();
    let boundary = boundary("evidence-1", AuthorityState::Authorized);
    assert_eq!(gate.revoke(), Ok(1));
    assert_eq!(
        gate.commit(&key("key-1"), &boundary, b"payload"),
        Err(CommitGateError::Revoked)
    );
    let independent = InMemoryCommitGate::new();
    assert_eq!(
        independent
            .commit(&key("key-1"), &boundary, b"payload")
            .expect("independent commit")
            .sequence(),
        1
    );
}

#[test]
fn unauthorized_requests_never_consume_keys_or_sequences() {
    let gate = InMemoryCommitGate::new();
    for (authority, error) in [
        (AuthorityState::Revoked, ContractError::RevokedAuthority),
        (AuthorityState::Expired, ContractError::ExpiredAuthority),
        (AuthorityState::InDoubt, ContractError::AuthorityInDoubt),
    ] {
        assert_eq!(
            gate.commit(
                &key("key-1"),
                &boundary("evidence-1", authority),
                b"payload"
            ),
            Err(CommitGateError::InvalidBoundary(error))
        );
    }
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    assert_eq!(
        gate.commit(&key("key-1"), &authorized, b"payload")
            .expect("authorized commit")
            .sequence(),
        1
    );
    assert_eq!(
        gate.commit(
            &key("key-1"),
            &boundary("evidence-1", AuthorityState::Revoked),
            b"payload",
        ),
        Err(CommitGateError::InvalidBoundary(
            ContractError::RevokedAuthority
        ))
    );
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn concurrent_identical_retries_share_one_sequence() {
    let gate = Arc::new(InMemoryCommitGate::new());
    let barrier = Arc::new(Barrier::new(8));
    let threads: Vec<_> = (0..8)
        .map(|_| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                gate.commit(
                    &key("same-key"),
                    &boundary("evidence-1", AuthorityState::Authorized),
                    b"payload",
                )
            })
        })
        .collect();
    for thread in threads {
        assert_eq!(
            thread.join().expect("worker").expect("commit").sequence(),
            1
        );
    }
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn concurrent_conflicting_retries_choose_only_one_payload() {
    let gate = Arc::new(InMemoryCommitGate::new());
    let barrier = Arc::new(Barrier::new(8));
    let threads: Vec<_> = (0_u8..8)
        .map(|payload| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                let result = gate.commit(
                    &key("same-key"),
                    &boundary("evidence-1", AuthorityState::Authorized),
                    &[payload],
                );
                (payload, result)
            })
        })
        .collect();
    let mut winners = Vec::new();
    for thread in threads {
        let (payload, result) = thread.join().expect("worker");
        match result {
            Ok(receipt) => {
                assert_eq!(receipt.sequence(), 1);
                winners.push((payload, receipt));
            }
            Err(error) => assert_eq!(error, CommitGateError::IdempotencyConflict),
        }
    }
    assert_eq!(winners.len(), 1);
    let (payload, receipt) = winners[0];
    assert_eq!(
        gate.commit(
            &key("same-key"),
            &boundary("evidence-1", AuthorityState::Authorized),
            &[payload],
        ),
        Ok(receipt)
    );
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn racing_commits_and_revocation_obey_one_local_order() {
    let gate = Arc::new(InMemoryCommitGate::new());
    let barrier = Arc::new(Barrier::new(9));
    let commits: Vec<_> = (0..8)
        .map(|index| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                gate.commit(
                    &key(&format!("key-{index}")),
                    &boundary("evidence-1", AuthorityState::Authorized),
                    b"payload",
                )
            })
        })
        .collect();
    barrier.wait();
    let revoked_at = gate.revoke().expect("revoke");
    let mut sequences = Vec::new();
    for thread in commits {
        match thread.join().expect("worker") {
            Ok(receipt) => {
                assert!(receipt.sequence() < revoked_at);
                sequences.push(receipt.sequence());
            }
            Err(error) => assert_eq!(error, CommitGateError::Revoked),
        }
    }
    sequences.sort_unstable();
    assert_eq!(sequences, (1..revoked_at).collect::<Vec<_>>());
    assert_eq!(gate.revoke(), Ok(revoked_at));
}
