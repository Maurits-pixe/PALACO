use std::{cell::RefCell, error::Error, rc::Rc};

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef, Validatable};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginError,
        PluginEventKind, PluginHealth, PluginId, PluginManager, PluginOutcome, PluginRegistration,
        PluginState,
    },
};

type TestResult = Result<(), Box<dyn Error>>;
type Log = Rc<RefCell<Vec<String>>>;

#[derive(Default)]
struct Behavior {
    fail: Option<PluginAction>,
    panic: Option<PluginAction>,
    not_ready: bool,
    cleanup_failures: usize,
    resume_readiness: Option<PluginOutcome>,
    health: Option<Rc<RefCell<PluginOutcome>>>,
}

struct Probe {
    log: Log,
    behavior: Behavior,
}

impl Probe {
    fn call(&self, context: &PluginContext<'_>, action: PluginAction) -> Result<(), String> {
        assert_eq!(context.evidence.as_str(), "plugin-evidence");
        self.log
            .borrow_mut()
            .push(format!("{}:{action:?}", context.id.as_str()));
        assert_ne!(self.behavior.panic, Some(action), "test callback panic");
        if self.behavior.fail == Some(action) {
            return Err("test callback failure".into());
        }
        Ok(())
    }
}

impl Plugin for Probe {
    fn initialize(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(context, PluginAction::Initialize)
    }

    fn start(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(context, PluginAction::Start)
    }

    fn readiness(&mut self, context: &PluginContext<'_>) -> Result<bool, String> {
        self.call(context, PluginAction::Readiness)?;
        if let Some(health) = &self.behavior.health {
            return match *health.borrow() {
                PluginOutcome::NotReady => Ok(false),
                PluginOutcome::Error => Err("private-health-secret".into()),
                PluginOutcome::Panicked => panic!("private-health-secret"),
                _ => Ok(true),
            };
        }
        Ok(!self.behavior.not_ready)
    }

    fn pause(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(context, PluginAction::Pause)
    }

    fn resume(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(context, PluginAction::Resume)?;
        match self.behavior.resume_readiness {
            Some(PluginOutcome::Error) => self.behavior.fail = Some(PluginAction::Readiness),
            Some(PluginOutcome::Panicked) => self.behavior.panic = Some(PluginAction::Readiness),
            Some(PluginOutcome::NotReady) => self.behavior.not_ready = true,
            _ => {}
        }
        Ok(())
    }

    fn stop(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(context, PluginAction::Stop)?;
        if self.behavior.cleanup_failures > 0 {
            self.behavior.cleanup_failures -= 1;
            return Err("retry cleanup".into());
        }
        Ok(())
    }
}

fn registration(
    name: &str,
    dependencies: &[&str],
    log: &Log,
    behavior: Behavior,
) -> Result<PluginRegistration, Box<dyn Error>> {
    Ok(PluginRegistration {
        descriptor: PluginDescriptor {
            id: PluginId::new(name)?,
            contract_version: CONTRACT_VERSION,
            dependencies: dependencies
                .iter()
                .map(|id| PluginId::new(*id))
                .collect::<Result<_, _>>()?,
            evidence: EvidenceRef::new("plugin-evidence")?,
        },
        plugin: Box::new(Probe {
            log: log.clone(),
            behavior,
        }),
    })
}

fn plan(authority: AuthorityState) -> Result<RuntimePlan, String> {
    let evidence = EvidenceRef::new("host-evidence").map_err(|error| error.to_string())?;
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(EventEnvelope::new("plugin.lifecycle", evidence), authority),
    )))
}

fn allow(_: &PluginDescriptor, _: PluginAction) -> Result<RuntimePlan, String> {
    plan(AuthorityState::Authorized)
}

#[test]
fn explicit_health_snapshots_recover_without_lifecycle_or_cleanup_changes() -> TestResult {
    let log = Log::default();
    let health = Rc::new(RefCell::new(PluginOutcome::Success));
    let mut manager = PluginManager::new(vec![registration(
        "a",
        &[],
        &log,
        Behavior {
            health: Some(health.clone()),
            ..Behavior::default()
        },
    )?])?;
    let a = PluginId::new("a")?;
    manager.start_all(&mut allow)?;
    manager.drain_events().for_each(drop);
    log.borrow_mut().clear();
    let auth = RefCell::new(Vec::new());
    let mut fresh = |descriptor: &PluginDescriptor, action: PluginAction| {
        auth.borrow_mut().push((descriptor.id.clone(), action));
        allow(descriptor, action)
    };
    for (outcome, expected) in [
        (PluginOutcome::Success, PluginHealth::Ready),
        (PluginOutcome::NotReady, PluginHealth::NotReady),
        (PluginOutcome::Success, PluginHealth::Ready),
    ] {
        *health.borrow_mut() = outcome;
        assert_eq!(manager.check_health(&a, &mut fresh)?, expected);
        let status = manager.status(&a).expect("status");
        assert_eq!(status.state, PluginState::Running);
        assert_eq!(status.health, expected);
        assert!(status.cleanup_pending);
        assert!(status.failure.is_none());
        assert!(status.cleanup_error.is_none());
    }
    assert_eq!(*auth.borrow(), vec![(a, PluginAction::Readiness); 3]);
    assert_eq!(*log.borrow(), ["a:Readiness"; 3]);
    let events = manager.drain_events().collect::<Vec<_>>();
    assert_eq!(events.len(), 3);
    for (event, (previous, current, outcome)) in events.iter().zip([
        (
            PluginHealth::Ready,
            PluginHealth::Ready,
            PluginOutcome::Success,
        ),
        (
            PluginHealth::Ready,
            PluginHealth::NotReady,
            PluginOutcome::NotReady,
        ),
        (
            PluginHealth::NotReady,
            PluginHealth::Ready,
            PluginOutcome::Success,
        ),
    ]) {
        assert_eq!(
            event.kind,
            PluginEventKind::Callback(PluginAction::Readiness)
        );
        assert_eq!(event.previous.health, previous);
        assert_eq!(event.current.health, current);
        assert_eq!(event.outcome, outcome);
        assert_eq!(event.current.state, PluginState::Running);
        assert!(event.current.cleanup_pending);
        assert!(!event.current.failed);
    }
    assert_eq!(events[0].sequence, 5);
    assert_eq!(events[2].sequence, 7);
    manager.stop_all()?;
    Ok(())
}

#[test]
fn health_authority_rejection_preserves_ready_and_not_ready_snapshots() -> TestResult {
    let log = Log::default();
    let health = Rc::new(RefCell::new(PluginOutcome::Success));
    let a = PluginId::new("a")?;
    let mut manager = PluginManager::new(vec![registration(
        "a",
        &[],
        &log,
        Behavior {
            health: Some(health.clone()),
            ..Behavior::default()
        },
    )?])?;
    manager.start_all(&mut allow)?;
    for outcome in [PluginOutcome::Success, PluginOutcome::NotReady] {
        *health.borrow_mut() = outcome;
        manager.check_health(&a, &mut allow)?;
        manager.drain_events().for_each(drop);
        for authority in [
            AuthorityState::Revoked,
            AuthorityState::Expired,
            AuthorityState::InDoubt,
        ] {
            let before = manager.status(&a).expect("status").clone();
            let calls = log.borrow().clone();
            let mut deny = |_: &PluginDescriptor, action: PluginAction| {
                assert_eq!(action, PluginAction::Readiness);
                plan(authority)
            };
            assert!(matches!(
                manager.check_health(&a, &mut deny),
                Err(PluginError::Authorization(..))
            ));
            assert_eq!(manager.status(&a), Some(&before));
            assert_eq!(*log.borrow(), calls);
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(events.len(), 1);
            assert_eq!(events[0].previous, events[0].current);
            assert_eq!(
                events[0].kind,
                PluginEventKind::AuthorizationRejected(PluginAction::Readiness)
            );
            assert_eq!(events[0].outcome, PluginOutcome::Rejected);
        }
        let before = manager.status(&a).expect("status").clone();
        let calls = log.borrow().clone();
        let mut deny = |_: &PluginDescriptor, _: PluginAction| Err("private-auth-secret".into());
        assert!(matches!(
            manager.check_health(&a, &mut deny),
            Err(PluginError::Authorization(..))
        ));
        assert_eq!(manager.status(&a), Some(&before));
        assert_eq!(*log.borrow(), calls);
        assert!(
            !format!("{:?}", manager.drain_events().collect::<Vec<_>>())
                .contains("private-auth-secret")
        );
    }
    manager.stop_all()?;
    Ok(())
}

