use std::{cell::RefCell, error::Error, rc::Rc};

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef, Validatable};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, HealthOutcome, Plugin, PluginAction, PluginContext, PluginDescriptor,
        PluginError, PluginEventKind, PluginHealth, PluginId, PluginManager, PluginOutcome,
        PluginRegistration, PluginSnapshot, PluginState, ShutdownOutcome, ShutdownScope,
        StartupDisposition,
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
    cleanup: Option<Rc<RefCell<PluginOutcome>>>,
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
        if let Some(cleanup) = &self.behavior.cleanup {
            match *cleanup.borrow() {
                PluginOutcome::Error => return Err("private-cleanup-secret".into()),
                PluginOutcome::Panicked => panic!("private-cleanup-secret"),
                _ => {}
            }
        }
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
fn inventory_tracks_retained_health_and_cleanup_without_observation_side_effects() -> TestResult {
    for failure in [PluginOutcome::Error, PluginOutcome::Panicked] {
        let log = Log::default();
        let health = Rc::new(RefCell::new(PluginOutcome::Success));
        let cleanup = Rc::new(RefCell::new(PluginOutcome::Error));
        let mut manager = PluginManager::new(vec![
            registration(
                "a",
                &[],
                &log,
                Behavior {
                    health: Some(health.clone()),
                    cleanup: Some(cleanup.clone()),
                    ..Behavior::default()
                },
            )?,
            registration("inactive", &["a"], &log, Behavior::default())?,
        ])?;
        let id = PluginId::new("a")?;
        let observe = |manager: &PluginManager| {
            let before_log = log.borrow().clone();
            let before_status = manager.status(&id).cloned();
            let inventory = manager.inventory();
            assert_eq!(manager.inventory(), inventory);
            assert_eq!(*log.borrow(), before_log);
            assert_eq!(manager.status(&id), before_status.as_ref());
            assert_eq!(inventory.entries().len(), 2);
            assert_eq!(
                inventory.entries()[1].snapshot.state,
                PluginState::Registered
            );
            assert_eq!(
                inventory.entries()[0].snapshot,
                PluginSnapshot::from(manager.status(&id).expect("status"))
            );
            let rendered = format!("{inventory:?}");
            for excluded in [
                "private-health-secret",
                "private-cleanup-secret",
                "plugin-evidence",
            ] {
                assert!(!rendered.contains(excluded));
            }
            inventory.entries()[0].snapshot
        };
        assert_eq!(observe(&manager).state, PluginState::Registered);
        manager.initialize(&id, &mut allow)?;
        assert_eq!(observe(&manager).state, PluginState::Initialized);
        manager.start(&id, &mut allow)?;
        assert_eq!(observe(&manager).health, PluginHealth::Ready);
        *health.borrow_mut() = PluginOutcome::NotReady;
        manager.check_health(&id, &mut allow)?;
        assert_eq!(observe(&manager).health, PluginHealth::NotReady);
        *health.borrow_mut() = PluginOutcome::Success;
        manager.check_health(&id, &mut allow)?;
        assert_eq!(observe(&manager).health, PluginHealth::Ready);
        manager.pause(&id, &mut allow)?;
        assert_eq!(observe(&manager).state, PluginState::Paused);
        manager.resume(&id, &mut allow)?;
        *health.borrow_mut() = failure;
        assert!(manager.check_health(&id, &mut allow).is_err());
        let failed = observe(&manager);
        assert_eq!(failed.state, PluginState::Failed);
        assert_eq!(failed.health, PluginHealth::Unhealthy);
        assert!(failed.failed && failed.cleanup_pending && !failed.cleanup_failed);
        assert!(manager.stop(&id).is_err());
        assert!(observe(&manager).cleanup_failed);
        *cleanup.borrow_mut() = PluginOutcome::Success;
        manager.stop_all()?;
        let cleaned = observe(&manager);
        assert_eq!(cleaned.state, PluginState::Failed);
        assert!(cleaned.failed && !cleaned.cleanup_pending && !cleaned.cleanup_failed);
    }
    Ok(())
}

#[test]
fn scoped_start_chain_and_diamond_are_deterministic_and_idempotent() -> TestResult {
    for diamond in [false, true] {
        for reverse in [false, true] {
            let log = Log::default();
            let mut registrations = vec![
                registration("a", &[], &log, Behavior::default())?,
                registration("b", &["a"], &log, Behavior::default())?,
                registration("c", &["a"], &log, Behavior::default())?,
                registration(
                    "root",
                    if diamond { &["c", "b"] } else { &["b"] },
                    &log,
                    Behavior::default(),
                )?,
                registration("dependent", &["root"], &log, Behavior::default())?,
                registration("unrelated", &[], &log, Behavior::default())?,
            ];
            if reverse {
                registrations.reverse();
            }
            let mut manager = PluginManager::new(registrations)?;
            let root = PluginId::new("root")?;
            let preview = manager.plan_startup(&root)?;
            assert!(preview.can_start());
            assert!(preview.steps().iter().all(|step| {
                step.disposition == StartupDisposition::Start
                    && step.snapshot
                        == PluginSnapshot::from(manager.status(&step.id).expect("status"))
            }));
            assert!(log.borrow().is_empty());
            let mut authorized = Vec::new();
            manager.start_with_dependencies(&root, &mut |d: &PluginDescriptor, action| {
                authorized.push(format!("{}:{action:?}", d.id.as_str()));
                allow(d, action)
            })?;
            let names = if diamond {
                vec!["a", "b", "c", "root"]
            } else {
                vec!["a", "b", "root"]
            };
            assert_eq!(
                preview
                    .steps()
                    .iter()
                    .map(|step| step.id.as_str())
                    .collect::<Vec<_>>(),
                names
            );
            let expected: Vec<_> = names
                .iter()
                .flat_map(|name| {
                    ["Initialize", "Start", "Readiness"].map(|action| format!("{name}:{action}"))
                })
                .collect();
            assert_eq!(*log.borrow(), expected);
            assert_eq!(authorized, expected);
            for name in ["dependent", "unrelated"]
                .into_iter()
                .chain((!diamond).then_some("c"))
            {
                assert_eq!(
                    manager.status(&PluginId::new(name)?).expect("status").state,
                    PluginState::Registered
                );
            }
            let before = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>();
            manager.drain_events().for_each(drop);
            log.borrow_mut().clear();
            let running = manager.plan_startup(&root)?;
            assert!(running.can_start());
            assert!(
                running
                    .steps()
                    .iter()
                    .all(|step| { step.disposition == StartupDisposition::AlreadyRunning })
            );
            // The owned initial plan is unchanged after startup.
            assert!(
                preview
                    .steps()
                    .iter()
                    .all(|step| { step.disposition == StartupDisposition::Start })
            );
            manager.start_with_dependencies(&root, &mut |_: &PluginDescriptor, _| {
                panic!("idempotent scoped start must not authorize")
            })?;
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
        }
    }
    Ok(())
}

#[test]
fn scoped_start_skips_running_dependencies_and_excludes_unrelated_failure() -> TestResult {
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration("b", &["a"], &log, Behavior::default())?,
        registration("root", &["b"], &log, Behavior::default())?,
        registration(
            "unrelated",
            &[],
            &log,
            Behavior {
                fail: Some(PluginAction::Initialize),
                ..Behavior::default()
            },
        )?,
    ])?;
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let unrelated = PluginId::new("unrelated")?;
    assert!(manager.initialize(&unrelated, &mut allow).is_err());
    let unrelated_before = manager.status(&unrelated).cloned();
    manager.start_with_dependencies(&b, &mut allow)?;
    let a_before = manager.status(&a).cloned();
    let b_before = manager.status(&b).cloned();
    log.borrow_mut().clear();
    manager.drain_events().for_each(drop);
    let preview = manager.plan_startup(&PluginId::new("root")?)?;
    assert!(preview.can_start());
    assert_eq!(
        preview
            .steps()
            .iter()
            .map(|step| step.disposition)
            .collect::<Vec<_>>(),
        [
            StartupDisposition::AlreadyRunning,
            StartupDisposition::AlreadyRunning,
            StartupDisposition::Start
        ]
    );
    manager.start_with_dependencies(
        &PluginId::new("root")?,
        &mut |d: &PluginDescriptor, action| {
            assert_eq!(d.id.as_str(), "root");
            allow(d, action)
        },
    )?;
    assert_eq!(
        *log.borrow(),
        ["root:Initialize", "root:Start", "root:Readiness"]
    );
    assert_eq!(manager.drain_events().count(), 3);
    assert_eq!(manager.status(&a), a_before.as_ref());
    assert_eq!(manager.status(&b), b_before.as_ref());
    assert_eq!(manager.status(&unrelated), unrelated_before.as_ref());
    manager.stop_all()?;
    Ok(())
}

