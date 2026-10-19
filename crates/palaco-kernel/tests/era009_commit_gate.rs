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
fn recorded_inputs_survive_caller_mutation_and_drop() {
    let gate = InMemoryCommitGate::with_record_limit(1);
    let receipt = {
        let request_key = key("owned-request");
        let mut supplied_boundary = boundary("original-evidence", AuthorityState::Authorized);
        let mut payload = vec![0, 255, 128, 0];
        let receipt = gate
            .commit(&request_key, &supplied_boundary, &payload)
            .expect("record original inputs");
        payload[1] = 254;
        assert_eq!(
            gate.commit(&request_key, &supplied_boundary, &payload),
            Err(CommitGateError::IdempotencyConflict)
        );
        supplied_boundary = boundary("replacement-evidence", AuthorityState::Authorized);
        assert_eq!(
            gate.commit_with_outcome(&request_key, &supplied_boundary, &[0, 255, 128, 0]),
            Err(CommitGateError::IdempotencyConflict)
        );
        receipt
    };
    assert_eq!(receipt.sequence(), 1);
    assert_eq!(gate.revoke(), Ok(2));
    let reconstructed_key = key("owned-request");
    let reconstructed_boundary = boundary("original-evidence", AuthorityState::Authorized);
    let reconstructed_payload = vec![0, 255, 128, 0];
    assert_eq!(
        gate.commit_with_outcome(
            &reconstructed_key,
            &reconstructed_boundary,
            &reconstructed_payload,
        ),
        Ok(CommitOutcome::Replayed(receipt))
    );
    assert_eq!(
        gate.commit(
            &reconstructed_key,
            &reconstructed_boundary,
            &reconstructed_payload
        ),
        Ok(receipt)
    );
}

#[test]
fn binary_payloads_are_compared_exactly_without_truncation_or_normalization() {
    let gate = InMemoryCommitGate::new();
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    let request_key = key("binary");
    let original = [0, 255, 128, 0];
    let receipt = gate
        .commit(&request_key, &authorized, &original)
        .expect("record");
    let alternatives: &[&[u8]] = &[
        &[],
        &[0],
        &[0, 255, 128],
        &[0, 255, 128, 0, 0],
        &[0, 254, 128, 0],
        &[0, 255, 129, 0],
    ];
    for revoked in [false, true] {
        if revoked {
            assert_eq!(gate.revoke(), Ok(2));
        }
        for payload in alternatives {
            assert_eq!(
                gate.commit(&request_key, &authorized, payload),
                Err(CommitGateError::IdempotencyConflict)
            );
            assert_eq!(
                gate.commit_with_outcome(&request_key, &authorized, payload),
                Err(CommitGateError::IdempotencyConflict)
            );
        }
        assert_eq!(
            gate.commit_with_outcome(&request_key, &authorized, &original),
            Ok(CommitOutcome::Replayed(receipt))
        );
    }
    assert_eq!(gate.revoke(), Ok(2));
}

#[test]
fn idempotency_keys_preserve_case_whitespace_and_unicode_encoding() {
    let gate = InMemoryCommitGate::new();
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    let identifiers = [
        "request", "Request", " request", "request ", "\u{e9}", "e\u{301}",
    ];
    let mut receipts = Vec::new();
    for (index, identifier) in identifiers.iter().enumerate() {
        let receipt = gate
            .commit(&key(identifier), &authorized, b"payload")
            .expect("distinct key");
        assert_eq!(receipt.sequence(), index as u64 + 1);
        receipts.push(receipt);
    }
    assert_eq!(gate.revoke(), Ok(identifiers.len() as u64 + 1));
    for (identifier, receipt) in identifiers.iter().zip(receipts) {
        assert_eq!(
            gate.commit_with_outcome(&key(identifier), &authorized, b"payload"),
            Ok(CommitOutcome::Replayed(receipt))
        );
    }
}