#[test]
fn health_failures_are_terminal_redacted_and_retain_cleanup_dependency_guards() -> TestResult {
    for outcome in [PluginOutcome::Error, PluginOutcome::Panicked] {
        let log = Log::default();
        let health = Rc::new(RefCell::new(PluginOutcome::Success));
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration(
                "b",
                &["a"],
                &log,
                Behavior {
                    health: Some(health.clone()),
                    cleanup_failures: 1,
                    ..Behavior::default()
                },
            )?,
        ])?;
        let a = PluginId::new("a")?;
        let b = PluginId::new("b")?;
        manager.start_all(&mut allow)?;
        manager.drain_events().for_each(drop);
        *health.borrow_mut() = outcome;
        assert!(matches!(
            manager.check_health(&b, &mut allow),
            Err(PluginError::Callback(..))
        ));
        let status = manager.status(&b).expect("status").clone();
        assert_eq!(status.state, PluginState::Failed);
        assert_eq!(status.health, PluginHealth::Unhealthy);
        assert!(status.cleanup_pending);
        let failure = status.failure.as_ref().expect("failure");
        assert_eq!(failure.action, PluginAction::Readiness);
        assert_eq!(failure.panicked, outcome == PluginOutcome::Panicked);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].outcome, outcome);
        assert_eq!(events[0].previous.health, PluginHealth::Ready);
        assert_eq!(events[0].current.health, PluginHealth::Unhealthy);
        assert!(events[0].current.failed);
        assert!(!format!("{events:?}").contains("private-health-secret"));
        *health.borrow_mut() = PluginOutcome::Success;
        let mut forbidden =
            |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                panic!("must not authorize");
            };
        assert_eq!(
            manager.check_health(&b, &mut forbidden),
            Err(PluginError::InvalidTransition(
                b.clone(),
                PluginState::Failed
            ))
        );
        assert_eq!(
            manager.pause(&a, &mut forbidden),
            Err(PluginError::DependencyInUse(b.clone()))
        );
        assert_eq!(manager.drain_events().count(), 0);
        assert!(manager.stop_all().is_err());
        assert_eq!(
            manager.status(&a).expect("status").state,
            PluginState::Running
        );
        assert_eq!(manager.status(&b).expect("status").failure, status.failure);
        manager.stop_all()?;
        assert!(!manager.status(&b).expect("status").cleanup_pending);
        assert_eq!(manager.status(&b).expect("status").failure, status.failure);
        assert_eq!(
            manager.status(&b).expect("status").state,
            PluginState::Failed
        );
    }
    Ok(())
}

#[test]
fn health_requires_running_and_batch_preflights_every_state_before_side_effects() -> TestResult {
    for state in [
        PluginState::Registered,
        PluginState::Initialized,
        PluginState::Starting,
        PluginState::Paused,
        PluginState::Stopped,
        PluginState::Failed,
    ] {
        let log = Log::default();
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration(
                "b",
                &[],
                &log,
                Behavior {
                    fail: (state == PluginState::Failed).then_some(PluginAction::Start),
                    ..Behavior::default()
                },
            )?,
        ])?;
        let a = PluginId::new("a")?;
        let b = PluginId::new("b")?;
        manager.initialize(&a, &mut allow)?;
        manager.start(&a, &mut allow)?;
        if state != PluginState::Registered {
            manager.initialize(&b, &mut allow)?;
        }
        if matches!(state, PluginState::Starting | PluginState::Failed) {
            let mut deny_readiness = |descriptor: &PluginDescriptor, action: PluginAction| {
                if action == PluginAction::Readiness {
                    Err("revoked".into())
                } else {
                    allow(descriptor, action)
                }
            };
            assert!(manager.start(&b, &mut deny_readiness).is_err());
        }
        if matches!(state, PluginState::Paused | PluginState::Stopped) {
            manager.start(&b, &mut allow)?;
            manager.pause(&b, &mut allow)?;
            if state == PluginState::Stopped {
                manager.stop_all()?;
            }
        }
        let before = manager.status(&b).expect("status").clone();
        let calls = log.borrow().clone();
        manager.drain_events().for_each(drop);
        let mut forbidden =
            |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                panic!("must preflight");
            };
        assert_eq!(
            manager.check_health(&b, &mut forbidden),
            Err(PluginError::InvalidTransition(b.clone(), state))
        );
        assert!(matches!(
            manager.check_health(&PluginId::new("unknown")?, &mut forbidden),
            Err(PluginError::UnknownPlugin(_))
        ));
        if state != PluginState::Paused {
            let invalid = if state == PluginState::Stopped {
                a
            } else {
                b.clone()
            };
            assert_eq!(
                manager.check_health_all(&mut forbidden),
                Err(PluginError::InvalidTransition(invalid, state))
            );
        }
        assert_eq!(manager.status(&b), Some(&before));
        assert_eq!(*log.borrow(), calls);
        assert_eq!(manager.drain_events().count(), 0);
        manager.stop_all()?;
    }
    Ok(())
}

#[test]
fn health_batch_is_topological_skips_paused_and_continues_past_not_ready() -> TestResult {
    let mut forbidden = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("empty/paused fleet must not authorize");
    };
    let mut empty = PluginManager::new(vec![])?;
    assert_eq!(empty.check_health_all(&mut forbidden)?, []);
    assert_eq!(empty.drain_events().count(), 0);
    let log = Log::default();
    let health = Rc::new(RefCell::new(PluginOutcome::Success));
    let mut manager = PluginManager::new(vec![
        registration("a", &["z"], &log, Behavior::default())?,
        registration("paused", &[], &log, Behavior::default())?,
        registration(
            "z",
            &[],
            &log,
            Behavior {
                health: Some(health.clone()),
                ..Behavior::default()
            },
        )?,
    ])?;
    manager.start_all(&mut allow)?;
    manager.pause(&PluginId::new("paused")?, &mut allow)?;
    manager.drain_events().for_each(drop);
    log.borrow_mut().clear();
    *health.borrow_mut() = PluginOutcome::NotReady;
    let calls = RefCell::new(Vec::new());
    let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
        calls.borrow_mut().push((descriptor.id.clone(), action));
        allow(descriptor, action)
    };
    let expected = vec![
        (PluginId::new("z")?, PluginHealth::NotReady),
        (PluginId::new("a")?, PluginHealth::Ready),
    ];
    assert_eq!(manager.check_health_all(&mut auth)?, expected);
    assert_eq!(*log.borrow(), ["z:Readiness", "a:Readiness"]);
    assert_eq!(
        *calls.borrow(),
        expected
            .iter()
            .map(|(id, _)| (id.clone(), PluginAction::Readiness))
            .collect::<Vec<_>>()
    );
    let events = manager.drain_events().collect::<Vec<_>>();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].id, expected[0].0);
    assert_eq!(events[1].id, expected[1].0);
    assert_eq!(events[0].outcome, PluginOutcome::NotReady);
    assert_eq!(
        manager.status(&PluginId::new("a")?).expect("status").state,
        PluginState::Running
    );
    manager.pause_all(&mut allow)?;
    manager.drain_events().for_each(drop);
    assert_eq!(manager.check_health_all(&mut forbidden)?, []);
    assert_eq!(manager.drain_events().count(), 0);
    manager.stop_all()?;
    Ok(())
}