#[test]
fn scoped_start_preflights_every_required_state_and_unknown_root() -> TestResult {
    for state in [
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
                    fail: (state == PluginState::Failed).then_some(PluginAction::Initialize),
                    ..Behavior::default()
                },
            )?,
            registration("c", &["b"], &log, Behavior::default())?,
            registration("root", &["a", "c"], &log, Behavior::default())?,
        ])?;
        let b = PluginId::new("b")?;
        let old_preview = manager.plan_startup(&PluginId::new("root")?)?;
        assert!(old_preview.can_start());
        let initialized = manager.initialize(&b, &mut allow);
        if state == PluginState::Failed {
            assert!(initialized.is_err());
        } else {
            initialized?;
            match state {
                PluginState::Starting => {
                    assert!(
                        manager
                            .start(&b, &mut |d: &PluginDescriptor, action| {
                                if action == PluginAction::Readiness {
                                    Err("revoked".into())
                                } else {
                                    allow(d, action)
                                }
                            })
                            .is_err()
                    );
                }
                PluginState::Paused => {
                    manager.start(&b, &mut allow)?;
                    manager.pause(&b, &mut allow)?;
                }
                PluginState::Stopped => manager.stop(&b)?,
                _ => {}
            }
        }
        let before = manager
            .order()
            .iter()
            .map(|id| manager.status(id).cloned())
            .collect::<Vec<_>>();
        log.borrow_mut().clear();
        manager.drain_events().for_each(drop);
        let loss = manager.lost_events();
        for name in ["root", "missing"] {
            let id = PluginId::new(name)?;
            if name == "missing" {
                assert_eq!(
                    manager.plan_startup(&id),
                    Err(PluginError::UnknownPlugin(id.clone()))
                );
            } else {
                let preview = manager.plan_startup(&id)?;
                assert!(!preview.can_start());
                assert_eq!(preview.steps().len(), 4);
                for step in preview.steps() {
                    assert_eq!(
                        step.snapshot,
                        PluginSnapshot::from(manager.status(&step.id).expect("status"))
                    );
                    assert_eq!(
                        step.disposition,
                        if step.id == b {
                            StartupDisposition::InvalidState
                        } else {
                            StartupDisposition::Start
                        }
                    );
                }
                assert!(old_preview.can_start());
            }
            let expected = if name == "missing" {
                PluginError::UnknownPlugin(id.clone())
            } else {
                PluginError::InvalidTransition(b.clone(), state)
            };
            assert_eq!(
                manager.start_with_dependencies(&id, &mut |_: &PluginDescriptor, _| {
                    panic!("preflight must not authorize")
                }),
                Err(expected)
            );
        }
        assert_eq!(
            manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>(),
            before
        );
        assert!(log.borrow().is_empty());
        assert_eq!(manager.drain_events().count(), 0);
        assert_eq!(manager.lost_events(), loss);
        manager.stop_all()?;
    }
    Ok(())
}

#[test]
fn scoped_start_running_not_ready_root_or_prerequisite_rejects_without_probing() -> TestResult {
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
        registration("root", &["b"], &log, Behavior::default())?,
    ])?;
    let a = PluginId::new("a")?;
    manager.start_with_dependencies(&a, &mut allow)?;
    let old_preview = manager.plan_startup(&PluginId::new("root")?)?;
    assert!(old_preview.can_start());
    *health.borrow_mut() = PluginOutcome::NotReady;
    assert_eq!(
        manager.check_health(&a, &mut allow)?,
        PluginHealth::NotReady
    );
    let before = manager.status(&a).cloned();
    log.borrow_mut().clear();
    manager.drain_events().for_each(drop);
    for name in ["a", "root"] {
        let preview = manager.plan_startup(&PluginId::new(name)?)?;
        assert!(!preview.can_start());
        assert_eq!(preview.steps()[0].id, a);
        assert_eq!(preview.steps()[0].disposition, StartupDisposition::NotReady);
        assert!(
            preview.steps()[1..]
                .iter()
                .all(|step| { step.disposition == StartupDisposition::Start })
        );
        assert_eq!(
            manager.start_with_dependencies(
                &PluginId::new(name)?,
                &mut |_: &PluginDescriptor, _| panic!("no probing or authorization")
            ),
            Err(PluginError::DependencyNotReady(a.clone()))
        );
    }
    assert_eq!(manager.status(&a), before.as_ref());
    assert_eq!(
        manager.status(&PluginId::new("b")?).expect("status").state,
        PluginState::Registered
    );
    assert!(log.borrow().is_empty());
    assert_eq!(manager.drain_events().count(), 0);
    assert!(old_preview.can_start());
    manager.stop_all()?;
    Ok(())
}

#[test]
fn startup_preview_reports_all_blockers_without_retaining_callback_details() -> TestResult {
    for outcome in [PluginOutcome::Error, PluginOutcome::Panicked] {
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
            registration(
                "b",
                &[],
                &log,
                Behavior {
                    health: Some(Rc::new(RefCell::new(outcome))),
                    ..Behavior::default()
                },
            )?,
            registration("child", &["a", "b"], &log, Behavior::default())?,
            registration("root", &["child"], &log, Behavior::default())?,
        ])?;
        let a = PluginId::new("a")?;
        manager.start_with_dependencies(&a, &mut allow)?;
        *health.borrow_mut() = PluginOutcome::NotReady;
        manager.check_health(&a, &mut allow)?;
        let b = PluginId::new("b")?;
        manager.initialize(&b, &mut allow)?;
        assert!(matches!(
            manager.start(&b, &mut allow),
            Err(PluginError::Callback(..))
        ));
        log.borrow_mut().clear();
        manager.drain_events().for_each(drop);
        let root = PluginId::new("root")?;
        let preview = manager.plan_startup(&root)?;
        assert!(!preview.can_start());
        assert_eq!(
            preview
                .steps()
                .iter()
                .map(|step| step.disposition)
                .collect::<Vec<_>>(),
            [
                StartupDisposition::NotReady,
                StartupDisposition::InvalidState,
                StartupDisposition::Start,
                StartupDisposition::Start
            ]
        );
        assert!(preview.steps()[1].snapshot.failed);
        let redacted = format!("{preview:?}");
        for private in [
            "private-health-secret",
            "plugin callback panicked",
            "plugin-evidence",
        ] {
            assert!(!redacted.contains(private));
        }
        assert_eq!(
            manager.start_with_dependencies(&root, &mut |_: &PluginDescriptor, _| {
                panic!("whole-scope preflight must reject before authorization")
            }),
            Err(PluginError::DependencyNotReady(a))
        );
        assert!(log.borrow().is_empty());
        assert_eq!(manager.drain_events().count(), 0);
        manager.stop_all()?;
    }
    Ok(())
}

#[test]
fn scoped_start_authorization_rejection_keeps_partial_progress_without_rollback() -> TestResult {
    for (denied, state, callbacks) in [
        (PluginAction::Initialize, PluginState::Registered, 0),
        (PluginAction::Start, PluginState::Initialized, 1),
        (PluginAction::Readiness, PluginState::Starting, 2),
    ] {
        let log = Log::default();
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration("root", &["a"], &log, Behavior::default())?,
            registration("unrelated", &[], &log, Behavior::default())?,
        ])?;
        let root = PluginId::new("root")?;
        manager.drain_events().for_each(drop);
        assert!(manager.plan_startup(&root)?.can_start());
        let mut authorizations = Vec::new();
        let result = manager.start_with_dependencies(&root, &mut |d: &PluginDescriptor, action| {
            authorizations.push((d.id.clone(), action));
            if d.id == root && action == denied {
                Err("revoked".into())
            } else {
                allow(d, action)
            }
        });
        assert_eq!(
            result,
            Err(PluginError::Authorization(root.clone(), "revoked".into()))
        );
        let status = manager.status(&root).expect("status");
        assert_eq!(status.state, state);
        assert_eq!(status.cleanup_pending, callbacks > 0);
        assert_eq!(status.health, PluginHealth::Unknown);
        assert!(status.failure.is_none());
        assert!(status.cleanup_error.is_none());
        assert_eq!(
            manager.status(&PluginId::new("a")?).expect("status").state,
            PluginState::Running
        );
        assert_eq!(
            manager
                .status(&PluginId::new("unrelated")?)
                .expect("status")
                .state,
            PluginState::Registered
        );
        assert_eq!(log.borrow().len(), 3 + callbacks);
        assert!(!log.borrow().iter().any(|call| call.ends_with(":Stop")));
        assert_eq!(authorizations.len(), 4 + callbacks);
        let events: Vec<_> = manager.drain_events().collect();
        assert_eq!(events.len(), 4 + callbacks);
        let rejection = events.last().expect("rejection event");
        assert_eq!(
            rejection.kind,
            PluginEventKind::AuthorizationRejected(denied)
        );
        assert_eq!(rejection.previous, rejection.current);
        if callbacks > 0 {
            assert_eq!(
                manager.start_with_dependencies(&root, &mut allow),
                Err(PluginError::InvalidTransition(root.clone(), state))
            );
        }
        manager.stop_all()?;
    }
    Ok(())
}