#[test]
fn record_limit_preserves_retries_conflicts_and_revocation() {
    let gate = InMemoryCommitGate::with_record_limit(1);
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    let receipt = gate
        .commit(&key("first"), &authorized, b"payload")
        .expect("first record fits");
    assert_eq!(receipt.sequence(), 1);
    for _ in 0..2 {
        assert_eq!(
            gate.commit(&key("next"), &authorized, b"payload"),
            Err(CommitGateError::RecordLimitReached)
        );
        assert_eq!(
            gate.commit_with_outcome(&key("next"), &authorized, b"payload"),
            Err(CommitGateError::RecordLimitReached)
        );
    }
    assert_eq!(
        gate.commit_with_outcome(&key("first"), &authorized, b"payload"),
        Ok(CommitOutcome::Replayed(receipt))
    );
    assert_eq!(
        gate.commit(&key("first"), &authorized, b"changed"),
        Err(CommitGateError::IdempotencyConflict)
    );
    assert_eq!(
        gate.commit(
            &key("next"),
            &boundary("evidence-1", AuthorityState::InDoubt),
            b"payload",
        ),
        Err(CommitGateError::InvalidBoundary(
            ContractError::AuthorityInDoubt
        ))
    );
    assert_eq!(gate.revoke(), Ok(2));
    assert_eq!(gate.revoke(), Ok(2));
    assert_eq!(
        gate.commit_with_outcome(&key("first"), &authorized, b"payload"),
        Ok(CommitOutcome::Replayed(receipt))
    );
    assert_eq!(
        gate.commit(&key("next"), &authorized, b"payload"),
        Err(CommitGateError::Revoked)
    );
}

#[test]
fn zero_record_limit_allows_revocation_without_consuming_commit_sequences() {
    let gate = InMemoryCommitGate::with_record_limit(0);
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    assert_eq!(
        gate.commit_with_outcome(&key("first"), &authorized, b""),
        Err(CommitGateError::RecordLimitReached)
    );
    assert_eq!(gate.revoke(), Ok(1));
    assert_eq!(
        gate.commit(&key("first"), &authorized, b""),
        Err(CommitGateError::Revoked)
    );
}

#[test]
fn concurrent_unique_keys_cannot_exceed_the_record_limit() {
    let gate = Arc::new(InMemoryCommitGate::with_record_limit(3));
    let barrier = Arc::new(Barrier::new(8));
    let threads: Vec<_> = (0..8)
        .map(|index| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                let request_key = key(&format!("key-{index}"));
                barrier.wait();
                let result = gate.commit_with_outcome(
                    &request_key,
                    &boundary("evidence-1", AuthorityState::Authorized),
                    b"payload",
                );
                (request_key, result)
            })
        })
        .collect();
    let mut admitted = Vec::new();
    let mut rejected = 0;
    for thread in threads {
        let (request_key, result) = thread.join().expect("worker");
        match result {
            Ok(CommitOutcome::Recorded(receipt)) => admitted.push((request_key, receipt)),
            Ok(CommitOutcome::Replayed(_)) => panic!("unique request cannot replay"),
            Err(error) => {
                assert_eq!(error, CommitGateError::RecordLimitReached);
                rejected += 1;
            }
        }
    }
    assert_eq!((admitted.len(), rejected), (3, 5));
    admitted.sort_unstable_by_key(|(_, receipt)| receipt.sequence());
    assert_eq!(
        admitted
            .iter()
            .map(|(_, receipt)| receipt.sequence())
            .collect::<Vec<_>>(),
        vec![1, 2, 3]
    );
    assert_eq!(gate.revoke(), Ok(4));
    for (request_key, receipt) in admitted {
        assert_eq!(
            gate.commit_with_outcome(
                &request_key,
                &boundary("evidence-1", AuthorityState::Authorized),
                b"payload",
            ),
            Ok(CommitOutcome::Replayed(receipt))
        );
    }
}