#[test]
fn health_batch_stops_on_error_or_rejection_preserving_progress() -> TestResult {
    for rejected in [true, false] {
        let log = Log::default();
        let a_health = Rc::new(RefCell::new(PluginOutcome::Success));
        let b_health = Rc::new(RefCell::new(PluginOutcome::Success));
        let mut manager = PluginManager::new(vec![
            registration("c", &["b"], &log, Behavior::default())?,
            registration(
                "b",
                &["a"],
                &log,
                Behavior {
                    health: Some(b_health.clone()),
                    ..Behavior::default()
                },
            )?,
            registration(
                "a",
                &[],
                &log,
                Behavior {
                    health: Some(a_health.clone()),
                    ..Behavior::default()
                },
            )?,
        ])?;
        manager.start_all(&mut allow)?;
        manager.drain_events().for_each(drop);
        log.borrow_mut().clear();
        *a_health.borrow_mut() = PluginOutcome::NotReady;
        *b_health.borrow_mut() = PluginOutcome::Error;
        let calls = RefCell::new(Vec::new());
        let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
            calls.borrow_mut().push(descriptor.id.as_str().to_owned());
            if rejected && descriptor.id.as_str() == "b" {
                Err("private-auth-secret".into())
            } else {
                allow(descriptor, action)
            }
        };
        let result = manager.check_health_all(&mut auth);
        assert!(if rejected {
            matches!(result, Err(PluginError::Authorization(..)))
        } else {
            matches!(result, Err(PluginError::Callback(..)))
        });
        assert_eq!(*calls.borrow(), ["a", "b"]);
        assert_eq!(
            *log.borrow(),
            if rejected {
                vec!["a:Readiness"]
            } else {
                vec!["a:Readiness", "b:Readiness"]
            }
        );
        assert_eq!(
            manager.status(&PluginId::new("a")?).expect("status").health,
            PluginHealth::NotReady
        );
        assert_eq!(
            manager.status(&PluginId::new("b")?).expect("status").state,
            if rejected {
                PluginState::Running
            } else {
                PluginState::Failed
            }
        );
        assert_eq!(
            manager.status(&PluginId::new("c")?).expect("status").health,
            PluginHealth::Ready
        );
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].outcome, PluginOutcome::NotReady);
        assert_eq!(
            events[1].outcome,
            if rejected {
                PluginOutcome::Rejected
            } else {
                PluginOutcome::Error
            }
        );
        assert!(!format!("{events:?}").contains("private-"));
        if rejected {
            *b_health.borrow_mut() = PluginOutcome::Success;
            assert_eq!(manager.check_health_all(&mut allow)?.len(), 3);
        }
        manager.stop_all()?;
    }
    Ok(())
}

#[test]
fn dependency_health_blocks_start_resume_before_authority_but_not_existing_work() -> TestResult {
    let log = Log::default();
    let health = Rc::new(RefCell::new(PluginOutcome::Success));
    let mut manager = PluginManager::new(vec![
        registration(
            "a",
            &[],
            &log,
            Behavior {
                health: Some(health.clone()),
                ..Behavior::default()
            },
        )?,
        registration("b", &["a"], &log, Behavior::default())?,
    ])?;
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    manager.initialize(&a, &mut allow)?;
    manager.start(&a, &mut allow)?;
    manager.initialize(&b, &mut allow)?;
    let mut forbidden = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("dependency check precedes authorization");
    };
    for resume in [false, true] {
        *health.borrow_mut() = PluginOutcome::NotReady;
        assert_eq!(
            manager.check_health(&a, &mut allow)?,
            PluginHealth::NotReady
        );
        let before = manager.status(&b).expect("status").clone();
        let calls = log.borrow().clone();
        manager.drain_events().for_each(drop);
        let result = if resume {
            manager.resume(&b, &mut forbidden)
        } else {
            manager.start(&b, &mut forbidden)
        };
        assert_eq!(result, Err(PluginError::DependencyNotReady(a.clone())));
        assert_eq!(manager.status(&b), Some(&before));
        assert_eq!(*log.borrow(), calls);
        assert_eq!(manager.drain_events().count(), 0);
        *health.borrow_mut() = PluginOutcome::Success;
        assert_eq!(manager.check_health(&a, &mut allow)?, PluginHealth::Ready);
        if resume {
            manager.resume(&b, &mut allow)?;
        } else {
            manager.start(&b, &mut allow)?;
        }
        *health.borrow_mut() = PluginOutcome::NotReady;
        manager.check_health(&a, &mut allow)?;
        assert_eq!(
            manager.status(&b).expect("status").state,
            PluginState::Running
        );
        assert_eq!(
            manager.status(&b).expect("status").health,
            PluginHealth::Ready
        );
        manager.pause(&b, &mut allow)?;
    }
    // A terminal health failure preserves the established not-Running error.
    *health.borrow_mut() = PluginOutcome::Error;
    assert!(manager.check_health(&a, &mut allow).is_err());
    manager.drain_events().for_each(drop);
    assert_eq!(
        manager.resume(&b, &mut forbidden),
        Err(PluginError::DependencyNotRunning(a))
    );
    assert_eq!(manager.drain_events().count(), 0);
    manager.stop_all()?;
    Ok(())
}

#[test]
fn non_running_dependency_errors_keep_precedence_over_new_health_checks() -> TestResult {
    let log = Log::default();
    let health = Rc::new(RefCell::new(PluginOutcome::Success));
    let mut manager = PluginManager::new(vec![
        registration(
            "a",
            &[],
            &log,
            Behavior {
                health: Some(health.clone()),
                ..Behavior::default()
            },
        )?,
        registration("z", &[], &log, Behavior::default())?,
        registration("b", &["a", "z"], &log, Behavior::default())?,
    ])?;
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let z = PluginId::new("z")?;
    for id in [&a, &z] {
        manager.initialize(id, &mut allow)?;
        manager.start(id, &mut allow)?;
    }
    manager.initialize(&b, &mut allow)?;
    let mut forbidden = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("dependency rejection must not authorize");
    };
    for resume in [false, true] {
        *health.borrow_mut() = PluginOutcome::NotReady;
        manager.check_health(&a, &mut allow)?;
        manager.pause(&z, &mut allow)?;
        manager.drain_events().for_each(drop);
        let calls = log.borrow().clone();
        let result = if resume {
            manager.resume(&b, &mut forbidden)
        } else {
            manager.start(&b, &mut forbidden)
        };
        assert_eq!(result, Err(PluginError::DependencyNotRunning(z.clone())));
        assert_eq!(*log.borrow(), calls);
        assert_eq!(manager.drain_events().count(), 0);
        manager.resume(&z, &mut allow)?;
        *health.borrow_mut() = PluginOutcome::Success;
        manager.check_health(&a, &mut allow)?;
        if resume {
            manager.resume(&b, &mut allow)?;
        } else {
            manager.start(&b, &mut allow)?;
        }
        manager.pause(&b, &mut allow)?;
    }
    manager.stop_all()?;
    Ok(())
}

#[test]
fn not_ready_plugins_can_pause_and_shutdown_and_health_events_remain_bounded() -> TestResult {
    for capacity in [0, 2] {
        for pause in [false, true] {
            let log = Log::default();
            let health = Rc::new(RefCell::new(PluginOutcome::Success));
            let a = PluginId::new("a")?;
            let mut manager = PluginManager::with_event_capacity(
                vec![registration(
                    "a",
                    &[],
                    &log,
                    Behavior {
                        health: Some(health.clone()),
                        ..Behavior::default()
                    },
                )?],
                capacity,
            )?;
            manager.start_all(&mut allow)?;
            assert_eq!(manager.lost_events(), 4 - capacity as u64);
            manager.drain_events().for_each(drop);
            for outcome in [
                PluginOutcome::Success,
                PluginOutcome::NotReady,
                PluginOutcome::Success,
                PluginOutcome::NotReady,
            ] {
                *health.borrow_mut() = outcome;
                manager.check_health(&a, &mut allow)?;
            }
            let lost = 8 - 2 * capacity as u64;
            assert_eq!(manager.lost_events(), lost);
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(events.len(), capacity);
            if capacity != 0 {
                assert_eq!(events[0].sequence, 7);
                assert_eq!(events[1].sequence, 8);
                assert_eq!(events[1].current.health, PluginHealth::NotReady);
                assert_eq!(events[1].outcome, PluginOutcome::NotReady);
            }
            assert_eq!(manager.lost_events(), lost);
            assert_eq!(manager.drain_events().count(), 0);
            if pause {
                manager.pause(&a, &mut allow)?;
                assert_eq!(
                    manager.status(&a).expect("status").state,
                    PluginState::Paused
                );
            }
            manager.stop_all()?;
            assert_eq!(
                manager.status(&a).expect("status").state,
                PluginState::Stopped
            );
            assert!(!manager.status(&a).expect("status").cleanup_pending);
        }
    }
    Ok(())
}