#[test]
fn scoped_start_callback_failures_rollback_only_new_ownership() -> TestResult {
    for action in [
        PluginAction::Initialize,
        PluginAction::Start,
        PluginAction::Readiness,
    ] {
        for outcome in [
            PluginOutcome::Error,
            PluginOutcome::Panicked,
            PluginOutcome::NotReady,
        ] {
            if outcome == PluginOutcome::NotReady && action != PluginAction::Readiness {
                continue;
            }
            let log = Log::default();
            let mut manager = PluginManager::new(vec![
                registration("existing", &[], &log, Behavior::default())?,
                registration("held", &["existing"], &log, Behavior::default())?,
                registration("a", &["existing"], &log, Behavior::default())?,
                registration(
                    "b",
                    &["a"],
                    &log,
                    Behavior {
                        fail: (outcome == PluginOutcome::Error).then_some(action),
                        panic: (outcome == PluginOutcome::Panicked).then_some(action),
                        not_ready: outcome == PluginOutcome::NotReady,
                        ..Behavior::default()
                    },
                )?,
                registration("z", &["existing"], &log, Behavior::default())?,
                registration("root", &["b", "z"], &log, Behavior::default())?,
            ])?;
            let existing = PluginId::new("existing")?;
            let held = PluginId::new("held")?;
            manager.start_with_dependencies(&held, &mut allow)?;
            let existing_before = manager.status(&existing).cloned();
            let held_before = manager.status(&held).cloned();
            log.borrow_mut().clear();
            manager.drain_events().for_each(drop);
            let result = manager.start_with_dependencies(&PluginId::new("root")?, &mut allow);
            let Err(PluginError::Callback(id, failure)) = result else {
                panic!("expected callback failure");
            };
            assert_eq!(id.as_str(), "b");
            assert_eq!(failure.action, action);
            assert_eq!(failure.panicked, outcome == PluginOutcome::Panicked);
            assert_eq!(
                manager.status(&id).expect("status").failure.as_ref(),
                Some(&failure)
            );
            assert!(!manager.status(&id).expect("status").cleanup_pending);
            assert_eq!(manager.status(&existing), existing_before.as_ref());
            assert_eq!(manager.status(&held), held_before.as_ref());
            let stops: Vec<_> = log
                .borrow()
                .iter()
                .filter(|call| call.ends_with(":Stop"))
                .cloned()
                .collect();
            assert_eq!(stops, ["b:Stop", "a:Stop"]);
            assert_eq!(
                manager.status(&PluginId::new("z")?).expect("status").state,
                PluginState::Registered
            );
            assert_eq!(
                manager
                    .status(&PluginId::new("root")?)
                    .expect("status")
                    .state,
                PluginState::Registered
            );
            let events: Vec<_> = manager.drain_events().collect();
            assert!(events.iter().all(|event| {
                event.id != existing && event.id != held && event.id.as_str() != "root"
            }));
            manager.stop_all()?;
        }
    }
    Ok(())
}

#[test]
fn scoped_start_rollback_continues_independent_branches_and_retains_failed_cleanup_dependencies()
-> TestResult {
    for cleanup_outcome in [PluginOutcome::Error, PluginOutcome::Panicked] {
        let log = Log::default();
        let cleanup = Rc::new(RefCell::new(cleanup_outcome));
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration("b", &[], &log, Behavior::default())?,
            registration(
                "c",
                &["a"],
                &log,
                Behavior {
                    cleanup: Some(cleanup.clone()),
                    ..Behavior::default()
                },
            )?,
            registration(
                "root",
                &["b", "c"],
                &log,
                Behavior {
                    fail: Some(PluginAction::Start),
                    ..Behavior::default()
                },
            )?,
            registration("untouched", &[], &log, Behavior::default())?,
        ])?;
        let root = PluginId::new("root")?;
        let a = PluginId::new("a")?;
        let c = PluginId::new("c")?;
        let Err(PluginError::Callback(id, failure)) =
            manager.start_with_dependencies(&root, &mut allow)
        else {
            panic!("expected original startup failure");
        };
        assert_eq!(id, root);
        assert_eq!(failure.action, PluginAction::Start);
        assert_eq!(
            manager.status(&root).expect("status").failure.as_ref(),
            Some(&failure)
        );
        assert_eq!(
            log.borrow()
                .iter()
                .filter(|call| call.ends_with(":Stop"))
                .cloned()
                .collect::<Vec<_>>(),
            ["root:Stop", "c:Stop", "b:Stop"]
        );
        assert!(manager.status(&a).expect("status").cleanup_pending);
        assert!(manager.status(&c).expect("status").cleanup_pending);
        let cleanup_error = manager
            .status(&c)
            .expect("status")
            .cleanup_error
            .clone()
            .expect("cleanup failure");
        assert_eq!(
            cleanup_error.panicked,
            cleanup_outcome == PluginOutcome::Panicked
        );
        assert_eq!(
            manager.stop(&a),
            Err(PluginError::DependencyInUse(c.clone()))
        );
        *cleanup.borrow_mut() = PluginOutcome::Success;
        log.borrow_mut().clear();
        manager.stop_all()?;
        assert_eq!(*log.borrow(), ["c:Stop", "a:Stop"]);
        assert_eq!(
            manager.status(&root).expect("status").failure.as_ref(),
            Some(&failure)
        );
        assert_eq!(
            manager.status(&c).expect("status").failure.as_ref(),
            Some(&cleanup_error)
        );
        assert!(manager.status(&c).expect("status").cleanup_error.is_none());
        assert_eq!(
            manager
                .status(&PluginId::new("untouched")?)
                .expect("status")
                .state,
            PluginState::Registered
        );
    }
    Ok(())
}

#[test]
fn shutdown_reports_empty_unknown_noops_and_live_single_blockers() -> TestResult {
    let mut empty = PluginManager::new(vec![])?;
    let report = empty.execute_shutdown(ShutdownScope::All)?;
    assert!(report.complete());
    assert!(report.entries().is_empty());
    let log = Log::default();
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration("b", &["a"], &log, Behavior::default())?,
        registration("c", &["a"], &log, Behavior::default())?,
    ])?;
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let c = PluginId::new("c")?;
    manager.drain_events().for_each(drop);
    let before = manager.status(&a).cloned();
    for scope in [
        ShutdownScope::Single(PluginId::new("missing")?),
        ShutdownScope::WithDependents(PluginId::new("missing")?),
    ] {
        assert!(matches!(
            manager.execute_shutdown(scope),
            Err(PluginError::UnknownPlugin(_))
        ));
    }
    assert_eq!(manager.status(&a), before.as_ref());
    assert!(log.borrow().is_empty());
    assert_eq!(manager.drain_events().count(), 0);
    manager.initialize(&b, &mut allow)?;
    // Registered a is a no-op even while a dependent owns resources.
    let report = manager.execute_shutdown(ShutdownScope::Single(a.clone()))?;
    assert!(report.complete());
    assert_eq!(report.entries()[0].outcome, ShutdownOutcome::NoOp);
    assert!(report.entries()[0].blockers.is_empty());
    assert_eq!(manager.status(&a), before.as_ref());
    manager.initialize(&a, &mut allow)?;
    manager.initialize(&c, &mut allow)?;
    manager.drain_events().for_each(drop);
    log.borrow_mut().clear();
    let before = manager.status(&a).cloned();
    let loss = manager.lost_events();
    let report = manager.execute_shutdown(ShutdownScope::Single(a.clone()))?;
    assert!(!report.complete());
    let entry = &report.entries()[0];
    assert_eq!(entry.outcome, ShutdownOutcome::Blocked);
    assert_eq!(entry.blockers, [b.clone(), c.clone()]);
    assert_eq!(entry.previous, entry.current);
    assert_eq!(
        manager.stop(&a),
        Err(PluginError::DependencyInUse(b.clone()))
    );
    assert_eq!(manager.status(&a), before.as_ref());
    assert!(log.borrow().is_empty());
    assert_eq!(manager.drain_events().count(), 0);
    assert_eq!(manager.lost_events(), loss);
    // Fresh execution observes the successful cleanup, not a cached preview.
    let preview = manager.plan_shutdown(ShutdownScope::WithDependents(a.clone()))?;
    assert_eq!(preview[2].blockers, [b, c]);
    let report = manager.execute_shutdown(ShutdownScope::WithDependents(a))?;
    assert!(report.complete());
    assert_eq!(
        report
            .entries()
            .iter()
            .map(|e| e.id.as_str())
            .collect::<Vec<_>>(),
        ["c", "b", "a"]
    );
    assert!(
        report
            .entries()
            .iter()
            .all(|e| { e.outcome == ShutdownOutcome::Stopped && e.blockers.is_empty() })
    );
    assert_eq!(manager.drain_events().count(), 3);
    let before = manager
        .order()
        .iter()
        .map(|id| manager.status(id).cloned())
        .collect::<Vec<_>>();
    log.borrow_mut().clear();
    let report = manager.execute_shutdown(ShutdownScope::All)?;
    assert!(report.complete());
    assert!(
        report
            .entries()
            .iter()
            .all(|e| e.outcome == ShutdownOutcome::NoOp && e.previous == e.current)
    );
    assert_eq!(
        manager
            .order()
            .iter()
            .map(|id| manager.status(id).cloned())
            .collect::<Vec<_>>(),
        before
    );
    assert!(log.borrow().is_empty());
    assert_eq!(manager.drain_events().count(), 0);
    Ok(())
}