#[test]
fn identical_retries_share_the_last_record_slot() {
    for limit in [1, 2] {
        let gate = Arc::new(InMemoryCommitGate::with_record_limit(limit));
        let authorized = boundary("evidence-1", AuthorityState::Authorized);
        for index in 0..limit - 1 {
            gate.commit(&key(&format!("prefill-{index}")), &authorized, b"payload")
                .expect("prefill leaves one slot");
        }
        let barrier = Arc::new(Barrier::new(8));
        let threads: Vec<_> = (0..8)
            .map(|_| {
                let gate = Arc::clone(&gate);
                let barrier = Arc::clone(&barrier);
                let authorized = authorized.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    gate.commit_with_outcome(&key("last-slot"), &authorized, b"payload")
                })
            })
            .collect();
        let mut recorded = 0;
        let mut replayed = 0;
        for thread in threads {
            let outcome = thread.join().expect("worker").expect("record or retry");
            assert_eq!(outcome.receipt().sequence(), limit as u64);
            match outcome {
                CommitOutcome::Recorded(_) => recorded += 1,
                CommitOutcome::Replayed(_) => replayed += 1,
            }
        }
        assert_eq!((recorded, replayed), (1, 7));
        assert_eq!(
            gate.commit(&key("overflow"), &authorized, b"payload"),
            Err(CommitGateError::RecordLimitReached)
        );
        assert_eq!(gate.revoke(), Ok(limit as u64 + 1));
        let outcome = gate
            .commit_with_outcome(&key("last-slot"), &authorized, b"payload")
            .expect("full revoked gate preserves retry");
        assert!(matches!(outcome, CommitOutcome::Replayed(_)));
        assert_eq!(outcome.receipt().sequence(), limit as u64);
    }
}

#[test]
fn bounded_histories_match_an_independent_accepted_event_log() {
    let boundaries = [
        boundary("evidence-1", AuthorityState::Authorized),
        boundary("evidence-2", AuthorityState::Authorized),
        boundary("evidence-1", AuthorityState::Revoked),
        boundary("evidence-1", AuthorityState::Expired),
        boundary("evidence-1", AuthorityState::InDoubt),
    ];
    let authority_errors = [
        None,
        None,
        Some(ContractError::RevokedAuthority),
        Some(ContractError::ExpiredAuthority),
        Some(ContractError::AuthorityInDoubt),
    ];
    let keys = [key("key-1"), key("key-2")];
    let payloads: [&[u8]; 2] = [b"payload", b"changed"];
    let requests = [
        (0, 0, 0),
        (0, 1, 0),
        (1, 0, 0),
        (0, 0, 1),
        (0, 0, 2),
        (0, 0, 3),
        (0, 0, 4),
    ];
    let revoke = requests.len();
    let alphabet = revoke + 1;
    let histories_per_limit = alphabet.pow(5);
    let limits = [None, Some(0), Some(1), Some(2)];
    // Event positions, not mutable gate counters, define expected sequences.
    for history in 0..histories_per_limit * limits.len() {
        let limit = limits[history / histories_per_limit];
        let create_gate = || match limit {
            Some(limit) => InMemoryCommitGate::with_record_limit(limit),
            None => InMemoryCommitGate::new(),
        };
        let explicit = create_gate();
        let legacy = create_gate();
        let mut accepted: Vec<usize> = Vec::new();
        let mut remaining = history % histories_per_limit;
        for step in 0..5 {
            let operation = remaining % alphabet;
            remaining /= alphabet;
            if operation == revoke {
                let position = match accepted.iter().position(|event| *event == revoke) {
                    Some(position) => position,
                    None => {
                        accepted.push(revoke);
                        accepted.len() - 1
                    }
                };
                let expected = Ok(position as u64 + 1);
                assert_eq!(
                    explicit.revoke(),
                    expected,
                    "history={history}, step={step}"
                );
                assert_eq!(legacy.revoke(), expected, "history={history}, step={step}");
                continue;
            }
            let (key_index, payload_index, boundary_index) = requests[operation];
            let prior = accepted
                .iter()
                .position(|event| *event != revoke && requests[*event].0 == key_index);
            let expected = if let Some(error) = authority_errors[boundary_index] {
                Err(CommitGateError::InvalidBoundary(error))
            } else if let Some(position) = prior {
                if requests[accepted[position]] == requests[operation] {
                    Ok((position as u64 + 1, false))
                } else {
                    Err(CommitGateError::IdempotencyConflict)
                }
            } else if accepted.contains(&revoke) {
                Err(CommitGateError::Revoked)
            } else if limit.is_some_and(|limit| accepted.len() >= limit) {
                Err(CommitGateError::RecordLimitReached)
            } else {
                accepted.push(operation);
                Ok((accepted.len() as u64, true))
            };
            let actual = explicit
                .commit_with_outcome(
                    &keys[key_index],
                    &boundaries[boundary_index],
                    payloads[payload_index],
                )
                .map(|outcome| {
                    (
                        outcome.receipt().sequence(),
                        matches!(outcome, CommitOutcome::Recorded(_)),
                    )
                });
            assert_eq!(actual, expected, "history={history}, step={step}");
            assert_eq!(
                legacy
                    .commit(
                        &keys[key_index],
                        &boundaries[boundary_index],
                        payloads[payload_index],
                    )
                    .map(|receipt| receipt.sequence()),
                expected.map(|(sequence, _)| sequence),
                "legacy history={history}, step={step}"
            );
        }
        let revoked_at = accepted
            .iter()
            .position(|event| *event == revoke)
            .map_or(accepted.len() as u64 + 1, |position| position as u64 + 1);
        assert_eq!(explicit.revoke(), Ok(revoked_at), "history={history}");
        assert_eq!(legacy.revoke(), Ok(revoked_at), "history={history}");
        for (position, operation) in accepted.iter().enumerate() {
            if *operation == revoke {
                continue;
            }
            let (key_index, payload_index, boundary_index) = requests[*operation];
            let outcome = explicit
                .commit_with_outcome(
                    &keys[key_index],
                    &boundaries[boundary_index],
                    payloads[payload_index],
                )
                .expect("accepted record must remain replayable after revocation");
            assert!(matches!(outcome, CommitOutcome::Replayed(_)));
            assert_eq!(outcome.receipt().sequence(), position as u64 + 1);
            assert_eq!(
                legacy
                    .commit(
                        &keys[key_index],
                        &boundaries[boundary_index],
                        payloads[payload_index],
                    )
                    .expect("legacy retry remains available after revocation")
                    .sequence(),
                position as u64 + 1
            );
        }
    }
}