#[test]
fn normal_lifecycle_is_deterministic_and_serialized() -> TestResult {
    for names in [["c", "b", "a"], ["a", "c", "b"], ["b", "a", "c"]] {
        let log = Log::default();
        let registrations = names
            .into_iter()
            .map(|name| {
                let deps: &[&str] = if name == "c" { &["a"] } else { &[] };
                registration(name, deps, &log, Behavior::default())
            })
            .collect::<Result<_, _>>()?;
        let mut manager = PluginManager::new(registrations)?;
        assert_eq!(
            manager
                .order()
                .iter()
                .map(PluginId::as_str)
                .collect::<Vec<_>>(),
            ["a", "b", "c"]
        );
        manager.start_all(&mut allow)?;
        for id in manager.order() {
            let status = manager.status(id).expect("registered plugin");
            assert_eq!(status.state, PluginState::Running);
            assert_eq!(status.health, PluginHealth::Ready);
            assert!(status.failure.is_none());
            assert_eq!(manager.descriptor(id).expect("descriptor").id, *id);
        }
        manager.stop_all()?;
        let after_stop = log.borrow().clone();
        manager.stop_all()?;
        assert_eq!(*log.borrow(), after_stop);
        assert_eq!(
            after_stop,
            [
                "a:Initialize",
                "a:Start",
                "a:Readiness",
                "b:Initialize",
                "b:Start",
                "b:Readiness",
                "c:Initialize",
                "c:Start",
                "c:Readiness",
                "c:Stop",
                "b:Stop",
                "a:Stop",
            ]
        );
        assert!(
            manager
                .order()
                .iter()
                .all(|id| manager.status(id).expect("status").state == PluginState::Stopped)
        );
    }
    Ok(())
}