#[test]
fn shutdown_reports_partial_failure_retry_redaction_and_scoped_completeness() -> TestResult {
    for all in [false, true] {
        for capacity in [0, 1, 256] {
            let log = Log::default();
            let error = Rc::new(RefCell::new(PluginOutcome::Error));
            let panic = Rc::new(RefCell::new(PluginOutcome::Panicked));
            let mut manager = PluginManager::with_event_capacity(
                vec![
                    registration("a", &[], &log, Behavior::default())?,
                    registration("b", &["a"], &log, Behavior::default())?,
                    registration(
                        "c",
                        &["b"],
                        &log,
                        Behavior {
                            cleanup: Some(error.clone()),
                            ..Behavior::default()
                        },
                    )?,
                    registration(
                        "d",
                        &["a"],
                        &log,
                        Behavior {
                            cleanup: Some(panic.clone()),
                            ..Behavior::default()
                        },
                    )?,
                    registration("e", &["a"], &log, Behavior::default())?,
                    registration("unrelated", &[], &log, Behavior::default())?,
                ],
                capacity,
            )?;
            manager.start_all(&mut allow)?;
            let id = |name| PluginId::new(name).expect("ID");
            let scope = if all {
                ShutdownScope::All
            } else {
                ShutdownScope::WithDependents(id("a"))
            };
            manager.drain_events().for_each(drop);
            log.borrow_mut().clear();
            let loss = manager.lost_events();
            let report = manager.execute_shutdown(scope.clone())?;
            assert!(!report.complete());
            let entries = report.entries();
            assert_eq!(
                entries.iter().map(|e| e.id.as_str()).collect::<Vec<_>>(),
                if all {
                    vec!["unrelated", "e", "d", "c", "b", "a"]
                } else {
                    vec!["e", "d", "c", "b", "a"]
                }
            );
            let entries = &entries[usize::from(all)..];
            assert_eq!(
                entries.iter().map(|e| e.outcome).collect::<Vec<_>>(),
                [
                    ShutdownOutcome::Stopped,
                    ShutdownOutcome::Panicked,
                    ShutdownOutcome::Error,
                    ShutdownOutcome::Blocked,
                    ShutdownOutcome::Blocked,
                ]
            );
            assert_eq!(entries[3].blockers, [id("c")]);
            // e is already clean; only still-pending direct dependents block a.
            assert_eq!(entries[4].blockers, [id("b"), id("d")]);
            assert_eq!(
                *log.borrow(),
                if all {
                    vec!["unrelated:Stop", "e:Stop", "d:Stop", "c:Stop"]
                } else {
                    vec!["e:Stop", "d:Stop", "c:Stop"]
                }
            );
            let callback_count = 3 + usize::from(all);
            assert_eq!(manager.drain_events().count(), capacity.min(callback_count));
            assert_eq!(
                manager.lost_events() - loss,
                callback_count.saturating_sub(capacity) as u64
            );
            for secret in ["private-cleanup-secret", "plugin-evidence", "host-evidence"] {
                assert!(!format!("{report:?}").contains(secret));
            }
            let failures =
                ["c", "d"].map(|name| manager.status(&id(name)).expect("status").failure.clone());
            assert_eq!(
                failures[0].as_ref().expect("failure").message,
                "private-cleanup-secret"
            );
            assert!(failures[1].as_ref().expect("failure").panicked);
            *error.borrow_mut() = PluginOutcome::Success;
            *panic.borrow_mut() = PluginOutcome::Success;
            log.borrow_mut().clear();
            let retry = manager.execute_shutdown(scope.clone())?;
            assert!(retry.complete());
            assert!(!report.complete()); // Owned observation does not change on retry.
            assert_eq!(*log.borrow(), ["d:Stop", "c:Stop", "b:Stop", "a:Stop"]);
            for (name, failure) in ["c", "d"].into_iter().zip(failures) {
                let status = manager.status(&id(name)).expect("status");
                assert_eq!(status.failure, failure);
                assert_eq!(status.state, PluginState::Failed);
                assert!(status.cleanup_error.is_none());
                let entry = retry
                    .entries()
                    .iter()
                    .find(|e| e.id == id(name))
                    .expect("entry");
                assert_eq!(entry.outcome, ShutdownOutcome::Stopped);
                assert_eq!(entry.current.state, PluginState::Failed);
                assert!(!entry.current.cleanup_pending);
            }
            assert_eq!(
                manager.status(&id("unrelated")).expect("status").state,
                if all {
                    PluginState::Stopped
                } else {
                    PluginState::Running
                }
            );
            manager.drain_events().for_each(drop);
            let statuses = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>();
            let loss = manager.lost_events();
            let noop = manager.execute_shutdown(scope)?;
            assert!(noop.complete());
            assert!(
                noop.entries()
                    .iter()
                    .all(|e| e.outcome == ShutdownOutcome::NoOp
                        && e.previous == e.current
                        && e.blockers.is_empty())
            );
            assert_eq!(
                manager
                    .order()
                    .iter()
                    .map(|id| manager.status(id).cloned())
                    .collect::<Vec<_>>(),
                statuses
            );
            assert_eq!(manager.drain_events().count(), 0);
            assert_eq!(manager.lost_events(), loss);
            manager.stop_all()?;
        }
    }
    Ok(())
}

#[test]
fn shutdown_report_scopes_traverse_inactive_intermediaries() -> TestResult {
    for cleaned in [false, true] {
        for all in [false, true] {
            let log = Log::default();
            let mut manager = PluginManager::new(vec![
                registration("a", &[], &log, Behavior::default())?,
                registration("b", &["a"], &log, Behavior::default())?,
                registration("c", &["b"], &log, Behavior::default())?,
                registration("unrelated", &[], &log, Behavior::default())?,
            ])?;
            let b = PluginId::new("b")?;
            if cleaned {
                manager.initialize(&b, &mut allow)?;
                manager.stop(&b)?;
            }
            manager.initialize(&PluginId::new("c")?, &mut allow)?;
            let before = manager.status(&b).cloned();
            manager.drain_events().for_each(drop);
            log.borrow_mut().clear();
            let scope = if all {
                ShutdownScope::All
            } else {
                ShutdownScope::WithDependents(PluginId::new("a")?)
            };
            let report = manager.execute_shutdown(scope)?;
            assert!(report.complete());
            let entries = &report.entries()[usize::from(all)..];
            assert_eq!(
                entries.iter().map(|e| e.id.as_str()).collect::<Vec<_>>(),
                ["c", "b", "a"]
            );
            assert_eq!(
                entries.iter().map(|e| e.outcome).collect::<Vec<_>>(),
                [
                    ShutdownOutcome::Stopped,
                    ShutdownOutcome::NoOp,
                    ShutdownOutcome::NoOp
                ]
            );
            assert!(entries.iter().all(|e| e.blockers.is_empty()));
            assert_eq!(manager.status(&b), before.as_ref());
            assert_eq!(*log.borrow(), ["c:Stop"]);
            assert_eq!(manager.drain_events().count(), 1);
        }
    }
    Ok(())
}

#[test]
fn shutdown_single_report_retains_original_failure_and_other_running_plugins() -> TestResult {
    let log = Log::default();
    let health = Rc::new(RefCell::new(PluginOutcome::Success));
    let cleanup = Rc::new(RefCell::new(PluginOutcome::Error));
    let mut manager = PluginManager::new(vec![
        registration("prerequisite", &[], &log, Behavior::default())?,
        registration("unrelated", &[], &log, Behavior::default())?,
        registration(
            "root",
            &["prerequisite"],
            &log,
            Behavior {
                health: Some(health.clone()),
                cleanup: Some(cleanup.clone()),
                ..Behavior::default()
            },
        )?,
    ])?;
    manager.start_all(&mut allow)?;
    let root = PluginId::new("root")?;
    *health.borrow_mut() = PluginOutcome::Error;
    assert!(manager.check_health(&root, &mut allow).is_err());
    let first = manager.status(&root).expect("status").failure.clone();
    manager.drain_events().for_each(drop);
    let report = manager.execute_shutdown(ShutdownScope::Single(root.clone()))?;
    assert!(!report.complete());
    assert_eq!(report.entries().len(), 1);
    assert_eq!(report.entries()[0].outcome, ShutdownOutcome::Error);
    assert_eq!(manager.status(&root).expect("status").failure, first);
    *cleanup.borrow_mut() = PluginOutcome::Success;
    let report = manager.execute_shutdown(ShutdownScope::Single(root.clone()))?;
    assert!(report.complete());
    assert_eq!(report.entries()[0].outcome, ShutdownOutcome::Stopped);
    assert_eq!(report.entries()[0].current.state, PluginState::Failed);
    assert_eq!(manager.status(&root).expect("status").failure, first);
    for name in ["prerequisite", "unrelated"] {
        assert_eq!(
            manager.status(&PluginId::new(name)?).expect("status").state,
            PluginState::Running
        );
    }
    manager.stop_all()?;
    Ok(())
}