#[test]
fn concurrent_revokers_share_one_position_with_mixed_api_commits() {
    let gate = Arc::new(InMemoryCommitGate::new());
    let authorized = boundary("evidence-1", AuthorityState::Authorized);
    let original = gate
        .commit(&key("original"), &authorized, b"payload")
        .expect("initial record");
    let barrier = Arc::new(Barrier::new(12));
    let revokers: Vec<_> = (0..4)
        .map(|_| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                gate.revoke()
            })
        })
        .collect();
    let committers: Vec<_> = (0..8)
        .map(|index| {
            let gate = Arc::clone(&gate);
            let barrier = Arc::clone(&barrier);
            let authorized = authorized.clone();
            std::thread::spawn(move || {
                let request_key = key(&format!("key-{index}"));
                barrier.wait();
                if index % 2 == 0 {
                    gate.commit(&request_key, &authorized, b"payload")
                } else {
                    gate.commit_with_outcome(&request_key, &authorized, b"payload")
                        .map(|outcome| {
                            assert!(matches!(outcome, CommitOutcome::Recorded(_)));
                            outcome.receipt()
                        })
                }
            })
        })
        .collect();
    let revoked_at = revokers
        .into_iter()
        .map(|thread| thread.join().expect("revoker").expect("revoke"))
        .collect::<Vec<_>>();
    assert!(revoked_at.iter().all(|position| *position == revoked_at[0]));
    let revoked_at = revoked_at[0];
    let mut sequences = vec![original.sequence()];
    for thread in committers {
        match thread.join().expect("committer") {
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
    assert_eq!(
        gate.commit_with_outcome(&key("original"), &authorized, b"payload"),
        Ok(CommitOutcome::Replayed(original))
    );
    assert_eq!(
        gate.commit(&key("after-revocation"), &authorized, b"payload"),
        Err(CommitGateError::Revoked)
    );
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