#[test]
fn transitions_and_dependencies_fail_without_authorizing_or_callbacks() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration("b", &["a"], &log, Behavior::default())?,
    ])?;
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let mut forbidden = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("invalid transition must not authorize");
    };
    assert!(matches!(
        manager.start(&a, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    assert!(matches!(
        manager.initialize(&PluginId::new("absent")?, &mut forbidden),
        Err(PluginError::UnknownPlugin(_))
    ));
    manager.initialize(&b, &mut allow)?;
    assert_eq!(
        manager.start(&b, &mut forbidden),
        Err(PluginError::DependencyNotRunning(a.clone()))
    );
    manager.initialize(&a, &mut allow)?;
    assert!(matches!(
        manager.initialize(&a, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    manager.start(&a, &mut allow)?;
    manager.start(&b, &mut allow)?;
    assert!(matches!(
        manager.start(&a, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    assert!(matches!(
        manager.start_all(&mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    manager.stop_all()?;
    assert!(matches!(
        manager.initialize(&a, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    Ok(())
}

#[test]
fn fresh_authority_is_required_for_each_action_and_shutdown_bypasses_revocation() -> TestResult {
    for authority in [
        AuthorityState::Revoked,
        AuthorityState::Expired,
        AuthorityState::InDoubt,
    ] {
        let log = Log::default();
        let mut manager =
            PluginManager::new(vec![registration("a", &[], &log, Behavior::default())?])?;
        let a = PluginId::new("a")?;
        let mut deny = |_: &PluginDescriptor, _: PluginAction| plan(authority);
        // Hold and Deny plans validate successfully: validation alone is insufficient.
        assert!(plan(authority)?.validate().is_ok());
        assert!(matches!(
            manager.initialize(&a, &mut deny),
            Err(PluginError::Authorization(..))
        ));
        assert_eq!(
            manager.status(&a).expect("status").state,
            PluginState::Registered
        );
        assert!(log.borrow().is_empty());
        let calls = Rc::new(RefCell::new(Vec::new()));
        let captured = calls.clone();
        let mut fresh = move |descriptor: &PluginDescriptor, action: PluginAction| {
            captured.borrow_mut().push((descriptor.id.clone(), action));
            if action == PluginAction::Initialize {
                allow(descriptor, action)
            } else {
                plan(authority)
            }
        };
        manager.initialize(&a, &mut fresh)?;
        let before = manager.status(&a).expect("status").clone();
        assert!(matches!(
            manager.start(&a, &mut fresh),
            Err(PluginError::Authorization(..))
        ));
        assert_eq!(manager.status(&a), Some(&before));
        assert_eq!(*log.borrow(), ["a:Initialize"]);
        assert_eq!(
            *calls.borrow(),
            [
                (a.clone(), PluginAction::Initialize),
                (a.clone(), PluginAction::Start)
            ]
        );
        manager.stop_all()?;
        assert_eq!(*log.borrow(), ["a:Initialize", "a:Stop"]);
    }
    Ok(())
}

#[test]
fn host_denial_and_authorizer_panic_leave_status_untouched() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![registration("a", &[], &log, Behavior::default())?])?;
    let a = PluginId::new("a")?;
    let before = manager.status(&a).expect("status").clone();
    let mut deny = |_: &PluginDescriptor, _: PluginAction| Err("host denies".into());
    assert!(matches!(
        manager.initialize(&a, &mut deny),
        Err(PluginError::Authorization(..))
    ));
    let mut panic = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("authorizer panic");
    };
    assert!(matches!(
        manager.initialize(&a, &mut panic),
        Err(PluginError::Authorization(..))
    ));
    assert_eq!(manager.status(&a), Some(&before));
    assert!(log.borrow().is_empty());
    Ok(())
}

#[test]
fn startup_failures_rollback_and_preserve_failure_details() -> TestResult {
    for action in [
        PluginAction::Initialize,
        PluginAction::Start,
        PluginAction::Readiness,
    ] {
        for panicked in [false, true] {
            let log = Log::default();
            let behavior = Behavior {
                fail: (!panicked).then_some(action),
                panic: panicked.then_some(action),
                ..Behavior::default()
            };
            let mut manager = PluginManager::new(vec![
                registration("a", &[], &log, Behavior::default())?,
                registration("b", &["a"], &log, behavior)?,
                registration("c", &["b"], &log, Behavior::default())?,
            ])?;
            assert!(matches!(
                manager.start_all(&mut allow),
                Err(PluginError::Callback(..))
            ));
            let b = PluginId::new("b")?;
            let status = manager.status(&b).expect("status");
            assert_eq!(status.state, PluginState::Failed);
            assert_eq!(status.health, PluginHealth::Unhealthy);
            assert!(!status.cleanup_pending);
            let failure = status.failure.as_ref().expect("failure");
            assert_eq!(failure.action, action);
            assert_eq!(failure.panicked, panicked);
            assert!(log.borrow().ends_with(&["b:Stop".into(), "a:Stop".into()]));
            assert!(!log.borrow().iter().any(|line| line.starts_with("c:")));
            let before = log.borrow().clone();
            manager.stop_all()?;
            assert_eq!(*log.borrow(), before);
        }
    }
    Ok(())
}

#[test]
fn not_ready_is_distinct_from_lifecycle_state_and_is_cleaned_up() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![registration(
        "a",
        &[],
        &log,
        Behavior {
            not_ready: true,
            ..Behavior::default()
        },
    )?])?;
    assert!(manager.start_all(&mut allow).is_err());
    let status = manager.status(&PluginId::new("a")?).expect("status");
    assert_eq!(status.state, PluginState::Failed);
    assert_eq!(status.health, PluginHealth::NotReady);
    assert!(!status.cleanup_pending);
    assert_eq!(
        status.failure.as_ref().expect("failure").action,
        PluginAction::Readiness
    );
    assert_eq!(
        *log.borrow(),
        ["a:Initialize", "a:Start", "a:Readiness", "a:Stop"]
    );
    Ok(())
}

#[test]
fn failed_cleanup_retains_dependencies_until_explicit_retry() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration(
            "b",
            &["a"],
            &log,
            Behavior {
                cleanup_failures: 1,
                ..Behavior::default()
            },
        )?,
        registration("c", &[], &log, Behavior::default())?,
    ])?;
    manager.start_all(&mut allow)?;
    assert!(manager.stop_all().is_err());
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let status = manager.status(&b).expect("status");
    assert!(status.cleanup_pending);
    assert!(status.cleanup_error.is_some());
    assert_eq!(status.state, PluginState::Failed);
    assert_eq!(
        manager.status(&a).expect("status").state,
        PluginState::Running
    );
    assert!(log.borrow().ends_with(&["c:Stop".into(), "b:Stop".into()]));
    let before_retry = log.borrow().clone();
    let before_status = manager.status(&b).expect("status").clone();
    let mut forbidden = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("failed plugin must not be reauthorized");
    };
    assert!(matches!(
        manager.initialize(&b, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    assert!(matches!(
        manager.start(&b, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    assert_eq!(manager.status(&b), Some(&before_status));
    assert_eq!(*log.borrow(), before_retry);
    manager.stop_all()?;
    let status = manager.status(&b).expect("status");
    assert!(!status.cleanup_pending);
    assert!(status.cleanup_error.is_none());
    assert_eq!(status.state, PluginState::Failed);
    assert_eq!(
        status.failure.as_ref().expect("failure").action,
        PluginAction::Stop
    );
    assert!(log.borrow().ends_with(&["b:Stop".into(), "a:Stop".into()]));
    let before = log.borrow().clone();
    assert!(matches!(
        manager.initialize(&b, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    assert!(matches!(
        manager.start(&b, &mut forbidden),
        Err(PluginError::InvalidTransition(..))
    ));
    manager.stop_all()?;
    assert_eq!(*log.borrow(), before);
    Ok(())
}

#[test]
fn cleanup_panic_does_not_prevent_independent_cleanup() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration(
            "b",
            &[],
            &log,
            Behavior {
                panic: Some(PluginAction::Stop),
                ..Behavior::default()
            },
        )?,
    ])?;
    manager.start_all(&mut allow)?;
    assert!(manager.stop_all().is_err());
    assert!(log.borrow().ends_with(&["b:Stop".into(), "a:Stop".into()]));
    let b = PluginId::new("b")?;
    let status = manager.status(&b).expect("status");
    assert!(status.cleanup_pending);
    assert!(status.cleanup_error.as_ref().expect("failure").panicked);
    assert!(manager.stop_all().is_err());
    assert!(manager.status(&b).expect("status").cleanup_pending);
    Ok(())
}

#[test]
fn partial_startup_denial_retains_resources_for_revocation_safe_shutdown() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration("b", &["a"], &log, Behavior::default())?,
    ])?;
    let authority = Rc::new(RefCell::new(AuthorityState::Authorized));
    let current = authority.clone();
    let mut authorizer = move |descriptor: &PluginDescriptor, action: PluginAction| {
        if descriptor.id.as_str() == "b" && action == PluginAction::Start {
            *current.borrow_mut() = AuthorityState::Revoked;
        }
        plan(*current.borrow())
    };
    assert!(matches!(
        manager.start_all(&mut authorizer),
        Err(PluginError::Authorization(..))
    ));
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    assert_eq!(
        manager.status(&a).expect("status").state,
        PluginState::Running
    );
    assert_eq!(
        manager.status(&b).expect("status").state,
        PluginState::Initialized
    );
    assert_eq!(
        *log.borrow(),
        ["a:Initialize", "a:Start", "a:Readiness", "b:Initialize"]
    );
    assert_eq!(*authority.borrow(), AuthorityState::Revoked);
    manager.stop_all()?;
    assert!(log.borrow().ends_with(&["b:Stop".into(), "a:Stop".into()]));
    Ok(())
}

#[test]
fn rollback_cleanup_failure_is_not_retried_automatically_or_overwrites_start_failure() -> TestResult
{
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration(
            "b",
            &["a"],
            &log,
            Behavior {
                fail: Some(PluginAction::Start),
                cleanup_failures: 1,
                ..Behavior::default()
            },
        )?,
    ])?;
    let error = manager.start_all(&mut allow).expect_err("startup fails");
    assert!(matches!(error, PluginError::Callback(_, ref failure)
        if failure.action == PluginAction::Start));
    let b = PluginId::new("b")?;
    let status = manager.status(&b).expect("status");
    assert!(status.cleanup_pending);
    assert_eq!(
        status.failure.as_ref().expect("failure").action,
        PluginAction::Start
    );
    assert_eq!(
        status
            .cleanup_error
            .as_ref()
            .expect("cleanup failure")
            .action,
        PluginAction::Stop
    );
    assert_eq!(
        *log.borrow(),
        [
            "a:Initialize",
            "a:Start",
            "a:Readiness",
            "b:Initialize",
            "b:Start",
            "b:Stop",
        ]
    );
    manager.stop_all()?;
    let status = manager.status(&b).expect("status");
    assert_eq!(status.state, PluginState::Failed);
    assert!(!status.cleanup_pending);
    assert!(status.cleanup_error.is_none());
    assert_eq!(
        status.failure.as_ref().expect("failure").action,
        PluginAction::Start
    );
    assert!(log.borrow().ends_with(&["b:Stop".into(), "a:Stop".into()]));
    Ok(())
}

#[test]
fn pause_resume_dependency_order_authority_health_and_events() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("b", &["a"], &log, Behavior::default())?,
        registration("a", &[], &log, Behavior::default())?,
    ])?;
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let registered = manager.drain_events().collect::<Vec<_>>();
    assert_eq!(
        registered
            .iter()
            .map(|event| event.id.as_str())
            .collect::<Vec<_>>(),
        ["a", "b"]
    );
    assert!(
        registered
            .iter()
            .all(|event| event.kind == PluginEventKind::Registered)
    );
    manager.start_all(&mut allow)?;
    let before = log.borrow().len();
    assert_eq!(
        manager.pause(&a, &mut allow),
        Err(PluginError::DependencyInUse(b.clone()))
    );
    assert_eq!(log.borrow().len(), before);
    let status = manager.status(&b).expect("status").clone();
    let mut deny = |_: &PluginDescriptor, _: PluginAction| Err("secret host details".into());
    assert!(matches!(
        manager.pause(&b, &mut deny),
        Err(PluginError::Authorization(..))
    ));
    assert_eq!(manager.status(&b), Some(&status));
    assert_eq!(log.borrow().len(), before);
    manager.pause(&b, &mut allow)?;
    manager.pause(&a, &mut allow)?;
    assert_eq!(
        manager.status(&a).expect("status").health,
        PluginHealth::Unknown
    );
    assert_eq!(
        manager.resume(&b, &mut allow),
        Err(PluginError::DependencyNotRunning(a.clone()))
    );
    let paused = manager.status(&a).expect("status").clone();
    assert!(matches!(
        manager.resume(&a, &mut deny),
        Err(PluginError::Authorization(..))
    ));
    assert_eq!(manager.status(&a), Some(&paused));
    manager.resume(&a, &mut allow)?;
    manager.resume(&b, &mut allow)?;
    assert_eq!(
        manager.status(&b).expect("status").health,
        PluginHealth::Ready
    );
    manager.pause(&b, &mut allow)?;
    manager.pause(&a, &mut allow)?;
    manager.stop_all()?;
    assert!(log.borrow().ends_with(&["b:Stop".into(), "a:Stop".into()]));
    let events = manager.drain_events().collect::<Vec<_>>();
    assert!(
        events
            .windows(2)
            .all(|pair| pair[1].sequence == pair[0].sequence + 1)
    );
    assert_eq!(events[0].sequence, 3);
    let denied = events
        .iter()
        .filter(|event| matches!(event.kind, PluginEventKind::AuthorizationRejected(_)))
        .collect::<Vec<_>>();
    assert_eq!(denied.len(), 2);
    assert!(
        denied.iter().all(
            |event| event.previous == event.current && event.outcome == PluginOutcome::Rejected
        )
    );
    let pause = events
        .iter()
        .find(|event| event.kind == PluginEventKind::Callback(PluginAction::Pause))
        .expect("pause event");
    assert_eq!(pause.previous.state, PluginState::Running);
    assert_eq!(pause.current.state, PluginState::Paused);
    assert!(pause.current.cleanup_pending);
    assert!(!format!("{events:?}").contains("secret"));
    Ok(())
}

#[test]
fn operational_callbacks_each_require_fresh_authority() -> TestResult {
    for denied_action in [
        PluginAction::Readiness,
        PluginAction::Pause,
        PluginAction::Resume,
    ] {
        let log = Log::default();
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration("b", &["a"], &log, Behavior::default())?,
        ])?;
        manager.start_all(&mut allow)?;
        let b = PluginId::new("b")?;
        if denied_action != PluginAction::Pause {
            manager.pause(&b, &mut allow)?;
        }
        let before = log.borrow().clone();
        let calls = RefCell::new(Vec::new());
        let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
            calls.borrow_mut().push(action);
            if action == denied_action {
                Err("revoked".into())
            } else {
                allow(descriptor, action)
            }
        };
        let result = if denied_action == PluginAction::Pause {
            manager.pause(&b, &mut auth)
        } else {
            manager.resume(&b, &mut auth)
        };
        assert!(matches!(result, Err(PluginError::Authorization(..))));
        assert!(
            !log.borrow()[before.len()..]
                .iter()
                .any(|line| line == &format!("b:{denied_action:?}"))
        );
        if denied_action == PluginAction::Readiness {
            assert_eq!(
                *calls.borrow(),
                [PluginAction::Resume, PluginAction::Readiness]
            );
            assert_eq!(
                manager.status(&b).expect("status").state,
                PluginState::Starting
            );
            assert_eq!(
                manager.pause(&PluginId::new("a")?, &mut allow),
                Err(PluginError::DependencyInUse(b))
            );
        }
        manager.stop_all()?;
    }
    // Startup readiness is independently authorized too.
    let log = Log::default();
    let mut manager = PluginManager::new(vec![registration("a", &[], &log, Behavior::default())?])?;
    let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
        if action == PluginAction::Readiness {
            Err("revoked".into())
        } else {
            allow(descriptor, action)
        }
    };
    assert!(matches!(
        manager.start_all(&mut auth),
        Err(PluginError::Authorization(..))
    ));
    assert_eq!(*log.borrow(), ["a:Initialize", "a:Start"]);
    manager.stop_all()?;
    Ok(())
}

