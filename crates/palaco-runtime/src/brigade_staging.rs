//! Local BRI9ADE staging diagnostics, never authenticated guard evidence.
//!
//! No network, issuer enrollment, persistence, contact opening or commit path.
//! Host-selected adapters are trusted local code, not downloaded agents.
//! Their assertions, including negative assertions, cannot authorize PASS/STOP.
//! Mode tags reject accidental cross-mode input; they are not physical isolation
//! or authenticated provenance. Use separate host processes and stores for any
//! future real-observation adapter. No such provider adapter is enrolled here.

use std::time::{SystemTime, UNIX_EPOCH};

pub mod key_registry;

/// Logical specialties, not enrolled identities.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    Bg01,
    Bg02,
    Bg03,
    Bg04,
    Bg05,
    Bg06,
    Bg07,
    Bg08,
    Bg09,
}

const ROLES: [Role; 9] = [
    Role::Bg01,
    Role::Bg02,
    Role::Bg03,
    Role::Bg04,
    Role::Bg05,
    Role::Bg06,
    Role::Bg07,
    Role::Bg08,
    Role::Bg09,
];

/// The two independently visible sides of a contact.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Party {
    Sender,
    Recipient,
}

/// Checkpoints are never interchangeable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Checkpoint {
    ServiceCommit,
    QueuedDelivery,
}

/// Physically separate evaluation runs; neither mode authenticates evidence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Synthetic,
    LocalObservation,
}

/// Exact, caller-supplied context. Digests and identities are not authenticated.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Binding {
    pub challenge: String,
    pub contract_digest: String,
    pub sender: String,
    pub recipient: String,
    pub sender_device: String,
    pub recipient_device: String,
    pub tenant_context: String,
    pub policy_version: String,
    pub key_epoch: u64,
    pub checkpoint: Checkpoint,
}

impl Binding {
    fn well_formed(&self) -> bool {
        [
            &self.challenge,
            &self.contract_digest,
            &self.sender,
            &self.recipient,
            &self.sender_device,
            &self.recipient_device,
            &self.tenant_context,
            &self.policy_version,
        ]
        .iter()
        .all(|value| {
            !value.trim().is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
        })
    }
}

/// Unverified adapter assertions, deliberately not guard verdicts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Finding {
    Unknown,
    Positive,
    Negative,
}

/// Diagnostic data only; no signature, enrollment or trust assertion is accepted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Observation {
    pub binding: Binding,
    pub mode: Mode,
    pub role: Role,
    pub party: Party,
    pub issued_at: u64,
    pub expires_at: u64,
    pub finding: Finding,
}

/// Sanitized failures without provider response bodies or identifiers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdapterError {
    Unavailable,
}

/// Interface for bounded local diagnostics supplied by the host.
///
/// Called synchronously once per registration. Implementations must be local,
/// bounded and side-effect-free; no remote adapter or timeout worker is provided.
/// All returned data remains untrusted, even if it claims to be positive.
pub trait ObservationAdapter {
    fn observe(&self, binding: &Binding) -> Result<Observation, AdapterError>;
}

/// Host-owned routing; an adapter cannot select a different control place.
pub struct Registration<'a> {
    pub role: Role,
    pub party: Party,
    pub adapter: &'a dyn ObservationAdapter,
}

/// Explicit lack of verified coverage at each of the eighteen positions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Coverage {
    Unknown,
    Unverified(Finding),
}

/// Sanitized reasons for retaining UNKNOWN, not authenticated FAILs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Issue {
    Missing,
    InvalidInput,
    Unavailable,
    Duplicate,
    WrongBinding,
    WrongMode,
    WrongSlot,
    InvalidTime,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ControlPlace {
    pub role: Role,
    pub party: Party,
    pub coverage: Coverage,
    pub issue: Option<Issue>,
}

/// Read-only diagnostics with no path to the execution RuntimePlan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Report {
    pub mode: Mode,
    pub controls: [ControlPlace; 18],
}

impl Report {
    /// This module cannot verify any enrolled guard or produce PASS/STOP.
    #[must_use]
    pub fn disposition(&self) -> &'static str {
        "HOLD"
    }

    #[must_use]
    pub fn operative_authority(&self) -> &'static str {
        "NONE"
    }

    #[must_use]
    pub fn can_open_contact(&self) -> bool {
        false
    }

    #[must_use]
    pub fn runtime_connected(&self) -> bool {
        false
    }

    #[must_use]
    pub fn external_side_effect(&self) -> bool {
        false
    }
}