#[test]
fn shutdown_preview_is_read_only_including_queue_loss_sequence_and_authorization() -> TestResult {
    for capacity in [0, 2, 64] {
        let logs = [Log::default(), Log::default()];
        let mut managers = Vec::new();
        for log in &logs {
            managers.push(PluginManager::with_event_capacity(
                vec![
                    registration("a", &[], log, Behavior::default())?,
                    registration("c", &["a"], log, Behavior::default())?,
                    registration("b", &["a"], log, Behavior::default())?,
                ],
                capacity,
            )?);
        }
        let a = PluginId::new("a")?;
        let missing = PluginId::new("missing")?;
        for phase in [
            PluginState::Registered,
            PluginState::Running,
            PluginState::Stopped,
        ] {
            if phase != PluginState::Registered {
                for (manager, log) in managers.iter_mut().zip(&logs) {
                    if phase == PluginState::Running {
                        manager.start_all(&mut |descriptor: &PluginDescriptor, action| {
                            log.borrow_mut().push(format!("authorize:{action:?}"));
                            allow(descriptor, action)
                        })?;
                    } else {
                        manager.stop_all()?;
                    }
                }
            }
            let manager = &managers[0];
            let statuses = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>();
            let before_log = logs[0].borrow().clone();
            let before_loss = manager.lost_events();
            for _ in 0..3 {
                for scope in [
                    ShutdownScope::Single(a.clone()),
                    ShutdownScope::WithDependents(a.clone()),
                    ShutdownScope::All,
                ] {
                    let preview = manager.plan_shutdown(scope)?;
                    let root = preview.last().expect("root");
                    assert_eq!(root.id, a);
                    assert_eq!(root.snapshot.state, phase);
                    assert_eq!(root.snapshot.cleanup_pending, phase == PluginState::Running);
                    assert_eq!(
                        root.blockers
                            .iter()
                            .map(PluginId::as_str)
                            .collect::<Vec<_>>(),
                        if phase == PluginState::Running {
                            vec!["b", "c"]
                        } else {
                            vec![]
                        }
                    );
                }
                for scope in [
                    ShutdownScope::Single(missing.clone()),
                    ShutdownScope::WithDependents(missing.clone()),
                ] {
                    assert_eq!(
                        manager.plan_shutdown(scope),
                        Err(PluginError::UnknownPlugin(missing.clone()))
                    );
                }
            }
            assert_eq!(
                manager
                    .order()
                    .iter()
                    .map(|id| manager.status(id).cloned())
                    .collect::<Vec<_>>(),
                statuses
            );
            assert_eq!(*logs[0].borrow(), before_log);
            assert_eq!(manager.lost_events(), before_loss);
            assert_eq!(*logs[0].borrow(), *logs[1].borrow());
            let observed = managers[0].drain_events().collect::<Vec<_>>();
            let control = managers[1].drain_events().collect::<Vec<_>>();
            assert_eq!(observed, control);
            assert_eq!(managers[0].lost_events(), managers[1].lost_events());
        }
    }
    let empty = PluginManager::new(vec![])?;
    assert!(empty.plan_shutdown(ShutdownScope::All)?.is_empty());
    for scope in [
        ShutdownScope::Single(PluginId::new("missing")?),
        ShutdownScope::WithDependents(PluginId::new("missing")?),
    ] {
        assert!(matches!(
            empty.plan_shutdown(scope),
            Err(PluginError::UnknownPlugin(_))
        ));
    }
    Ok(())
}

#[test]
fn scoped_stop_closure_is_deterministic_and_excludes_prerequisites_and_other_branches() -> TestResult
{
    for diamond in [false, true] {
        for permutation in [
            [0, 1, 2, 3, 4, 5, 6],
            [6, 5, 4, 3, 2, 1, 0],
            [3, 0, 6, 2, 5, 1, 4],
        ] {
            let log = Log::default();
            let graph: [(&str, &[&str]); 7] = [
                ("prerequisite", &[]),
                ("root", &["prerequisite"]),
                ("b", &["root"]),
                ("c", if diamond { &["root"] } else { &["b"] }),
                ("d", &["b", "c", "shared"]),
                ("shared", &[]),
                ("unrelated", &["prerequisite", "shared"]),
            ];
            let mut manager = PluginManager::new(
                permutation
                    .into_iter()
                    .map(|index| {
                        let (id, dependencies) = graph[index];
                        registration(id, dependencies, &log, Behavior::default())
                    })
                    .collect::<Result<_, _>>()?,
            )?;
            manager.start_all(&mut allow)?;
            let retained = ["prerequisite", "shared", "unrelated"]
                .map(|name| PluginId::new(name).expect("valid ID"));
            let before = retained.each_ref().map(|id| manager.status(id).cloned());
            manager.drain_events().for_each(drop);
            log.borrow_mut().clear();
            let root = PluginId::new("root")?;
            let missing = PluginId::new("missing")?;
            let statuses = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>();
            assert_eq!(
                manager.stop_with_dependents(&missing),
                Err(PluginError::UnknownPlugin(missing))
            );
            assert_eq!(
                manager
                    .order()
                    .iter()
                    .map(|id| manager.status(id).cloned())
                    .collect::<Vec<_>>(),
                statuses
            );
            assert!(log.borrow().is_empty());
            assert_eq!(manager.drain_events().count(), 0);
            // Revoked operational authority cannot prevent cleanup or be consulted by it.
            let mut revoked = |_: &PluginDescriptor, _: PluginAction| plan(AuthorityState::Revoked);
            assert!(matches!(
                manager.check_health(&root, &mut revoked),
                Err(PluginError::Authorization(..))
            ));
            manager.drain_events().for_each(drop);
            let preview = manager.plan_shutdown(ShutdownScope::WithDependents(root.clone()))?;
            assert_eq!(
                preview
                    .iter()
                    .map(|step| step.id.as_str())
                    .collect::<Vec<_>>(),
                ["d", "c", "b", "root"]
            );
            let fleet = manager.plan_shutdown(ShutdownScope::All)?;
            assert_eq!(
                fleet
                    .iter()
                    .map(|step| step.id.as_str())
                    .collect::<Vec<_>>(),
                ["unrelated", "d", "shared", "c", "b", "root", "prerequisite"]
            );
            assert_eq!(
                fleet.iter().map(|step| &step.id).collect::<Vec<_>>(),
                manager.order().iter().rev().collect::<Vec<_>>()
            );
            let single = manager.plan_shutdown(ShutdownScope::Single(root.clone()))?;
            assert_eq!(single.len(), 1);
            assert_eq!(
                single[0]
                    .blockers
                    .iter()
                    .map(PluginId::as_str)
                    .collect::<Vec<_>>(),
                if diamond { vec!["b", "c"] } else { vec!["b"] }
            );
            manager.stop_with_dependents(&root)?;
            assert_eq!(*log.borrow(), ["d:Stop", "c:Stop", "b:Stop", "root:Stop"]);
            assert_eq!(
                *log.borrow(),
                preview
                    .iter()
                    .filter(|step| step.snapshot.cleanup_pending)
                    .map(|step| format!("{}:Stop", step.id.as_str()))
                    .collect::<Vec<_>>()
            );
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(
                events
                    .iter()
                    .map(|event| event.id.as_str())
                    .collect::<Vec<_>>(),
                ["d", "c", "b", "root"]
            );
            assert!(events.iter().all(|event| event.kind
                == PluginEventKind::Callback(PluginAction::Stop)
                && event.outcome == PluginOutcome::Success));
            assert!(
                events
                    .windows(2)
                    .all(|pair| pair[0].sequence + 1 == pair[1].sequence)
            );
            for (id, status) in retained.iter().zip(&before) {
                assert_eq!(manager.status(id), status.as_ref());
                assert_eq!(
                    manager.status(id).expect("status").state,
                    PluginState::Running
                );
            }
            let cleaned = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>();
            manager.stop_with_dependents(&root)?;
            assert_eq!(
                manager
                    .order()
                    .iter()
                    .map(|id| manager.status(id).cloned())
                    .collect::<Vec<_>>(),
                cleaned
            );
            assert_eq!(manager.drain_events().count(), 0);
            assert_eq!(log.borrow().len(), 4);
            manager.stop_all()?;
        }
    }
    Ok(())
}

#[test]
fn scoped_stop_traverses_registered_and_already_cleaned_intermediaries() -> TestResult {
    for cleaned in [false, true] {
        let log = Log::default();
        let a = PluginId::new("a")?;
        let b = PluginId::new("b")?;
        let c = PluginId::new("c")?;
        let mut manager = PluginManager::new(vec![
            registration("c", &["b"], &log, Behavior::default())?,
            registration("b", &["a"], &log, Behavior::default())?,
            registration("a", &[], &log, Behavior::default())?,
        ])?;
        // Individual initialization does not require initialized dependencies.
        if cleaned {
            manager.initialize(&b, &mut allow)?;
            manager.stop(&b)?;
        }
        let intermediary = manager.status(&b).cloned();
        let root = manager.status(&a).cloned();
        manager.initialize(&c, &mut allow)?;
        log.borrow_mut().clear();
        manager.drain_events().for_each(drop);
        let preview = manager.plan_shutdown(ShutdownScope::WithDependents(a.clone()))?;
        assert_eq!(
            preview
                .iter()
                .map(|step| step.id.as_str())
                .collect::<Vec<_>>(),
            ["c", "b", "a"]
        );
        assert_eq!(preview[1].blockers, std::slice::from_ref(&c));
        assert!(!preview[1].snapshot.cleanup_pending);
        assert_eq!(
            preview[1].snapshot.state,
            if cleaned {
                PluginState::Stopped
            } else {
                PluginState::Registered
            }
        );
        assert!(!preview[2].snapshot.cleanup_pending);
        manager.stop_with_dependents(&a)?;
        assert_eq!(*log.borrow(), ["c:Stop"]);
        assert_eq!(manager.status(&a), root.as_ref());
        assert_eq!(manager.status(&b), intermediary.as_ref());
        assert_eq!(manager.drain_events().count(), 1);
        let statuses = [&a, &b, &c].map(|id| manager.status(id).cloned());
        manager.stop_with_dependents(&a)?;
        assert_eq!([&a, &b, &c].map(|id| manager.status(id).cloned()), statuses);
        assert_eq!(manager.drain_events().count(), 0);
        assert_eq!(log.borrow().len(), 1);
    }
    Ok(())
}