#[test]
fn pause_resume_failure_and_panic_block_dependency_until_cleanup() -> TestResult {
    for action in [PluginAction::Pause, PluginAction::Resume] {
        for panicked in [false, true] {
            let log = Log::default();
            let mut manager = PluginManager::new(vec![
                registration("a", &[], &log, Behavior::default())?,
                registration(
                    "b",
                    &["a"],
                    &log,
                    Behavior {
                        fail: (!panicked).then_some(action),
                        panic: panicked.then_some(action),
                        cleanup_failures: 1,
                        ..Behavior::default()
                    },
                )?,
            ])?;
            manager.start_all(&mut allow)?;
            let a = PluginId::new("a")?;
            let b = PluginId::new("b")?;
            if action == PluginAction::Resume {
                manager.pause(&b, &mut allow)?;
            }
            let result = if action == PluginAction::Pause {
                manager.pause(&b, &mut allow)
            } else {
                manager.resume(&b, &mut allow)
            };
            assert!(matches!(result, Err(PluginError::Callback(..))));
            assert_eq!(
                manager.status(&b).expect("status").state,
                PluginState::Failed
            );
            assert!(manager.status(&b).expect("status").cleanup_pending);
            assert_eq!(
                manager.pause(&a, &mut allow),
                Err(PluginError::DependencyInUse(b.clone()))
            );
            assert!(manager.stop_all().is_err());
            assert_eq!(
                manager.status(&a).expect("status").state,
                PluginState::Running
            );
            manager.stop_all()?;
            let events = manager.drain_events().collect::<Vec<_>>();
            let failure = events
                .iter()
                .find(|event| event.kind == PluginEventKind::Callback(action))
                .expect("failure event");
            assert_eq!(
                failure.outcome,
                if panicked {
                    PluginOutcome::Panicked
                } else {
                    PluginOutcome::Error
                }
            );
            let cleanup = events
                .iter()
                .filter(|event| {
                    event.id == b && event.kind == PluginEventKind::Callback(PluginAction::Stop)
                })
                .collect::<Vec<_>>();
            assert_eq!(cleanup.len(), 2);
            assert_eq!(cleanup[0].outcome, PluginOutcome::Error);
            assert!(cleanup[0].current.cleanup_failed);
            assert_eq!(cleanup[1].outcome, PluginOutcome::Success);
            assert_eq!(cleanup[1].previous.state, PluginState::Failed);
            assert_eq!(cleanup[1].current.state, PluginState::Failed);
            assert!(!cleanup[1].current.cleanup_pending);
            assert!(!cleanup[1].current.cleanup_failed);
            let debug = format!("{events:?}");
            assert!(!debug.contains("test callback"));
            assert!(!debug.contains("retry cleanup"));
        }
    }
    Ok(())
}

#[test]
fn event_overflow_drops_oldest_with_visible_gaps_and_cumulative_loss() -> TestResult {
    for capacity in [0, 2] {
        let log = Log::default();
        let mut manager = PluginManager::with_event_capacity(
            vec![registration("a", &[], &log, Behavior::default())?],
            capacity,
        )?;
        manager.start_all(&mut allow)?;
        manager.stop_all()?;
        let lost = 5 - capacity as u64;
        assert_eq!(manager.lost_events(), lost);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), capacity);
        if capacity != 0 {
            assert_eq!(events[0].sequence, 4);
            assert_eq!(events[1].sequence, 5);
        }
        assert_eq!(manager.drain_events().count(), 0);
        assert_eq!(manager.lost_events(), lost);
        // Unknown IDs and invalid transitions produce no events.
        assert!(
            manager
                .start(&PluginId::new("missing")?, &mut allow)
                .is_err()
        );
        assert!(manager.start(&PluginId::new("a")?, &mut allow).is_err());
        assert_eq!(manager.drain_events().count(), 0);
        assert_eq!(manager.lost_events(), lost);
    }
    Ok(())
}

#[test]
fn legacy_implementors_default_to_unsupported_pause_and_failed_cleanup() -> TestResult {
    struct Legacy;
    impl Plugin for Legacy {
        fn initialize(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
            Ok(())
        }
        fn start(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
            Ok(())
        }
        fn readiness(&mut self, _: &PluginContext<'_>) -> Result<bool, String> {
            Ok(true)
        }
        fn stop(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
            Ok(())
        }
    }
    let log = Log::default();
    let mut registration = registration("a", &[], &log, Behavior::default())?;
    let context = PluginContext {
        id: &registration.descriptor.id,
        evidence: &registration.descriptor.evidence,
    };
    assert!(Legacy.resume(&context).is_err());
    registration.plugin = Box::new(Legacy);
    let mut manager = PluginManager::new(vec![registration])?;
    manager.start_all(&mut allow)?;
    let a = PluginId::new("a")?;
    assert!(matches!(
        manager.pause(&a, &mut allow),
        Err(PluginError::Callback(..))
    ));
    assert_eq!(
        manager.status(&a).expect("status").state,
        PluginState::Failed
    );
    assert!(manager.status(&a).expect("status").cleanup_pending);
    manager.stop_all()?;
    assert!(!manager.status(&a).expect("status").cleanup_pending);
    Ok(())
}

#[test]
fn resume_readiness_failure_and_panic_are_failed_not_paused_or_running() -> TestResult {
    for outcome in [
        PluginOutcome::Error,
        PluginOutcome::Panicked,
        PluginOutcome::NotReady,
    ] {
        let log = Log::default();
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration(
                "b",
                &["a"],
                &log,
                Behavior {
                    resume_readiness: Some(outcome),
                    ..Behavior::default()
                },
            )?,
        ])?;
        manager.start_all(&mut allow)?;
        let a = PluginId::new("a")?;
        let b = PluginId::new("b")?;
        manager.pause(&b, &mut allow)?;
        assert!(manager.resume(&b, &mut allow).is_err());
        let status = manager.status(&b).expect("status");
        assert_eq!(status.state, PluginState::Failed);
        assert!(status.cleanup_pending);
        assert_eq!(
            status.health,
            if outcome == PluginOutcome::NotReady {
                PluginHealth::NotReady
            } else {
                PluginHealth::Unhealthy
            }
        );
        assert_eq!(
            manager.pause(&a, &mut allow),
            Err(PluginError::DependencyInUse(b.clone()))
        );
        manager.stop_all()?;
        let events = manager.drain_events().collect::<Vec<_>>();
        let event = events
            .iter()
            .find(|event| event.id == b && event.outcome == outcome)
            .expect("readiness failure");
        assert_eq!(
            event.kind,
            PluginEventKind::Callback(PluginAction::Readiness)
        );
        assert_eq!(event.previous.state, PluginState::Starting);
        assert_eq!(event.current.state, PluginState::Failed);
    }
    Ok(())
}