/// Actual host wall-clock sample; not proof of trusted time or BG07/BG09 coverage.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockSample {
    pub unix_seconds: u64,
}

impl ClockSample {
    pub fn observe() -> Result<Self, AdapterError> {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| Self {
                unix_seconds: duration.as_secs(),
            })
            .map_err(|_| AdapterError::Unavailable)
    }
}

/// Evaluate a single isolated run without storing or consuming challenges.
///
/// The clock is a local observation, not a trusted freshness assertion.
/// Even complete, timely observations retain HOLD/NONE. Callers must not use
/// this report for contact authorization, enrollment or durable commit.
///
/// ```
/// use palaco_runtime::brigade_staging::{Binding, Checkpoint, ClockSample, Mode, evaluate};
///
/// let context = Binding {
///     challenge: "local-diagnostic".into(),
///     contract_digest: "unverified-context-reference".into(),
///     sender: "staging-sender".into(),
///     recipient: "staging-recipient".into(),
///     sender_device: "staging-device-a".into(),
///     recipient_device: "staging-device-b".into(),
///     tenant_context: "isolated-local-run".into(),
///     policy_version: "design-v0.1".into(),
///     key_epoch: 0,
///     checkpoint: Checkpoint::ServiceCommit,
/// };
/// let report = evaluate(Mode::LocalObservation, &context, ClockSample::observe(), &[]);
/// assert_eq!(report.controls.len(), 18);
/// assert_eq!(report.disposition(), "HOLD");
/// assert!(!report.can_open_contact());
/// ```
#[must_use]
pub fn evaluate(
    mode: Mode,
    binding: &Binding,
    clock: Result<ClockSample, AdapterError>,
    registrations: &[Registration<'_>],
) -> Report {
    let mut report = Report {
        mode,
        controls: std::array::from_fn(|index| ControlPlace {
            role: ROLES[index % 9],
            party: if index < 9 {
                Party::Sender
            } else {
                Party::Recipient
            },
            coverage: Coverage::Unknown,
            issue: Some(Issue::Missing),
        }),
    };
    let Ok(clock) = clock else {
        for control in &mut report.controls {
            control.issue = Some(Issue::Unavailable);
        }
        return report;
    };
    if !binding.well_formed() || registrations.len() > 18 {
        for control in &mut report.controls {
            control.issue = Some(Issue::InvalidInput);
        }
        return report;
    }
    for control in &mut report.controls {
        let mut matching = registrations.iter().filter(|registration| {
            registration.role == control.role && registration.party == control.party
        });
        let Some(registration) = matching.next() else {
            continue;
        };
        if matching.next().is_some() {
            control.issue = Some(Issue::Duplicate);
            continue;
        }
        let observation = match registration.adapter.observe(binding) {
            Ok(observation) => observation,
            Err(_) => {
                control.issue = Some(Issue::Unavailable);
                continue;
            }
        };
        control.issue = if observation.binding != *binding {
            Some(Issue::WrongBinding)
        } else if observation.mode != mode {
            Some(Issue::WrongMode)
        } else if observation.role != control.role || observation.party != control.party {
            Some(Issue::WrongSlot)
        } else if observation.issued_at > clock.unix_seconds
            || observation.expires_at <= clock.unix_seconds
            || observation.issued_at >= observation.expires_at
        {
            Some(Issue::InvalidTime)
        } else {
            None
        };
        if control.issue.is_none() {
            control.coverage = match observation.finding {
                Finding::Unknown => Coverage::Unknown,
                finding => Coverage::Unverified(finding),
            };
        }
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;

    fn binding() -> Binding {
        Binding {
            challenge: "synthetic-challenge".into(),
            contract_digest: "opaque-test-digest-not-canonical".into(),
            sender: "test-sender".into(),
            recipient: "test-recipient".into(),
            sender_device: "test-sender-device".into(),
            recipient_device: "test-recipient-device".into(),
            tenant_context: "test-tenant".into(),
            policy_version: "test-policy".into(),
            key_epoch: 1,
            checkpoint: Checkpoint::ServiceCommit,
        }
    }

    struct Fixture(Result<Observation, AdapterError>);

    impl ObservationAdapter for Fixture {
        fn observe(&self, _: &Binding) -> Result<Observation, AdapterError> {
            self.0.clone()
        }
    }

    fn observation() -> Observation {
        Observation {
            binding: binding(),
            mode: Mode::Synthetic,
            role: Role::Bg01,
            party: Party::Sender,
            issued_at: 90,
            expires_at: 110,
            finding: Finding::Positive,
        }
    }

    fn report(fixture: &Fixture, mode: Mode) -> Report {
        evaluate(
            mode,
            &binding(),
            Ok(ClockSample { unix_seconds: 100 }),
            &[Registration {
                role: Role::Bg01,
                party: Party::Sender,
                adapter: fixture,
            }],
        )
    }

    fn closed(report: &Report) {
        assert_eq!(report.disposition(), "HOLD");
        assert_eq!(report.operative_authority(), "NONE");
        assert!(!report.can_open_contact());
        assert!(!report.runtime_connected());
        assert!(!report.external_side_effect());
    }

    #[test]
    fn missing_controls_are_eighteen_distinct_unknowns() {
        let report = evaluate(
            Mode::LocalObservation,
            &binding(),
            ClockSample::observe(),
            &[],
        );
        closed(&report);
        for (index, control) in report.controls.iter().enumerate() {
            assert_eq!(control.role, ROLES[index % 9]);
            assert_eq!(
                control.party,
                if index < 9 {
                    Party::Sender
                } else {
                    Party::Recipient
                }
            );
            assert_eq!(control.coverage, Coverage::Unknown);
        }
    }

    #[test]
    fn complete_claims_missing_each_slot_and_repeated_reads_remain_closed() {
        let fixtures: Vec<_> = (0..18)
            .map(|index| {
                Fixture(Ok(Observation {
                    role: ROLES[index % 9],
                    party: if index < 9 {
                        Party::Sender
                    } else {
                        Party::Recipient
                    },
                    ..observation()
                }))
            })
            .collect();
        let registrations: Vec<_> = fixtures
            .iter()
            .map(|fixture| {
                let observation = fixture.0.as_ref().expect("test observation");
                Registration {
                    role: observation.role,
                    party: observation.party,
                    adapter: fixture,
                }
            })
            .collect();
        let evaluate_run = |registrations: &[Registration<'_>]| {
            evaluate(
                Mode::Synthetic,
                &binding(),
                Ok(ClockSample { unix_seconds: 100 }),
                registrations,
            )
        };
        let complete = evaluate_run(&registrations);
        closed(&complete);
        assert!(
            complete
                .controls
                .iter()
                .all(|c| c.coverage == Coverage::Unverified(Finding::Positive))
        );
        assert_eq!(complete, evaluate_run(&registrations));
        for missing in 0..18 {
            let remaining: Vec<_> = registrations
                .iter()
                .enumerate()
                .filter(|(index, _)| *index != missing)
                .map(|(_, registration)| Registration {
                    role: registration.role,
                    party: registration.party,
                    adapter: registration.adapter,
                })
                .collect();
            let report = evaluate_run(&remaining);
            closed(&report);
            assert_eq!(report.controls[missing].coverage, Coverage::Unknown);
            assert_eq!(report.controls[missing].issue, Some(Issue::Missing));
        }
    }

    #[test]
    fn untrusted_positive_and_negative_never_produce_pass_or_stop() {
        for mode in [Mode::Synthetic, Mode::LocalObservation] {
            for finding in [Finding::Positive, Finding::Negative, Finding::Unknown] {
                let fixture = Fixture(Ok(Observation {
                    mode,
                    finding,
                    ..observation()
                }));
                let report = report(&fixture, mode);
                closed(&report);
                assert_eq!(report.controls[0].issue, None);
                assert_eq!(
                    report.controls[0].coverage,
                    match finding {
                        Finding::Unknown => Coverage::Unknown,
                        finding => Coverage::Unverified(finding),
                    }
                );
                assert!(
                    report.controls[1..]
                        .iter()
                        .all(|c| c.coverage == Coverage::Unknown)
                );
            }
        }
    }

    #[test]
    fn every_context_field_and_checkpoint_is_exactly_bound() {
        let original = binding();
        let mut variants = Vec::new();
        for field in 0..8 {
            let mut changed = original.clone();
            [
                &mut changed.challenge,
                &mut changed.contract_digest,
                &mut changed.sender,
                &mut changed.recipient,
                &mut changed.sender_device,
                &mut changed.recipient_device,
                &mut changed.tenant_context,
                &mut changed.policy_version,
            ][field]
                .push('x');
            variants.push(changed);
        }
        variants.push(Binding {
            key_epoch: 2,
            ..original.clone()
        });
        variants.push(Binding {
            checkpoint: Checkpoint::QueuedDelivery,
            ..original
        });
        for binding in variants {
            let report = report(
                &Fixture(Ok(Observation {
                    binding,
                    ..observation()
                })),
                Mode::Synthetic,
            );
            closed(&report);
            assert_eq!(report.controls[0].issue, Some(Issue::WrongBinding));
            assert_eq!(report.controls[0].coverage, Coverage::Unknown);
        }
    }

    #[test]
    fn mode_and_slot_spoofing_are_unknown() {
        for (changed, issue) in [
            (
                Observation {
                    mode: Mode::LocalObservation,
                    ..observation()
                },
                Issue::WrongMode,
            ),
            (
                Observation {
                    role: Role::Bg09,
                    ..observation()
                },
                Issue::WrongSlot,
            ),
            (
                Observation {
                    party: Party::Recipient,
                    ..observation()
                },
                Issue::WrongSlot,
            ),
        ] {
            let report = report(&Fixture(Ok(changed)), Mode::Synthetic);
            closed(&report);
            assert_eq!(report.controls[0].issue, Some(issue));
            assert_eq!(report.controls[0].coverage, Coverage::Unknown);
        }
    }

    #[test]
    fn expiry_future_time_and_unavailable_adapters_fail_closed() {
        for (issued_at, expires_at) in [(90, 100), (101, 110), (100, 100), (110, 90)] {
            let report = report(
                &Fixture(Ok(Observation {
                    issued_at,
                    expires_at,
                    ..observation()
                })),
                Mode::Synthetic,
            );
            closed(&report);
            assert_eq!(report.controls[0].issue, Some(Issue::InvalidTime));
        }
        let report = report(&Fixture(Err(AdapterError::Unavailable)), Mode::Synthetic);
        assert_eq!(report.controls[0].issue, Some(Issue::Unavailable));
        closed(&report);
    }

    #[test]
    fn duplicate_slots_and_excess_registrations_are_rejected() {
        let fixture = Fixture(Ok(observation()));
        let registrations: Vec<_> = (0..19)
            .map(|_| Registration {
                role: Role::Bg01,
                party: Party::Sender,
                adapter: &fixture,
            })
            .collect();
        for count in [2, 19] {
            let report = evaluate(
                Mode::Synthetic,
                &binding(),
                Ok(ClockSample { unix_seconds: 100 }),
                &registrations[..count],
            );
            closed(&report);
            assert_eq!(
                report.controls[0].issue,
                Some(if count == 2 {
                    Issue::Duplicate
                } else {
                    Issue::InvalidInput
                })
            );
            assert!(
                report
                    .controls
                    .iter()
                    .all(|c| c.coverage == Coverage::Unknown)
            );
        }
    }

    #[test]
    fn invalid_binding_or_missing_clock_does_not_invoke_adapter() {
        struct Never;
        impl ObservationAdapter for Never {
            fn observe(&self, _: &Binding) -> Result<Observation, AdapterError> {
                panic!("invalid run must not invoke adapter")
            }
        }
        for challenge in ["", " ", "bad\ncontext", &"x".repeat(257)] {
            let binding = Binding {
                challenge: challenge.into(),
                ..binding()
            };
            let report = evaluate(
                Mode::Synthetic,
                &binding,
                Ok(ClockSample { unix_seconds: 100 }),
                &[Registration {
                    role: Role::Bg01,
                    party: Party::Sender,
                    adapter: &Never,
                }],
            );
            closed(&report);
            assert!(
                report
                    .controls
                    .iter()
                    .all(|c| c.issue == Some(Issue::InvalidInput))
            );
        }
        let report = evaluate(
            Mode::Synthetic,
            &binding(),
            Err(AdapterError::Unavailable),
            &[Registration {
                role: Role::Bg01,
                party: Party::Sender,
                adapter: &Never,
            }],
        );
        assert!(
            report
                .controls
                .iter()
                .all(|c| c.issue == Some(Issue::Unavailable))
        );
    }
}