#[test]
fn scoped_stop_continues_independent_branches_and_retries_failed_cleanup() -> TestResult {
    for panicked in [false, true] {
        let log = Log::default();
        let cleanup = Rc::new(RefCell::new(if panicked {
            PluginOutcome::Panicked
        } else {
            PluginOutcome::Error
        }));
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration("b", &["a"], &log, Behavior::default())?,
            registration("b-independent", &["a"], &log, Behavior::default())?,
            registration(
                "c",
                &["b"],
                &log,
                Behavior {
                    cleanup: Some(cleanup.clone()),
                    ..Behavior::default()
                },
            )?,
            registration("d", &["a"], &log, Behavior::default())?,
            registration(
                "e",
                &["d"],
                &log,
                Behavior {
                    cleanup_failures: 1,
                    ..Behavior::default()
                },
            )?,
            registration("f", &["a"], &log, Behavior::default())?,
        ])?;
        manager.start_all(&mut allow)?;
        let a = PluginId::new("a")?;
        let retained = ["a", "b", "d"].map(|name| PluginId::new(name).expect("ID"));
        let before = retained.each_ref().map(|id| manager.status(id).cloned());
        manager.drain_events().for_each(drop);
        log.borrow_mut().clear();
        let Err(PluginError::Callback(id, failure)) = manager.stop_with_dependents(&a) else {
            panic!("first reverse-topological callback error expected");
        };
        assert_eq!(id.as_str(), "e");
        assert!(!failure.panicked);
        assert_eq!(
            *log.borrow(),
            ["f:Stop", "e:Stop", "c:Stop", "b-independent:Stop"]
        );
        for (id, status) in retained.iter().zip(&before) {
            assert_eq!(manager.status(id), status.as_ref());
        }
        let c = PluginId::new("c")?;
        let e = PluginId::new("e")?;
        let first = [&c, &e].map(|id| manager.status(id).expect("status").failure.clone());
        assert_eq!(first[0].as_ref().expect("failure").panicked, panicked);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 4);
        assert_eq!(
            events[2].outcome,
            if panicked {
                PluginOutcome::Panicked
            } else {
                PluginOutcome::Error
            }
        );
        *cleanup.borrow_mut() = PluginOutcome::Success;
        log.borrow_mut().clear();
        let retry = manager.plan_shutdown(ShutdownScope::WithDependents(a.clone()))?;
        assert_eq!(
            retry
                .iter()
                .map(|step| step.id.as_str())
                .collect::<Vec<_>>(),
            ["f", "e", "d", "c", "b-independent", "b", "a"]
        );
        assert_eq!(retry[2].blockers, std::slice::from_ref(&e));
        assert_eq!(retry[5].blockers, std::slice::from_ref(&c));
        assert_eq!(
            retry[6]
                .blockers
                .iter()
                .map(PluginId::as_str)
                .collect::<Vec<_>>(),
            ["b", "d"]
        );
        for step in [&retry[1], &retry[3]] {
            assert!(
                step.snapshot.failed
                    && step.snapshot.cleanup_failed
                    && step.snapshot.cleanup_pending
            );
            assert_eq!(step.snapshot.state, PluginState::Failed);
        }
        assert!(!format!("{retry:?}").contains("private-cleanup-secret"));
        assert!(!format!("{retry:?}").contains("retry cleanup"));
        manager.stop_with_dependents(&a)?;
        assert_eq!(
            *log.borrow(),
            ["e:Stop", "d:Stop", "c:Stop", "b:Stop", "a:Stop"]
        );
        assert_eq!(
            *log.borrow(),
            retry
                .iter()
                .filter(|step| step.snapshot.cleanup_pending)
                .map(|step| format!("{}:Stop", step.id.as_str()))
                .collect::<Vec<_>>()
        );
        for (id, failure) in [&c, &e].into_iter().zip(first) {
            let status = manager.status(id).expect("status");
            assert_eq!(status.failure, failure);
            assert_eq!(status.state, PluginState::Failed);
            assert!(!status.cleanup_pending);
            assert!(status.cleanup_error.is_none());
            let preview = manager.plan_shutdown(ShutdownScope::Single(id.clone()))?;
            assert_eq!(preview[0].snapshot, PluginSnapshot::from(status));
            assert!(preview[0].snapshot.failed);
            assert!(!preview[0].snapshot.cleanup_failed);
            assert!(!preview[0].snapshot.cleanup_pending);
            assert!(preview[0].blockers.is_empty());
        }
        assert_eq!(manager.drain_events().count(), 5);
        let before = manager
            .order()
            .iter()
            .map(|id| manager.status(id).cloned())
            .collect::<Vec<_>>();
        manager.stop_with_dependents(&a)?;
        assert_eq!(
            manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect::<Vec<_>>(),
            before
        );
        assert_eq!(manager.drain_events().count(), 0);
        assert_eq!(log.borrow().len(), 5);
    }
    Ok(())
}

#[test]
fn selective_stop_unknown_and_registered_are_silent_and_registered_does_not_block() -> TestResult {
    let log = Log::default();
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let missing = PluginId::new("missing")?;
    let mut manager = PluginManager::new(vec![
        registration("a", &[], &log, Behavior::default())?,
        registration("b", &["a"], &log, Behavior::default())?,
    ])?;
    let registered = manager.status(&b).expect("status").clone();
    manager.drain_events().for_each(drop);
    assert_eq!(
        manager.stop(&missing),
        Err(PluginError::UnknownPlugin(missing))
    );
    manager.stop(&b)?;
    manager.stop(&b)?;
    assert_eq!(manager.status(&b), Some(&registered));
    assert!(log.borrow().is_empty());
    assert_eq!(manager.drain_events().count(), 0);
    manager.initialize(&a, &mut allow)?;
    manager.drain_events().for_each(drop);
    log.borrow_mut().clear();
    manager.stop(&a)?;
    let stopped = manager.status(&a).expect("status").clone();
    assert_eq!(stopped.state, PluginState::Stopped);
    assert_eq!(manager.status(&b), Some(&registered));
    assert_eq!(*log.borrow(), ["a:Stop"]);
    assert_eq!(manager.drain_events().count(), 1);
    manager.stop(&a)?;
    manager.stop(&b)?;
    manager.stop_all()?;
    assert_eq!(manager.status(&a), Some(&stopped));
    assert_eq!(manager.status(&b), Some(&registered));
    assert_eq!(*log.borrow(), ["a:Stop"]);
    assert_eq!(manager.drain_events().count(), 0);
    Ok(())
}

#[test]
fn selective_stop_guards_every_pending_dependent_state_without_side_effects() -> TestResult {
    for phase in [
        "initialized",
        "starting",
        "ready",
        "not-ready",
        "paused",
        "health-failed",
        "cleanup-failed",
    ] {
        let log = Log::default();
        let health = Rc::new(RefCell::new(PluginOutcome::Success));
        let a = PluginId::new("a")?;
        let b = PluginId::new("b")?;
        let mut manager = PluginManager::new(vec![
            registration("a", &[], &log, Behavior::default())?,
            registration(
                "b",
                &["a"],
                &log,
                Behavior {
                    health: Some(health.clone()),
                    cleanup_failures: usize::from(phase == "cleanup-failed"),
                    ..Behavior::default()
                },
            )?,
        ])?;
        manager.initialize(&a, &mut allow)?;
        manager.start(&a, &mut allow)?;
        manager.initialize(&b, &mut allow)?;
        let expected = match phase {
            "initialized" => PluginState::Initialized,
            "starting" => {
                let mut deny_readiness = |descriptor: &PluginDescriptor, action: PluginAction| {
                    if action == PluginAction::Readiness {
                        plan(AuthorityState::Revoked)
                    } else {
                        allow(descriptor, action)
                    }
                };
                assert!(matches!(
                    manager.start(&b, &mut deny_readiness),
                    Err(PluginError::Authorization(..))
                ));
                PluginState::Starting
            }
            _ => {
                manager.start(&b, &mut allow)?;
                match phase {
                    "paused" => {
                        manager.pause(&b, &mut allow)?;
                        PluginState::Paused
                    }
                    "not-ready" => {
                        *health.borrow_mut() = PluginOutcome::NotReady;
                        assert_eq!(
                            manager.check_health(&b, &mut allow)?,
                            PluginHealth::NotReady
                        );
                        PluginState::Running
                    }
                    "health-failed" => {
                        *health.borrow_mut() = PluginOutcome::Error;
                        assert!(matches!(
                            manager.check_health(&b, &mut allow),
                            Err(PluginError::Callback(..))
                        ));
                        PluginState::Failed
                    }
                    "cleanup-failed" => {
                        assert!(matches!(manager.stop(&b), Err(PluginError::Callback(..))));
                        PluginState::Failed
                    }
                    _ => PluginState::Running,
                }
            }
        };
        assert_eq!(manager.status(&b).expect("status").state, expected);
        assert!(manager.status(&b).expect("status").cleanup_pending);
        let before = [manager.status(&a).cloned(), manager.status(&b).cloned()];
        manager.drain_events().for_each(drop);
        log.borrow_mut().clear();
        assert_eq!(
            manager.stop(&a),
            Err(PluginError::DependencyInUse(b.clone())),
            "{phase}"
        );
        assert_eq!(
            [manager.status(&a).cloned(), manager.status(&b).cloned()],
            before
        );
        assert!(log.borrow().is_empty());
        assert_eq!(manager.drain_events().count(), 0);
        manager.stop_with_dependents(&a)?;
        assert_eq!(*log.borrow(), ["b:Stop", "a:Stop"]);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].id, b);
        assert_eq!(events[1].id, a);
        assert!(events.iter().all(|event| {
            event.kind == PluginEventKind::Callback(PluginAction::Stop)
                && event.outcome == PluginOutcome::Success
        }));
    }
    Ok(())
}