#[test]
fn batch_diamond_order_events_and_idempotence_across_registration_permutations() -> TestResult {
    for a in 0..4 {
        for b in 0..4 {
            for c in 0..4 {
                for d in 0..4 {
                    let permutation = [a, b, c, d];
                    if permutation
                        .iter()
                        .copied()
                        .collect::<std::collections::BTreeSet<_>>()
                        .len()
                        != 4
                    {
                        continue;
                    }
                    let log = Log::default();
                    let nodes = [
                        ("a", &[][..]),
                        ("b", &["a"][..]),
                        ("c", &["a"][..]),
                        ("d", &["b", "c"][..]),
                    ];
                    let make = || {
                        permutation
                            .iter()
                            .map(|index| {
                                let (name, deps) = nodes[*index];
                                registration(name, deps, &log, Behavior::default())
                            })
                            .collect::<Result<Vec<_>, _>>()
                    };
                    let mut manager = PluginManager::new(make()?)?;
                    let mut single = PluginManager::new(make()?)?;
                    manager.start_all(&mut allow)?;
                    single.start_all(&mut allow)?;
                    log.borrow_mut().clear();
                    manager.drain_events().count();
                    single.drain_events().count();
                    let auth_calls = RefCell::new(Vec::new());
                    let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
                        auth_calls
                            .borrow_mut()
                            .push(format!("{}:{action:?}", descriptor.id.as_str()));
                        allow(descriptor, action)
                    };
                    manager.pause_all(&mut auth)?;
                    manager.resume_all(&mut auth)?;
                    let expected = [
                        "d:Pause",
                        "c:Pause",
                        "b:Pause",
                        "a:Pause",
                        "a:Resume",
                        "a:Readiness",
                        "b:Resume",
                        "b:Readiness",
                        "c:Resume",
                        "c:Readiness",
                        "d:Resume",
                        "d:Readiness",
                    ];
                    assert_eq!(*log.borrow(), expected);
                    assert_eq!(*auth_calls.borrow(), expected);
                    let events = manager.drain_events().collect::<Vec<_>>();
                    let last_running_sequence = events.last().expect("resume event").sequence;
                    for id in single.order().to_vec().into_iter().rev() {
                        single.pause(&id, &mut allow)?;
                    }
                    for id in single.order().to_vec() {
                        single.resume(&id, &mut allow)?;
                    }
                    assert_eq!(events, single.drain_events().collect::<Vec<_>>());

                    let mut forbidden =
                        |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                            panic!("idempotent batches must not authorize");
                        };
                    log.borrow_mut().clear();
                    let running_statuses = manager
                        .order()
                        .iter()
                        .map(|id| manager.status(id).cloned())
                        .collect::<Vec<_>>();
                    manager.resume_all(&mut forbidden)?;
                    manager.resume_all(&mut forbidden)?;
                    assert!(log.borrow().is_empty());
                    assert_eq!(manager.drain_events().count(), 0);
                    assert_eq!(
                        manager
                            .order()
                            .iter()
                            .map(|id| manager.status(id).cloned())
                            .collect::<Vec<_>>(),
                        running_statuses
                    );
                    manager.pause_all(&mut allow)?;
                    log.borrow_mut().clear();
                    let pause_events = manager.drain_events().collect::<Vec<_>>();
                    assert_eq!(pause_events[0].sequence, last_running_sequence + 1);
                    let last_paused_sequence = pause_events.last().expect("pause event").sequence;
                    let paused_statuses = manager
                        .order()
                        .iter()
                        .map(|id| manager.status(id).cloned())
                        .collect::<Vec<_>>();
                    manager.pause_all(&mut forbidden)?;
                    manager.pause_all(&mut forbidden)?;
                    assert!(log.borrow().is_empty());
                    assert_eq!(manager.drain_events().count(), 0);
                    assert_eq!(
                        manager
                            .order()
                            .iter()
                            .map(|id| manager.status(id).cloned())
                            .collect::<Vec<_>>(),
                        paused_statuses
                    );
                    assert_eq!(manager.lost_events(), 0);
                    manager.stop_all()?;
                    let cleanup_events = manager.drain_events().collect::<Vec<_>>();
                    assert_eq!(cleanup_events[0].sequence, last_paused_sequence + 1);
                    single.stop_all()?;
                }
            }
        }
    }
    let mut empty = PluginManager::new(vec![])?;
    let mut forbidden = |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
        panic!("empty fleet must not authorize");
    };
    empty.pause_all(&mut forbidden)?;
    empty.resume_all(&mut forbidden)?;
    assert_eq!(empty.drain_events().count(), 0);
    Ok(())
}

#[test]
fn batch_preflights_all_invalid_states_before_any_work_in_either_direction() -> TestResult {
    for state in [
        PluginState::Registered,
        PluginState::Initialized,
        PluginState::Starting,
        PluginState::Stopped,
        PluginState::Failed,
    ] {
        for pausing in [false, true] {
            let log = Log::default();
            let mut manager = PluginManager::new(vec![
                registration("c", &[], &log, Behavior::default())?,
                registration(
                    "b",
                    &[],
                    &log,
                    Behavior {
                        fail: (state == PluginState::Failed).then_some(PluginAction::Initialize),
                        ..Behavior::default()
                    },
                )?,
                registration("a", &[], &log, Behavior::default())?,
                registration("aa", &[], &log, Behavior::default())?,
            ])?;
            let b = PluginId::new("b")?;
            match state {
                PluginState::Registered => {}
                PluginState::Failed => {
                    assert!(manager.initialize(&b, &mut allow).is_err());
                }
                _ => {
                    manager.initialize(&b, &mut allow)?;
                    if state == PluginState::Stopped {
                        manager.stop_all()?;
                    } else if state == PluginState::Starting {
                        let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
                            if action == PluginAction::Readiness {
                                Err("revoked".into())
                            } else {
                                allow(descriptor, action)
                            }
                        };
                        assert!(manager.start(&b, &mut auth).is_err());
                    }
                }
            }
            for name in ["a", "aa", "c"] {
                let id = PluginId::new(name)?;
                manager.initialize(&id, &mut allow)?;
                manager.start(&id, &mut allow)?;
                if (name == "aa" && pausing) || (name != "aa" && !pausing) {
                    manager.pause(&id, &mut allow)?;
                }
            }
            assert_eq!(manager.status(&b).expect("status").state, state);
            let before = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>();
            log.borrow_mut().clear();
            let last_sequence = manager.drain_events().last().expect("setup event").sequence;
            let mut forbidden =
                |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                    panic!("fleet preflight must finish before authorization");
                };
            let result = if pausing {
                manager.pause_all(&mut forbidden)
            } else {
                manager.resume_all(&mut forbidden)
            };
            assert_eq!(result, Err(PluginError::InvalidTransition(b, state)));
            assert!(log.borrow().is_empty());
            assert_eq!(manager.drain_events().count(), 0);
            assert_eq!(
                manager
                    .order()
                    .iter()
                    .map(|id| manager.status(id).cloned())
                    .collect::<Vec<_>>(),
                before
            );
            manager.stop_all()?;
            assert_eq!(
                manager
                    .drain_events()
                    .next()
                    .expect("cleanup event")
                    .sequence,
                last_sequence + 1
            );
        }
    }
    // Even reverse-order pause reports the first invalid node in DAG order.
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("b", &[], &log, Behavior::default())?,
        registration("a", &["b"], &log, Behavior::default())?,
    ])?;
    manager.drain_events().count();
    for pausing in [false, true] {
        let result = if pausing {
            manager.pause_all(&mut allow)
        } else {
            manager.resume_all(&mut allow)
        };
        assert_eq!(
            result,
            Err(PluginError::InvalidTransition(
                PluginId::new("b")?,
                PluginState::Registered
            ))
        );
        assert!(log.borrow().is_empty());
        assert_eq!(manager.drain_events().count(), 0);
    }
    Ok(())
}

#[test]
fn batch_authorization_rejection_preserves_progress_and_mixed_fleet_can_continue() -> TestResult {
    for action in [
        PluginAction::Pause,
        PluginAction::Resume,
        PluginAction::Readiness,
    ] {
        for panicked in [false, true] {
            let log = Log::default();
            let mut manager = PluginManager::new(vec![
                registration("a", &[], &log, Behavior::default())?,
                registration("b", &["a"], &log, Behavior::default())?,
                registration("c", &["b"], &log, Behavior::default())?,
            ])?;
            manager.start_all(&mut allow)?;
            if action != PluginAction::Pause {
                manager.pause_all(&mut allow)?;
            }
            log.borrow_mut().clear();
            manager.drain_events().count();
            let calls = RefCell::new(Vec::new());
            let mut auth = |descriptor: &PluginDescriptor, current: PluginAction| {
                calls
                    .borrow_mut()
                    .push(format!("{}:{current:?}", descriptor.id.as_str()));
                if descriptor.id.as_str() == "b" && current == action {
                    assert!(!panicked, "synthetic authorizer panic");
                    plan(AuthorityState::Revoked)
                } else {
                    allow(descriptor, current)
                }
            };
            let result = if action == PluginAction::Pause {
                manager.pause_all(&mut auth)
            } else {
                manager.resume_all(&mut auth)
            };
            assert!(matches!(result, Err(PluginError::Authorization(id, _)) if id.as_str() == "b"));
            let states = manager
                .order()
                .iter()
                .map(|id| manager.status(id).expect("status").state)
                .collect::<Vec<_>>();
            let expected_calls: &[&str] = match action {
                PluginAction::Pause => {
                    assert_eq!(
                        states,
                        [
                            PluginState::Running,
                            PluginState::Running,
                            PluginState::Paused
                        ]
                    );
                    assert_eq!(*log.borrow(), ["c:Pause"]);
                    &["c:Pause", "b:Pause"]
                }
                PluginAction::Resume => {
                    assert_eq!(
                        states,
                        [
                            PluginState::Running,
                            PluginState::Paused,
                            PluginState::Paused
                        ]
                    );
                    assert_eq!(*log.borrow(), ["a:Resume", "a:Readiness"]);
                    &["a:Resume", "a:Readiness", "b:Resume"]
                }
                _ => {
                    assert_eq!(
                        states,
                        [
                            PluginState::Running,
                            PluginState::Starting,
                            PluginState::Paused
                        ]
                    );
                    assert_eq!(*log.borrow(), ["a:Resume", "a:Readiness", "b:Resume"]);
                    &["a:Resume", "a:Readiness", "b:Resume", "b:Readiness"]
                }
            };
            assert_eq!(*calls.borrow(), expected_calls);
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(events.len(), expected_calls.len());
            for (event, call) in events.iter().zip(expected_calls) {
                let event_action = match event.kind {
                    PluginEventKind::Callback(action)
                    | PluginEventKind::AuthorizationRejected(action) => action,
                    _ => panic!("unexpected registration event"),
                };
                assert_eq!(format!("{}:{event_action:?}", event.id.as_str()), *call);
            }
            let rejected = events.last().expect("rejection");
            assert_eq!(
                rejected.kind,
                PluginEventKind::AuthorizationRejected(action)
            );
            assert_eq!(rejected.previous, rejected.current);
            assert_eq!(rejected.outcome, PluginOutcome::Rejected);
            log.borrow_mut().clear();
            if action == PluginAction::Readiness {
                assert_eq!(
                    manager.status(&PluginId::new("b")?).expect("status").health,
                    PluginHealth::Unknown
                );
                let mut forbidden =
                    |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                        panic!("Starting must not be retried");
                    };
                assert!(matches!(
                    manager.resume_all(&mut forbidden),
                    Err(PluginError::InvalidTransition(_, PluginState::Starting))
                ));
                assert!(matches!(
                    manager.pause_all(&mut forbidden),
                    Err(PluginError::InvalidTransition(_, PluginState::Starting))
                ));
                assert!(log.borrow().is_empty());
                assert_eq!(manager.drain_events().count(), 0);
            } else if action == PluginAction::Pause {
                manager.pause_all(&mut allow)?;
                assert_eq!(*log.borrow(), ["b:Pause", "a:Pause"]);
            } else {
                manager.resume_all(&mut allow)?;
                assert_eq!(
                    *log.borrow(),
                    ["b:Resume", "b:Readiness", "c:Resume", "c:Readiness"]
                );
            }
            // No authority is available after revocation, but cleanup remains usable.
            log.borrow_mut().clear();
            manager.stop_all()?;
            assert_eq!(*log.borrow(), ["c:Stop", "b:Stop", "a:Stop"]);
            assert!(
                manager
                    .order()
                    .iter()
                    .all(|id| !manager.status(id).expect("status").cleanup_pending)
            );
        }
    }
    Ok(())
}

#[test]
fn batch_callback_errors_and_panics_stop_immediately_and_cleanup_is_revocation_safe() -> TestResult
{
    for action in [
        PluginAction::Pause,
        PluginAction::Resume,
        PluginAction::Readiness,
    ] {
        for outcome in [
            PluginOutcome::Error,
            PluginOutcome::Panicked,
            PluginOutcome::NotReady,
        ] {
            if action != PluginAction::Readiness && outcome == PluginOutcome::NotReady {
                continue;
            }
            let log = Log::default();
            let mut manager = PluginManager::new(vec![
                registration("a", &[], &log, Behavior::default())?,
                registration(
                    "b",
                    &["a"],
                    &log,
                    Behavior {
                        fail: (action != PluginAction::Readiness
                            && outcome == PluginOutcome::Error)
                            .then_some(action),
                        panic: (action != PluginAction::Readiness
                            && outcome == PluginOutcome::Panicked)
                            .then_some(action),
                        resume_readiness: (action == PluginAction::Readiness).then_some(outcome),
                        cleanup_failures: 1,
                        ..Behavior::default()
                    },
                )?,
                registration("c", &["b"], &log, Behavior::default())?,
            ])?;
            manager.start_all(&mut allow)?;
            if action != PluginAction::Pause {
                manager.pause_all(&mut allow)?;
            }
            log.borrow_mut().clear();
            manager.drain_events().count();
            let calls = RefCell::new(Vec::new());
            let mut auth = |descriptor: &PluginDescriptor, current: PluginAction| {
                calls
                    .borrow_mut()
                    .push(format!("{}:{current:?}", descriptor.id.as_str()));
                allow(descriptor, current)
            };
            let result = if action == PluginAction::Pause {
                manager.pause_all(&mut auth)
            } else {
                manager.resume_all(&mut auth)
            };
            assert!(
                matches!(result, Err(PluginError::Callback(id, failure)) if id.as_str() == "b" && failure.action == action && failure.panicked == (outcome == PluginOutcome::Panicked))
            );
            let expected: &[&str] = match action {
                PluginAction::Pause => &["c:Pause", "b:Pause"],
                PluginAction::Resume => &["a:Resume", "a:Readiness", "b:Resume"],
                _ => &["a:Resume", "a:Readiness", "b:Resume", "b:Readiness"],
            };
            assert_eq!(*log.borrow(), expected);
            assert_eq!(*calls.borrow(), expected);
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(events.len(), expected.len());
            assert!(
                events[..events.len() - 1]
                    .iter()
                    .all(|event| event.outcome == PluginOutcome::Success)
            );
            let failure_event = events.last().expect("failure event");
            assert_eq!(failure_event.outcome, outcome);
            assert_eq!(failure_event.kind, PluginEventKind::Callback(action));
            assert_eq!(failure_event.current.state, PluginState::Failed);
            assert!(failure_event.current.cleanup_pending);
            assert_eq!(
                manager.status(&PluginId::new("a")?).expect("status").state,
                PluginState::Running
            );
            assert_eq!(
                manager.status(&PluginId::new("c")?).expect("status").state,
                PluginState::Paused
            );
            let failed = manager
                .status(&PluginId::new("b")?)
                .expect("status")
                .failure
                .clone();
            log.borrow_mut().clear();
            let mut forbidden =
                |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                    panic!("failed fleet must not retry business work");
                };
            assert!(matches!(
                manager.pause_all(&mut forbidden),
                Err(PluginError::InvalidTransition(_, PluginState::Failed))
            ));
            assert!(matches!(
                manager.resume_all(&mut forbidden),
                Err(PluginError::InvalidTransition(_, PluginState::Failed))
            ));
            assert!(log.borrow().is_empty());
            assert_eq!(manager.drain_events().count(), 0);
            assert!(manager.stop_all().is_err());
            assert_eq!(*log.borrow(), ["c:Stop", "b:Stop"]);
            assert_eq!(
                manager.status(&PluginId::new("a")?).expect("status").state,
                PluginState::Running
            );
            manager.stop_all()?;
            assert_eq!(*log.borrow(), ["c:Stop", "b:Stop", "b:Stop", "a:Stop"]);
            let status = manager.status(&PluginId::new("b")?).expect("status");
            assert_eq!(status.failure, failed);
            assert_eq!(status.state, PluginState::Failed);
            assert!(!status.cleanup_pending);
            assert!(status.cleanup_error.is_none());
        }
    }
    Ok(())
}