#[test]
fn selective_stop_preserves_diamond_and_transitive_safety_without_cascade() -> TestResult {
    let log = Log::default();
    let a = PluginId::new("a")?;
    let b = PluginId::new("b")?;
    let c = PluginId::new("c")?;
    let d = PluginId::new("d")?;
    let z = PluginId::new("z")?;
    let mut manager = PluginManager::new(vec![
        registration("z", &[], &log, Behavior::default())?,
        registration("d", &["c", "b"], &log, Behavior::default())?,
        registration("c", &["a"], &log, Behavior::default())?,
        registration("b", &["a"], &log, Behavior::default())?,
        registration("a", &[], &log, Behavior::default())?,
    ])?;
    manager.start_all(&mut allow)?;
    manager.drain_events().for_each(drop);
    log.borrow_mut().clear();
    for (target, blocker) in [(&a, &b), (&b, &d), (&c, &d)] {
        assert_eq!(
            manager.stop(target),
            Err(PluginError::DependencyInUse(blocker.clone()))
        );
    }
    assert!(log.borrow().is_empty());
    assert_eq!(manager.drain_events().count(), 0);
    let untouched = [&a, &b, &c, &z].map(|id| manager.status(id).expect("status").clone());
    manager.stop(&d)?;
    for (id, status) in [&a, &b, &c, &z].into_iter().zip(&untouched) {
        assert_eq!(manager.status(id), Some(status));
    }
    manager.stop(&b)?;
    assert_eq!(
        manager.stop(&a),
        Err(PluginError::DependencyInUse(c.clone()))
    );
    manager.stop(&c)?;
    manager.stop(&a)?;
    assert_eq!(*log.borrow(), ["d:Stop", "b:Stop", "c:Stop", "a:Stop"]);
    let events = manager.drain_events().collect::<Vec<_>>();
    assert_eq!(
        events.iter().map(|event| &event.id).collect::<Vec<_>>(),
        [&d, &b, &c, &a]
    );
    assert!(
        events
            .windows(2)
            .all(|pair| pair[0].sequence + 1 == pair[1].sequence)
    );
    for id in [&a, &b, &c, &d] {
        manager.stop(id)?;
    }
    assert_eq!(manager.drain_events().count(), 0);
    assert_eq!(*log.borrow(), ["d:Stop", "b:Stop", "c:Stop", "a:Stop"]);
    assert_eq!(manager.status(&z), Some(&untouched[3]));
    manager.stop_all()?;
    assert_eq!(manager.drain_events().count(), 1);
    assert_eq!(log.borrow().last().expect("stop"), "z:Stop");
    Ok(())
}

#[test]
fn selective_stop_retries_errors_and_panics_preserving_first_failure_and_latest_cleanup()
-> TestResult {
    for health_failed in [false, true] {
        let log = Log::default();
        let cleanup = Rc::new(RefCell::new(PluginOutcome::Success));
        let health = Rc::new(RefCell::new(PluginOutcome::Success));
        let a = PluginId::new("a")?;
        let mut manager = PluginManager::new(vec![registration(
            "a",
            &[],
            &log,
            Behavior {
                health: Some(health.clone()),
                cleanup: Some(cleanup.clone()),
                ..Behavior::default()
            },
        )?])?;
        manager.start_all(&mut allow)?;
        if health_failed {
            *health.borrow_mut() = PluginOutcome::Error;
            assert!(manager.check_health(&a, &mut allow).is_err());
        }
        let mut first = manager.status(&a).expect("status").failure.clone();
        manager.drain_events().for_each(drop);
        log.borrow_mut().clear();
        for outcome in [
            PluginOutcome::Error,
            PluginOutcome::Panicked,
            PluginOutcome::Error,
        ] {
            *cleanup.borrow_mut() = outcome;
            let previous = manager.status(&a).expect("status").clone();
            let Err(PluginError::Callback(id, failure)) = manager.stop(&a) else {
                panic!("cleanup must fail");
            };
            assert_eq!(id, a);
            assert_eq!(failure.action, PluginAction::Stop);
            assert_eq!(failure.panicked, outcome == PluginOutcome::Panicked);
            first.get_or_insert_with(|| failure.clone());
            let status = manager.status(&a).expect("status").clone();
            assert_eq!(status.state, PluginState::Failed);
            assert!(status.cleanup_pending);
            assert_eq!(status.failure, first);
            assert_eq!(status.cleanup_error, Some(failure));
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(events.len(), 1);
            assert_eq!(
                events[0].kind,
                PluginEventKind::Callback(PluginAction::Stop)
            );
            assert_eq!(events[0].outcome, outcome);
            assert_eq!(events[0].previous, (&previous).into());
            assert_eq!(events[0].current, (&status).into());
            assert!(!format!("{events:?}").contains("private-cleanup-secret"));
        }
        *cleanup.borrow_mut() = PluginOutcome::Success;
        manager.stop(&a)?;
        let cleaned = manager.status(&a).expect("status").clone();
        assert_eq!(cleaned.state, PluginState::Failed);
        assert_eq!(cleaned.health, PluginHealth::Unhealthy);
        assert_eq!(cleaned.failure, first);
        assert!(!cleaned.cleanup_pending);
        assert!(cleaned.cleanup_error.is_none());
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].outcome, PluginOutcome::Success);
        assert!(events[0].previous.cleanup_failed);
        assert!(!events[0].current.cleanup_failed);
        assert!(!events[0].current.cleanup_pending);
        assert_eq!(*log.borrow(), ["a:Stop"; 4]);
        manager.stop(&a)?;
        manager.stop_all()?;
        assert_eq!(manager.status(&a), Some(&cleaned));
        assert_eq!(manager.drain_events().count(), 0);
        assert_eq!(*log.borrow(), ["a:Stop"; 4]);
    }
    Ok(())
}

#[test]
fn selective_stop_after_revocation_never_requests_new_host_authority() -> TestResult {
    let log = Log::default();
    let a = PluginId::new("a")?;
    let mut manager = PluginManager::new(vec![registration("a", &[], &log, Behavior::default())?])?;
    let mut authorized = true;
    let mut auth_calls = 0;
    let mut authorizer = |_: &PluginDescriptor, _: PluginAction| {
        auth_calls += 1;
        plan(if authorized {
            AuthorityState::Authorized
        } else {
            AuthorityState::Revoked
        })
    };
    manager.start_all(&mut authorizer)?;
    assert_eq!(auth_calls, 3);
    authorized = false;
    let mut revoked = |_: &PluginDescriptor, _: PluginAction| {
        auth_calls += 1;
        assert!(!authorized);
        plan(AuthorityState::Revoked)
    };
    assert!(matches!(
        manager.check_health(&a, &mut revoked),
        Err(PluginError::Authorization(..))
    ));
    manager.drain_events().for_each(drop);
    log.borrow_mut().clear();
    manager.stop(&a)?;
    assert_eq!(auth_calls, 4);
    assert_eq!(*log.borrow(), ["a:Stop"]);
    assert_eq!(
        manager.status(&a).expect("status").state,
        PluginState::Stopped
    );
    assert_eq!(manager.drain_events().count(), 1);
    Ok(())
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
                manager.stop(&b)?;
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
            assert_eq!(
                manager.check_health_all(&mut forbidden),
                Err(PluginError::InvalidTransition(b.clone(), state))
            );
            let fleet_before = [manager.status(&a).cloned(), manager.status(&b).cloned()];
            let loss = manager.lost_events();
            let mut auth_calls = 0;
            let mut counted = |descriptor: &PluginDescriptor, action: PluginAction| {
                auth_calls += 1;
                allow(descriptor, action)
            };
            assert_eq!(
                manager.check_health_report(&mut counted),
                Err(PluginError::InvalidTransition(b.clone(), state))
            );
            assert_eq!(auth_calls, 0);
            assert_eq!(manager.lost_events(), loss);
            assert_eq!(
                [manager.status(&a).cloned(), manager.status(&b).cloned()],
                fleet_before
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
fn health_reports_are_fresh_topological_complete_and_independent_of_event_loss() -> TestResult {
    let mut empty = PluginManager::new(vec![])?;
    let mut auth_calls = 0;
    let mut counted = |descriptor: &PluginDescriptor, action: PluginAction| {
        auth_calls += 1;
        allow(descriptor, action)
    };
    let report = empty.check_health_report(&mut counted)?;
    assert!(report.complete() && report.all_ready());
    assert!(report.entries().is_empty());
    assert_eq!(auth_calls, 0);
    assert_eq!(empty.drain_events().count(), 0);
    for names in [
        ["a", "p", "z"],
        ["a", "z", "p"],
        ["p", "a", "z"],
        ["p", "z", "a"],
        ["z", "a", "p"],
        ["z", "p", "a"],
    ] {
        for capacity in [0, 256] {
            let log = Log::default();
            let health = Rc::new(RefCell::new(PluginOutcome::Success));
            let registrations = names
                .iter()
                .map(|name| {
                    registration(
                        name,
                        if *name == "a" { &["z"] } else { &[] },
                        &log,
                        Behavior {
                            health: (*name == "z").then(|| health.clone()),
                            ..Behavior::default()
                        },
                    )
                })
                .collect::<Result<Vec<_>, _>>()?;
            let mut manager = PluginManager::with_event_capacity(registrations, capacity)?;
            manager.start_all(&mut allow)?;
            let mut retained = None;
            for (outcome, expected) in [
                (PluginOutcome::Success, HealthOutcome::Ready),
                (PluginOutcome::NotReady, HealthOutcome::NotReady),
                (PluginOutcome::Success, HealthOutcome::Ready),
            ] {
                *health.borrow_mut() = outcome;
                manager.drain_events().for_each(drop);
                log.borrow_mut().clear();
                let loss = manager.lost_events();
                let mut authorized = Vec::new();
                let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
                    authorized.push((descriptor.id.as_str().to_owned(), action));
                    allow(descriptor, action)
                };
                let report = manager.check_health_report(&mut auth)?;
                assert!(report.complete());
                assert_eq!(report.all_ready(), expected == HealthOutcome::Ready);
                assert_eq!(
                    report
                        .entries()
                        .iter()
                        .map(|e| e.id.as_str())
                        .collect::<Vec<_>>(),
                    ["p", "z", "a"]
                );
                assert_eq!(
                    report
                        .entries()
                        .iter()
                        .map(|e| e.outcome)
                        .collect::<Vec<_>>(),
                    [HealthOutcome::Ready, expected, HealthOutcome::Ready]
                );
                assert_eq!(
                    authorized,
                    ["p", "z", "a"].map(|id| (id.to_owned(), PluginAction::Readiness))
                );
                assert_eq!(*log.borrow(), ["p:Readiness", "z:Readiness", "a:Readiness"]);
                for entry in report.entries() {
                    assert_eq!(
                        entry.current,
                        manager.status(&entry.id).expect("status").into()
                    );
                    assert_eq!(entry.current.state, PluginState::Running);
                    assert!(entry.current.cleanup_pending);
                    assert!(!entry.current.failed);
                }
                if expected == HealthOutcome::NotReady {
                    assert_eq!(report.entries()[1].previous.health, PluginHealth::Ready);
                    retained = Some(report.clone());
                } else if let Some(old) = &retained {
                    assert_eq!(old.entries()[1].current.health, PluginHealth::NotReady);
                    assert_eq!(report.entries()[1].previous.health, PluginHealth::NotReady);
                }
                assert_eq!(
                    manager.drain_events().count(),
                    if capacity == 0 { 0 } else { 3 }
                );
                assert_eq!(
                    manager.lost_events() - loss,
                    if capacity == 0 { 3 } else { 0 }
                );
            }
            manager.pause(&PluginId::new("p")?, &mut allow)?;
            manager.drain_events().for_each(drop);
            log.borrow_mut().clear();
            let report = manager.check_health_report(&mut allow)?;
            assert!(report.complete() && !report.all_ready());
            assert_eq!(report.entries()[0].outcome, HealthOutcome::SkippedPaused);
            assert_eq!(report.entries()[0].previous, report.entries()[0].current);
            assert_eq!(*log.borrow(), ["z:Readiness", "a:Readiness"]);
            assert_eq!(
                manager.drain_events().count(),
                if capacity == 0 { 0 } else { 2 }
            );
            manager.pause_all(&mut allow)?;
            manager.drain_events().for_each(drop);
            log.borrow_mut().clear();
            let loss = manager.lost_events();
            let mut calls = 0;
            let mut counted = |descriptor: &PluginDescriptor, action: PluginAction| {
                calls += 1;
                allow(descriptor, action)
            };
            let report = manager.check_health_report(&mut counted)?;
            assert!(report.complete() && !report.all_ready());
            assert!(
                report
                    .entries()
                    .iter()
                    .all(|e| e.outcome == HealthOutcome::SkippedPaused)
            );
            assert_eq!(calls, 0);
            assert!(log.borrow().is_empty());
            assert_eq!(manager.drain_events().count(), 0);
            assert_eq!(manager.lost_events(), loss);
            manager.stop_all()?;
        }
    }
    Ok(())
}

#[test]
fn health_reports_retain_partial_results_rejections_failures_and_unattempted_nodes() -> TestResult {
    for mode in ["deny", "hold", "revoked", "auth-panic", "error", "panic"] {
        for prior in [PluginOutcome::Success, PluginOutcome::NotReady] {
            for capacity in [0, 256] {
                let log = Log::default();
                let a_health = Rc::new(RefCell::new(PluginOutcome::Success));
                let b_health = Rc::new(RefCell::new(PluginOutcome::Success));
                let mut manager = PluginManager::with_event_capacity(
                    vec![
                        registration("d", &[], &log, Behavior::default())?,
                        registration("c", &["b"], &log, Behavior::default())?,
                        registration(
                            "b",
                            &["a"],
                            &log,
                            Behavior {
                                health: Some(b_health.clone()),
                                cleanup_failures: usize::from(matches!(mode, "error" | "panic")),
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
                    ],
                    capacity,
                )?;
                let b = PluginId::new("b")?;
                manager.start_all(&mut allow)?;
                manager.pause(&PluginId::new("d")?, &mut allow)?;
                *b_health.borrow_mut() = prior;
                manager.check_health(&b, &mut allow)?;
                let before = manager.status(&b).expect("status").clone();
                *a_health.borrow_mut() = PluginOutcome::NotReady;
                *b_health.borrow_mut() = match mode {
                    "error" => PluginOutcome::Error,
                    "panic" => PluginOutcome::Panicked,
                    _ => prior,
                };
                manager.drain_events().for_each(drop);
                log.borrow_mut().clear();
                let loss = manager.lost_events();
                let mut authorized = Vec::new();
                let mut auth = |descriptor: &PluginDescriptor, action: PluginAction| {
                    authorized.push(descriptor.id.as_str().to_owned());
                    assert_eq!(action, PluginAction::Readiness);
                    if descriptor.id == b {
                        match mode {
                            "deny" => return Err("private-auth-secret".into()),
                            "hold" => return plan(AuthorityState::InDoubt),
                            "revoked" => return plan(AuthorityState::Revoked),
                            "auth-panic" => panic!("private-auth-secret"),
                            _ => {}
                        }
                    }
                    allow(descriptor, action)
                };
                let report = manager.check_health_report(&mut auth)?;
                let failed = matches!(mode, "error" | "panic");
                let expected = match mode {
                    "error" => HealthOutcome::Error,
                    "panic" => HealthOutcome::Panicked,
                    _ => HealthOutcome::Rejected,
                };
                assert!(!report.complete() && !report.all_ready());
                assert_eq!(authorized, ["a", "b"]);
                assert_eq!(
                    report
                        .entries()
                        .iter()
                        .map(|e| (e.id.as_str(), e.outcome))
                        .collect::<Vec<_>>(),
                    [
                        ("a", HealthOutcome::NotReady),
                        ("b", expected),
                        ("c", HealthOutcome::NotAttempted),
                        ("d", HealthOutcome::SkippedPaused)
                    ]
                );
                assert_eq!(
                    *log.borrow(),
                    if failed {
                        vec!["a:Readiness", "b:Readiness"]
                    } else {
                        vec!["a:Readiness"]
                    }
                );
                assert_eq!(report.entries()[1].previous, (&before).into());
                for entry in &report.entries()[2..] {
                    assert_eq!(entry.previous, entry.current);
                }
                assert_eq!(report.entries()[2].current.health, PluginHealth::Ready);
                let status = manager.status(&b).expect("status").clone();
                assert_eq!(report.entries()[1].current, (&status).into());
                assert_eq!(
                    status.state,
                    if failed {
                        PluginState::Failed
                    } else {
                        PluginState::Running
                    }
                );
                assert!(status.cleanup_pending);
                if !failed {
                    assert_eq!(status, before);
                }
                let rendered = format!("{report:?}");
                for secret in [
                    "private-auth-secret",
                    "private-health-secret",
                    "plugin-evidence",
                    "host-evidence",
                ] {
                    assert!(!rendered.contains(secret));
                }
                let events = manager.drain_events().collect::<Vec<_>>();
                assert_eq!(events.len(), if capacity == 0 { 0 } else { 2 });
                assert_eq!(
                    manager.lost_events() - loss,
                    if capacity == 0 { 2 } else { 0 }
                );
                if capacity != 0 {
                    assert_eq!(events[0].outcome, PluginOutcome::NotReady);
                    assert_eq!(
                        events[1].outcome,
                        match mode {
                            "error" => PluginOutcome::Error,
                            "panic" => PluginOutcome::Panicked,
                            _ => PluginOutcome::Rejected,
                        }
                    );
                }
                if failed {
                    assert_eq!(status.health, PluginHealth::Unhealthy);
                    assert_eq!(
                        status.failure.as_ref().expect("failure").panicked,
                        mode == "panic"
                    );
                    assert!(manager.stop_all().is_err());
                    assert_eq!(manager.status(&b).expect("status").failure, status.failure);
                    assert!(manager.status(&b).expect("status").cleanup_error.is_some());
                    manager.stop_all()?;
                    assert_eq!(manager.status(&b).expect("status").failure, status.failure);
                    assert!(!manager.status(&b).expect("status").cleanup_pending);
                } else {
                    let recovered = manager.check_health_report(&mut allow)?;
                    assert!(recovered.complete() && !recovered.all_ready());
                    manager.stop_all()?;
                }
            }
        }
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
