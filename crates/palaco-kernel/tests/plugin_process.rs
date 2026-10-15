#![cfg(feature = "plugin-process-tests")]

use std::{
    cell::Cell,
    error::Error,
    path::PathBuf,
    rc::Rc,
    time::{Duration, Instant},
};

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, HealthOutcome, Plugin, PluginAction, PluginContext, PluginDescriptor,
        PluginError, PluginEventKind, PluginHealth, PluginId, PluginManager, PluginOutcome,
        PluginRegistration, PluginState, ShutdownOutcome, ShutdownScope, StartupDisposition,
        process::{ProcessPlugin, ProcessPluginConfig},
    },
};

type TestResult = Result<(), Box<dyn Error>>;
const TIMEOUT: Duration = Duration::from_millis(500);

struct TrackedProcess {
    plugin: ProcessPlugin,
    pid: Rc<Cell<Option<u32>>>,
    calls: Rc<Cell<usize>>,
}

impl Plugin for TrackedProcess {
    fn initialize(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.calls.set(self.calls.get() + 1);
        self.plugin.initialize(context)?;
        self.pid.set(self.plugin.child_id());
        Ok(())
    }

    fn start(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.calls.set(self.calls.get() + 1);
        self.plugin.start(context)
    }

    fn readiness(&mut self, context: &PluginContext<'_>) -> Result<bool, String> {
        self.calls.set(self.calls.get() + 1);
        self.plugin.readiness(context)
    }

    fn stop(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.calls.set(self.calls.get() + 1);
        self.plugin.stop(context)
    }
}

fn process(mode: &str) -> Result<ProcessPlugin, String> {
    ProcessPlugin::new(ProcessPluginConfig {
        executable: PathBuf::from(env!("CARGO_BIN_EXE_plugin-process-fixture")),
        args: vec![mode.into()],
        timeout: TIMEOUT,
    })
}

fn descriptor() -> Result<PluginDescriptor, Box<dyn Error>> {
    Ok(PluginDescriptor {
        id: PluginId::new("child")?,
        evidence: EvidenceRef::new("child-evidence")?,
        contract_version: CONTRACT_VERSION,
        dependencies: vec![],
    })
}

fn context(descriptor: &PluginDescriptor) -> PluginContext<'_> {
    PluginContext {
        id: &descriptor.id,
        evidence: &descriptor.evidence,
    }
}

fn allow(_: &PluginDescriptor, _: PluginAction) -> Result<RuntimePlan, String> {
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(
            EventEnvelope::new(
                "plugin.process",
                EvidenceRef::new("host-evidence").map_err(|error| error.to_string())?,
            ),
            AuthorityState::Authorized,
        ),
    )))
}

fn assert_reaped(pid: u32) {
    // The core protocol tests are portable; Linux also verifies OS-level reaping
    // rather than merely observing that the adapter released its Child handle.
    #[cfg(target_os = "linux")]
    assert!(
        !PathBuf::from(format!("/proc/{pid}")).exists(),
        "child still exists: {pid}"
    );
    #[cfg(not(target_os = "linux"))]
    let _ = pid;
}

#[test]
fn scoped_process_start_spawns_only_required_children_and_rolls_back_only_new_children()
-> TestResult {
    for mode in ["healthy", "start-error", "not-ready", "readiness-error"] {
        let ids = ["existing", "held", "new", "root", "other"]
            .map(|name| PluginId::new(name).expect("ID"));
        let [existing, held, new, root, other] = &ids;
        let pids = [(); 5].map(|()| Rc::new(Cell::new(None)));
        let calls = [(); 5].map(|()| Rc::new(Cell::new(0)));
        let mut registrations = Vec::new();
        for (index, (id, dependencies, mode)) in [
            (existing, vec![], "probe-hang"),
            (held, vec![existing.clone()], "healthy"),
            (new, vec![existing.clone()], "healthy"),
            (root, vec![new.clone()], mode),
            (other, vec![], "healthy"),
        ]
        .into_iter()
        .enumerate()
        {
            registrations.push(PluginRegistration {
                descriptor: PluginDescriptor {
                    id: id.clone(),
                    dependencies,
                    ..descriptor()?
                },
                plugin: Box::new(TrackedProcess {
                    plugin: process(mode)?,
                    pid: pids[index].clone(),
                    calls: calls[index].clone(),
                }),
            });
        }
        registrations.reverse();
        let mut manager = PluginManager::new(registrations)?;
        assert!(pids.iter().all(|pid| pid.get().is_none()));
        assert!(calls.iter().all(|count| count.get() == 0));
        assert!(matches!(
            manager.start_with_dependencies(&PluginId::new("missing")?, &mut allow),
            Err(PluginError::UnknownPlugin(_))
        ));
        assert!(calls.iter().all(|count| count.get() == 0));
        manager.start_with_dependencies(held, &mut allow)?;
        let existing_before = manager.status(existing).cloned();
        let held_before = manager.status(held).cloned();
        assert!(pids[0].get().is_some() && pids[1].get().is_some());
        assert!(pids[2..].iter().all(|pid| pid.get().is_none()));
        manager.drain_events().for_each(drop);
        let result = manager.start_with_dependencies(root, &mut allow);
        assert_eq!(manager.status(existing), existing_before.as_ref());
        assert_eq!(manager.status(held), held_before.as_ref());
        assert_eq!(calls[0].get(), 3);
        assert_eq!(calls[1].get(), 3);
        assert_eq!(calls[4].get(), 0);
        assert!(pids[4].get().is_none());
        assert_eq!(
            manager.status(other).expect("status").state,
            PluginState::Registered
        );
        let events: Vec<_> = manager.drain_events().collect();
        assert!(events.iter().all(|e| &e.id == new || &e.id == root));
        if mode == "healthy" {
            result?;
            assert_eq!(calls[2].get(), 3);
            assert_eq!(calls[3].get(), 3);
            manager.start_with_dependencies(root, &mut |_: &PluginDescriptor, _| {
                panic!("already running children must be skipped")
            })?;
            assert_eq!(calls[0].get(), 3);
            assert_eq!(calls[2].get(), 3);
            assert_eq!(calls[3].get(), 3);
            assert_eq!(manager.drain_events().count(), 0);
        } else {
            let Err(PluginError::Callback(id, failure)) = result else {
                panic!("expected scoped startup callback failure");
            };
            assert_eq!(&id, root);
            assert_eq!(
                failure.action,
                if mode == "start-error" {
                    PluginAction::Start
                } else {
                    PluginAction::Readiness
                }
            );
            assert_reaped(pids[2].get().expect("new child spawned"));
            assert_reaped(pids[3].get().expect("root child spawned"));
            assert_eq!(calls[2].get(), 4);
            assert!(!manager.status(root).expect("status").cleanup_pending);
            assert!(!manager.status(new).expect("status").cleanup_pending);
            #[cfg(target_os = "linux")]
            for pid in &pids[..2] {
                assert!(PathBuf::from(format!("/proc/{}", pid.get().expect("child PID"))).exists());
            }
        }
        manager.stop_all()?;
        for pid in &pids[..4] {
            assert_reaped(pid.get().expect("selected child spawned"));
        }
        assert_eq!(calls[0].get(), 4);
        assert_eq!(calls[1].get(), 4);
        assert_eq!(calls[4].get(), 0);
    }
    Ok(())
}

#[test]
fn inventory_and_previews_never_spawn_or_call_a_running_process() -> TestResult {
    let descriptor = descriptor()?;
    let id = descriptor.id.clone();
    let pid = Rc::new(Cell::new(None));
    let calls = Rc::new(Cell::new(0));
    let mut manager = PluginManager::new(vec![PluginRegistration {
        descriptor,
        plugin: Box::new(TrackedProcess {
            // An unexpected readiness probe after startup would time out.
            plugin: process("probe-hang")?,
            pid: pid.clone(),
            calls: calls.clone(),
        }),
    }])?;
    for running in [false, true] {
        if running {
            manager.start_all(&mut allow)?;
        }
        let before_calls = calls.get();
        let before_status = manager.status(&id).cloned();
        for _ in 0..3 {
            let inventory = manager.inventory();
            assert_eq!(manager.inventory(), inventory);
            assert_eq!(inventory.entries().len(), 1);
            assert_eq!(inventory.entries()[0].id, id);
            assert_eq!(
                inventory.entries()[0].snapshot.state,
                if running {
                    PluginState::Running
                } else {
                    PluginState::Registered
                }
            );
            assert_eq!(inventory.entries()[0].snapshot.cleanup_pending, running);
            let startup = manager.plan_startup(&id)?;
            assert!(startup.can_start());
            assert_eq!(startup.steps().len(), 1);
            assert_eq!(
                startup.steps()[0].disposition,
                if running {
                    StartupDisposition::AlreadyRunning
                } else {
                    StartupDisposition::Start
                }
            );
            assert_eq!(
                manager.plan_startup(&PluginId::new("missing")?),
                Err(PluginError::UnknownPlugin(PluginId::new("missing")?))
            );
            for scope in [
                ShutdownScope::Single(id.clone()),
                ShutdownScope::WithDependents(id.clone()),
                ShutdownScope::All,
            ] {
                let preview = manager.plan_shutdown(scope)?;
                assert_eq!(preview.len(), 1);
                assert_eq!(preview[0].snapshot.cleanup_pending, running);
                assert_eq!(
                    preview[0].snapshot.state,
                    if running {
                        PluginState::Running
                    } else {
                        PluginState::Registered
                    }
                );
                assert!(preview[0].blockers.is_empty());
            }
        }
        assert_eq!(calls.get(), before_calls);
        assert_eq!(manager.status(&id), before_status.as_ref());
        assert_eq!(pid.get().is_some(), running);
    }
    let pid = pid.get().expect("spawned child");
    manager.stop_all()?;
    assert_eq!(calls.get(), 4);
    assert_reaped(pid);
    Ok(())
}

#[test]
fn inventory_and_startup_preview_accept_unspawnable_configuration_without_executing_it()
-> TestResult {
    // A path below the fixture executable cannot be an executable itself.
    let executable = PathBuf::from(env!("CARGO_BIN_EXE_plugin-process-fixture")).join("missing");
    assert!(executable.is_absolute() && !executable.exists());
    let descriptor = descriptor()?;
    let id = descriptor.id.clone();
    let calls = Rc::new(Cell::new(0));
    let pid = Rc::new(Cell::new(None));
    let mut manager = PluginManager::new(vec![PluginRegistration {
        descriptor,
        plugin: Box::new(TrackedProcess {
            plugin: ProcessPlugin::new(ProcessPluginConfig {
                executable,
                args: vec![],
                timeout: TIMEOUT,
            })?,
            calls: calls.clone(),
            pid: pid.clone(),
        }),
    }])?;
    let initial = manager.inventory();
    assert_eq!(manager.inventory(), initial);
    assert_eq!(initial.entries()[0].snapshot.state, PluginState::Registered);
    let rendered = format!("{initial:?}");
    assert!(!rendered.contains("plugin-process-fixture"));
    assert!(!rendered.contains("child-evidence"));
    assert!(manager.plan_startup(&id)?.can_start());
    assert_eq!(
        manager.plan_startup(&PluginId::new("missing")?),
        Err(PluginError::UnknownPlugin(PluginId::new("missing")?))
    );
    assert_eq!(calls.get(), 0);
    assert!(pid.get().is_none());
    assert_eq!(
        manager.status(&id).expect("status").state,
        PluginState::Registered
    );
    assert!(matches!(
        manager.start_with_dependencies(&id, &mut allow),
        Err(PluginError::Callback(_, failure)) if failure.action == PluginAction::Initialize
    ));
    assert_eq!(calls.get(), 2); // Failed initialize and scoped rollback cleanup.
    assert!(pid.get().is_none());
    let failed = manager.plan_startup(&id)?;
    assert!(!failed.can_start());
    assert_eq!(
        failed.steps()[0].disposition,
        StartupDisposition::InvalidState
    );
    assert!(failed.steps()[0].snapshot.failed);
    manager.stop_all()?;
    Ok(())
}

#[test]
fn process_shutdown_reports_cleanup_retry_and_scoped_child_retention() -> TestResult {
    for mode in ["healthy", "stop-error", "stop-hang"] {
        let ids = ["service", "worker", "independent"].map(|name| PluginId::new(name).expect("ID"));
        let [service, worker, independent] = &ids;
        let pids = [(); 3].map(|()| Rc::new(Cell::new(None)));
        let mut registrations = Vec::new();
        for (index, (id, dependencies, mode)) in [
            (service, vec![], "healthy"),
            (worker, vec![service.clone()], mode),
            (independent, vec![], "healthy"),
        ]
        .into_iter()
        .enumerate()
        {
            registrations.push(PluginRegistration {
                descriptor: PluginDescriptor {
                    id: id.clone(),
                    dependencies,
                    ..descriptor()?
                },
                plugin: Box::new(TrackedProcess {
                    plugin: process(mode)?,
                    pid: pids[index].clone(),
                    calls: Rc::default(),
                }),
            });
        }
        let mut manager = PluginManager::new(registrations)?;
        manager.start_all(&mut allow)?;
        let pids = pids.map(|pid| pid.get().expect("spawned child"));
        let independent_before = manager.status(independent).cloned();
        manager.drain_events().for_each(drop);
        let began = Instant::now();
        let report = manager.execute_shutdown(ShutdownScope::WithDependents(service.clone()))?;
        assert!(began.elapsed() < Duration::from_secs(3), "{mode}");
        assert_eq!(
            report.entries().iter().map(|e| &e.id).collect::<Vec<_>>(),
            [worker, service]
        );
        assert_reaped(pids[1]);
        if mode == "healthy" {
            assert!(report.complete());
            assert!(
                report
                    .entries()
                    .iter()
                    .all(|e| e.outcome == ShutdownOutcome::Stopped && e.blockers.is_empty())
            );
            assert_eq!(manager.drain_events().count(), 2);
        } else {
            assert!(!report.complete());
            assert_eq!(report.entries()[0].outcome, ShutdownOutcome::Error);
            assert_eq!(report.entries()[1].outcome, ShutdownOutcome::Blocked);
            assert_eq!(report.entries()[1].blockers, std::slice::from_ref(worker));
            assert_eq!(manager.drain_events().count(), 1);
            let first = manager.status(worker).expect("status").failure.clone();
            let retry = manager.execute_shutdown(ShutdownScope::WithDependents(service.clone()))?;
            assert!(retry.complete());
            assert!(
                retry
                    .entries()
                    .iter()
                    .all(|e| e.outcome == ShutdownOutcome::Stopped && e.blockers.is_empty())
            );
            let status = manager.status(worker).expect("status");
            assert_eq!(status.failure, first);
            assert_eq!(status.state, PluginState::Failed);
            assert!(status.cleanup_error.is_none());
        }
        assert_reaped(pids[0]);
        assert_eq!(manager.status(independent), independent_before.as_ref());
        let inventory = manager.inventory();
        assert_eq!(manager.inventory(), inventory);
        assert_eq!(inventory.entries().len(), 3);
        for entry in inventory.entries() {
            assert_eq!(entry.snapshot.cleanup_pending, &entry.id == independent);
            assert_eq!(
                entry.snapshot.state,
                if &entry.id == independent {
                    PluginState::Running
                } else if &entry.id == worker && mode != "healthy" {
                    PluginState::Failed
                } else {
                    PluginState::Stopped
                }
            );
        }
        assert_eq!(
            manager.check_health(independent, &mut allow)?,
            PluginHealth::Ready
        );
        let final_report = manager.execute_shutdown(ShutdownScope::All)?;
        assert!(final_report.complete());
        assert_eq!(
            final_report
                .entries()
                .iter()
                .filter(|e| e.outcome == ShutdownOutcome::Stopped)
                .count(),
            1
        );
        assert_reaped(pids[2]);
        assert!(
            manager
                .inventory()
                .entries()
                .iter()
                .all(|entry| !entry.snapshot.cleanup_pending)
        );
    }
    Ok(())
}

#[test]
fn scoped_process_shutdown_reaps_descendants_and_retains_unrelated_child() -> TestResult {
    for mode in ["healthy", "stop-error", "stop-hang", "probe-error"] {
        let ids = ["service", "worker", "leaf", "independent"]
            .map(|name| PluginId::new(name).expect("valid ID"));
        let [service, worker, leaf, independent] = &ids;
        let pids = [(); 4].map(|()| Rc::new(Cell::new(None)));
        let mut registrations = Vec::new();
        for (index, (id, dependencies, mode)) in [
            (service, vec![], "healthy"),
            (worker, vec![service.clone()], "healthy"),
            (leaf, vec![worker.clone()], mode),
            (independent, vec![], "healthy"),
        ]
        .into_iter()
        .enumerate()
        {
            registrations.push(PluginRegistration {
                descriptor: PluginDescriptor {
                    id: id.clone(),
                    dependencies,
                    ..descriptor()?
                },
                plugin: Box::new(TrackedProcess {
                    plugin: process(mode)?,
                    pid: pids[index].clone(),
                    calls: Rc::default(),
                }),
            });
        }
        let mut manager = PluginManager::new(registrations)?;
        manager.start_all(&mut allow)?;
        let pids = pids.map(|pid| pid.get().expect("spawned child"));
        let retained =
            [service, worker, independent].map(|id| manager.status(id).expect("status").clone());
        if mode == "probe-error" {
            assert!(matches!(
                manager.check_health(leaf, &mut allow),
                Err(PluginError::Callback(..))
            ));
            assert_reaped(pids[2]);
        }
        manager.drain_events().for_each(drop);
        let began = Instant::now();
        let result = manager.stop_with_dependents(service);
        assert!(began.elapsed() < Duration::from_secs(3), "{mode}");
        assert_reaped(pids[2]);
        if matches!(mode, "stop-error" | "stop-hang") {
            assert!(matches!(result, Err(PluginError::Callback(id, _)) if &id == leaf));
            assert_eq!(manager.drain_events().count(), 1);
            for (id, status) in [service, worker, independent].into_iter().zip(&retained) {
                assert_eq!(manager.status(id), Some(status));
                assert_eq!(manager.check_health(id, &mut allow)?, PluginHealth::Ready);
            }
            manager.drain_events().for_each(drop);
            manager.stop_with_dependents(service)?;
        } else {
            result?;
        }
        assert_reaped(pids[0]);
        assert_reaped(pids[1]);
        assert_eq!(manager.status(independent), Some(&retained[2]));
        assert_eq!(
            manager.check_health(independent, &mut allow)?,
            PluginHealth::Ready
        );
        assert!(
            ids[..3]
                .iter()
                .all(|id| !manager.status(id).expect("status").cleanup_pending)
        );
        manager.drain_events().for_each(drop);
        let before = ids.each_ref().map(|id| manager.status(id).cloned());
        manager.stop_with_dependents(service)?;
        assert_eq!(ids.each_ref().map(|id| manager.status(id).cloned()), before);
        assert_eq!(manager.drain_events().count(), 0);
        manager.stop_all()?;
        assert_reaped(pids[3]);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 1);
        assert_eq!(&events[0].id, independent);
    }
    Ok(())
}

#[test]
fn selective_process_stop_reaps_only_target_and_retains_dependency_until_cleanup() -> TestResult {
    for mode in ["healthy", "stop-error", "stop-hang", "probe-error"] {
        let service = PluginId::new("service")?;
        let worker = PluginId::new("worker")?;
        let independent = PluginId::new("independent")?;
        let pids = [(); 3].map(|()| Rc::new(Cell::new(None)));
        let mut registrations = Vec::new();
        for (index, (id, dependencies, mode)) in [
            (&service, vec![], "healthy"),
            (&worker, vec![service.clone()], mode),
            (&independent, vec![], "healthy"),
        ]
        .into_iter()
        .enumerate()
        {
            registrations.push(PluginRegistration {
                descriptor: PluginDescriptor {
                    id: id.clone(),
                    dependencies,
                    ..descriptor()?
                },
                plugin: Box::new(TrackedProcess {
                    plugin: process(mode)?,
                    pid: pids[index].clone(),
                    calls: Rc::default(),
                }),
            });
        }
        let mut manager = PluginManager::new(registrations)?;
        manager.start_all(&mut allow)?;
        let [service_pid, worker_pid, independent_pid] =
            pids.map(|pid| pid.get().expect("spawned child"));
        let untouched =
            [&service, &independent].map(|id| manager.status(id).expect("status").clone());
        if mode == "probe-error" {
            assert!(matches!(
                manager.check_health(&worker, &mut allow),
                Err(PluginError::Callback(..))
            ));
            assert_reaped(worker_pid);
        }
        let failure = manager.status(&worker).expect("status").failure.clone();
        manager.drain_events().for_each(drop);
        let before = manager.status(&service).expect("status").clone();
        assert_eq!(
            manager.stop(&service),
            Err(PluginError::DependencyInUse(worker.clone()))
        );
        assert_eq!(manager.status(&service), Some(&before));
        assert_eq!(manager.drain_events().count(), 0);
        let began = Instant::now();
        let stopped = manager.stop(&worker);
        assert!(began.elapsed() < Duration::from_secs(3), "{mode}");
        assert_reaped(worker_pid);
        if matches!(mode, "stop-error" | "stop-hang") {
            assert!(matches!(stopped, Err(PluginError::Callback(..))));
            let failed = manager.status(&worker).expect("status").clone();
            assert!(failed.cleanup_pending);
            assert!(failed.cleanup_error.is_some());
            let events = manager.drain_events().collect::<Vec<_>>();
            assert_eq!(events.len(), 1);
            assert_eq!(events[0].id, worker);
            assert_eq!(events[0].outcome, PluginOutcome::Error);
            // Even a reaped process retains dependency ownership until explicit retry.
            assert_eq!(
                manager.stop(&service),
                Err(PluginError::DependencyInUse(worker.clone()))
            );
            assert_eq!(manager.status(&worker), Some(&failed));
            assert_eq!(manager.drain_events().count(), 0);
            manager.stop(&worker)?;
            assert_eq!(
                manager.status(&worker).expect("status").failure,
                failed.failure
            );
        } else {
            stopped?;
            assert_eq!(manager.status(&worker).expect("status").failure, failure);
        }
        let cleaned = manager.status(&worker).expect("status").clone();
        assert!(!cleaned.cleanup_pending);
        assert!(cleaned.cleanup_error.is_none());
        assert_eq!(
            cleaned.state,
            if mode == "healthy" {
                PluginState::Stopped
            } else {
                PluginState::Failed
            }
        );
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].id, worker);
        assert_eq!(
            events[0].kind,
            PluginEventKind::Callback(PluginAction::Stop)
        );
        assert_eq!(events[0].outcome, PluginOutcome::Success);
        manager.stop(&worker)?;
        assert_eq!(manager.status(&worker), Some(&cleaned));
        assert_eq!(manager.drain_events().count(), 0);
        for (id, status) in [&service, &independent].into_iter().zip(&untouched) {
            assert_eq!(manager.status(id), Some(status));
            // A fresh protocol round trip also proves these children remain live.
            assert_eq!(manager.check_health(id, &mut allow)?, PluginHealth::Ready);
        }
        manager.drain_events().for_each(drop);
        manager.stop(&service)?;
        assert_reaped(service_pid);
        assert_eq!(manager.status(&independent), Some(&untouched[1]));
        assert_eq!(manager.drain_events().count(), 1);
        manager.stop_all()?;
        assert_reaped(independent_pid);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].id, independent);
    }
    Ok(())
}

#[test]
fn fleet_health_reports_probe_processes_without_automatically_stopping_other_children() -> TestResult
{
    for mode in ["health-cycle", "probe-error", "probe-hang"] {
        let mut registrations = Vec::new();
        let mut tracked = Vec::new();
        for (name, fixture) in [("a", "healthy"), ("b", mode), ("c", "healthy")] {
            let mut descriptor = descriptor()?;
            descriptor.id = PluginId::new(name)?;
            let pid = Rc::new(Cell::new(None));
            let calls = Rc::new(Cell::new(0));
            registrations.push(PluginRegistration {
                descriptor,
                plugin: Box::new(TrackedProcess {
                    plugin: process(fixture)?,
                    pid: pid.clone(),
                    calls: calls.clone(),
                }),
            });
            tracked.push((PluginId::new(name)?, pid, calls));
        }
        let mut manager = PluginManager::new(registrations)?;
        manager.start_all(&mut allow)?;
        let report = manager.check_health_report(&mut allow)?;
        let recoverable = mode == "health-cycle";
        assert_eq!(report.complete(), recoverable);
        assert!(!report.all_ready());
        assert_eq!(
            report
                .entries()
                .iter()
                .map(|e| e.outcome)
                .collect::<Vec<_>>(),
            [
                HealthOutcome::Ready,
                if recoverable {
                    HealthOutcome::NotReady
                } else {
                    HealthOutcome::Error
                },
                if recoverable {
                    HealthOutcome::Ready
                } else {
                    HealthOutcome::NotAttempted
                }
            ]
        );
        assert_eq!(tracked[0].2.get(), 4);
        assert_eq!(tracked[1].2.get(), 4);
        assert_eq!(tracked[2].2.get(), if recoverable { 4 } else { 3 });
        for index in [0, 2] {
            let status = manager.status(&tracked[index].0).expect("status");
            assert_eq!(status.state, PluginState::Running);
            assert!(status.cleanup_pending);
            // A fresh successful command proves the report did not stop this child.
            assert_eq!(
                manager.check_health(&tracked[index].0, &mut allow)?,
                PluginHealth::Ready
            );
        }
        if recoverable {
            let recovery = manager.check_health_report(&mut allow)?;
            assert!(recovery.complete() && recovery.all_ready());
            assert_eq!(report.entries()[1].current.health, PluginHealth::NotReady);
        } else {
            assert_reaped(tracked[1].1.get().expect("spawned child"));
            assert_eq!(report.entries()[1].current.state, PluginState::Failed);
            assert_eq!(report.entries()[2].previous, report.entries()[2].current);
        }
        let failure = manager
            .status(&tracked[1].0)
            .expect("status")
            .failure
            .clone();
        manager.stop_all()?;
        for (id, pid, _) in &tracked {
            assert_reaped(pid.get().expect("spawned child"));
            assert!(!manager.status(id).expect("status").cleanup_pending);
        }
        assert_eq!(
            manager.status(&tracked[1].0).expect("status").failure,
            failure
        );
    }
    Ok(())
}

#[test]
fn ongoing_process_health_can_report_not_ready_and_recover_on_fresh_ready_commands() -> TestResult {
    for mode in ["healthy", "health-cycle"] {
        let descriptor = descriptor()?;
        let id = descriptor.id.clone();
        let mut manager = PluginManager::new(vec![PluginRegistration {
            descriptor,
            plugin: Box::new(process(mode)?),
        }])?;
        manager.start_all(&mut allow)?;
        manager.drain_events().for_each(drop);
        let before = manager.status(&id).expect("status").clone();
        let mut deny = |_: &PluginDescriptor, _: PluginAction| Err("private-secret-details".into());
        assert!(matches!(
            manager.check_health(&id, &mut deny),
            Err(PluginError::Authorization(..))
        ));
        assert_eq!(manager.status(&id), Some(&before));
        let first = if mode == "health-cycle" {
            PluginHealth::NotReady
        } else {
            PluginHealth::Ready
        };
        assert_eq!(manager.check_health(&id, &mut allow)?, first);
        assert_eq!(
            manager.status(&id).expect("status").state,
            PluginState::Running
        );
        assert!(manager.status(&id).expect("status").cleanup_pending);
        assert!(manager.status(&id).expect("status").failure.is_none());
        assert_eq!(
            manager.check_health_all(&mut allow)?,
            [(id.clone(), PluginHealth::Ready)]
        );
        assert_eq!(manager.check_health(&id, &mut allow)?, PluginHealth::Ready);
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 4);
        assert_eq!(events[0].outcome, PluginOutcome::Rejected);
        assert_eq!(
            events[1].outcome,
            if mode == "health-cycle" {
                PluginOutcome::NotReady
            } else {
                PluginOutcome::Success
            }
        );
        assert_eq!(events[2].previous.health, first);
        assert_eq!(events[2].current.health, PluginHealth::Ready);
        assert!(!format!("{events:?}").contains("private-secret-details"));
        manager.stop_all()?;
    }
    Ok(())
}

#[test]
fn ongoing_process_probe_error_dead_child_and_timeout_are_terminal_and_reaped() -> TestResult {
    for mode in ["probe-error", "exit-after-ready", "probe-hang"] {
        let descriptor = descriptor()?;
        let id = descriptor.id.clone();
        let pid = Rc::new(Cell::new(None));
        let mut manager = PluginManager::new(vec![PluginRegistration {
            descriptor,
            plugin: Box::new(TrackedProcess {
                plugin: process(mode)?,
                pid: pid.clone(),
                calls: Rc::default(),
            }),
        }])?;
        manager.start_all(&mut allow)?;
        let pid = pid.get().expect("spawned child");
        manager.drain_events().for_each(drop);
        let began = Instant::now();
        assert!(matches!(
            manager.check_health(&id, &mut allow),
            Err(PluginError::Callback(..))
        ));
        assert!(
            began.elapsed() < Duration::from_secs(3),
            "{mode} exceeded deadline"
        );
        assert_reaped(pid);
        let status = manager.status(&id).expect("status").clone();
        assert_eq!(status.state, PluginState::Failed);
        assert_eq!(status.health, PluginHealth::Unhealthy);
        assert!(status.cleanup_pending);
        assert_eq!(
            status.failure.as_ref().expect("failure").action,
            PluginAction::Readiness
        );
        let events = manager.drain_events().collect::<Vec<_>>();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].outcome, PluginOutcome::Error);
        assert_eq!(events[0].current.state, PluginState::Failed);
        assert!(!format!("{events:?}").contains("private-secret-details"));
        let mut forbidden =
            |_: &PluginDescriptor, _: PluginAction| -> Result<RuntimePlan, String> {
                panic!("terminal sessions cannot recover");
            };
        assert_eq!(
            manager.check_health(&id, &mut forbidden),
            Err(PluginError::InvalidTransition(
                id.clone(),
                PluginState::Failed
            ))
        );
        assert_eq!(manager.drain_events().count(), 0);
        manager.stop_all()?;
        assert_reaped(pid);
        let cleaned = manager.status(&id).expect("status");
        assert_eq!(cleaned.state, PluginState::Failed);
        assert_eq!(cleaned.failure, status.failure);
        assert!(!cleaned.cleanup_pending);
    }
    Ok(())
}

#[test]
fn process_configuration_is_explicit_and_bounded() {
    for (executable, timeout) in [
        (PathBuf::from("relative"), TIMEOUT),
        (
            PathBuf::from(env!("CARGO_BIN_EXE_plugin-process-fixture")),
            Duration::ZERO,
        ),
        (
            PathBuf::from(env!("CARGO_BIN_EXE_plugin-process-fixture")),
            Duration::from_secs(61),
        ),
    ] {
        assert!(
            ProcessPlugin::new(ProcessPluginConfig {
                executable,
                args: vec![],
                timeout
            })
            .is_err()
        );
    }
}

#[test]
fn healthy_process_has_full_lifecycle_cleared_env_and_reaped_shutdown() -> TestResult {
    for mode in ["healthy", "stderr"] {
        let mut plugin = process(mode)?;
        let descriptor = descriptor()?;
        let context = context(&descriptor);
        assert!(plugin.child_id().is_none()); // Construction/discovery does not spawn.
        plugin.initialize(&context)?;
        let pid = plugin.child_id().expect("child alive");
        plugin.start(&context)?;
        assert!(plugin.readiness(&context)?);
        plugin.pause(&context)?;
        plugin.resume(&context)?;
        assert!(plugin.readiness(&context)?);
        plugin.stop(&context)?;
        assert!(plugin.child_id().is_none());
        assert_reaped(pid);
        plugin.stop(&context)?;
        assert!(plugin.initialize(&context).is_err()); // No automatic respawn.
    }
    Ok(())
}

#[test]
fn subprocess_manager_pause_resume_and_redacted_lifecycle_events() -> TestResult {
    let descriptor = descriptor()?;
    let id = descriptor.id.clone();
    let dependent = PluginId::new("worker")?;
    let mut manager = PluginManager::new(vec![
        PluginRegistration {
            descriptor: PluginDescriptor {
                id: dependent.clone(),
                dependencies: vec![id.clone()],
                ..descriptor.clone()
            },
            plugin: Box::new(process("healthy")?),
        },
        PluginRegistration {
            descriptor,
            plugin: Box::new(process("healthy")?),
        },
    ])?;
    manager.start_all(&mut allow)?;
    manager.pause_all(&mut allow)?;
    assert_eq!(
        manager.status(&id).expect("status").state,
        PluginState::Paused
    );
    manager.pause_all(&mut allow)?;
    manager.resume_all(&mut allow)?;
    assert_eq!(
        manager.status(&id).expect("status").health,
        PluginHealth::Ready
    );
    assert_eq!(
        manager.status(&dependent).expect("status").state,
        PluginState::Running
    );
    manager.resume_all(&mut allow)?;
    manager.stop_all()?;
    let events = manager.drain_events().collect::<Vec<_>>();
    assert_eq!(events.len(), 16);
    assert!(
        events
            .iter()
            .all(|event| event.outcome == PluginOutcome::Success)
    );
    assert_eq!(
        events.last().expect("stop event").kind,
        PluginEventKind::Callback(PluginAction::Stop)
    );
    let operational = events
        .iter()
        .filter(|event| {
            matches!(
                event.kind,
                PluginEventKind::Callback(PluginAction::Pause | PluginAction::Resume)
            )
        })
        .map(|event| (event.id.as_str(), event.kind))
        .collect::<Vec<_>>();
    assert_eq!(
        operational,
        [
            ("worker", PluginEventKind::Callback(PluginAction::Pause)),
            ("child", PluginEventKind::Callback(PluginAction::Pause)),
            ("child", PluginEventKind::Callback(PluginAction::Resume)),
            ("worker", PluginEventKind::Callback(PluginAction::Resume)),
        ]
    );
    Ok(())
}

#[test]
fn subprocess_errors_eof_crash_malformed_oversize_and_deadlines_reap_child() -> TestResult {
    for mode in [
        "error",
        "eof",
        "crash",
        "malformed",
        "oversize",
        "wrong-sequence",
        "hang",
        "partial",
    ] {
        let mut plugin = process(mode)?;
        let descriptor = descriptor()?;
        let context = context(&descriptor);
        let began = Instant::now();
        let error = plugin.initialize(&context).expect_err("fault must fail");
        assert!(
            began.elapsed() < Duration::from_secs(3),
            "{mode} exceeded bound"
        );
        assert!(!error.contains("private-secret-details"));
        assert!(plugin.child_id().is_none(), "{mode} child not reaped");
        plugin.stop(&context)?;
    }
    Ok(())
}

#[test]
fn unsolicited_reply_and_exit_after_reply_fail_next_command() -> TestResult {
    for mode in ["extra", "exit-after-init"] {
        let mut plugin = process(mode)?;
        let descriptor = descriptor()?;
        let context = context(&descriptor);
        plugin.initialize(&context)?;
        let pid = plugin.child_id().expect("child");
        assert!(plugin.start(&context).is_err());
        assert!(plugin.child_id().is_none());
        assert_reaped(pid);
        plugin.stop(&context)?;
    }
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn already_exited_child_stop_completes_cleanup_without_protocol_error() -> TestResult {
    let mut plugin = process("exit-after-init")?;
    let descriptor = descriptor()?;
    let context = context(&descriptor);
    plugin.initialize(&context)?;
    let pid = plugin.child_id().expect("child handle");
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
        if stat
            .split_once(") ")
            .is_some_and(|(_, fields)| fields.starts_with("Z "))
        {
            break;
        }
        assert!(Instant::now() < deadline, "fixture did not exit");
        std::thread::sleep(Duration::from_millis(1));
    }
    plugin.stop(&context)?;
    assert!(plugin.child_id().is_none());
    assert_reaped(pid);
    plugin.stop(&context)?;
    Ok(())
}

#[test]
fn readiness_and_pause_resume_process_errors_require_manager_cleanup() -> TestResult {
    for mode in [
        "not-ready",
        "readiness-error",
        "pause-error",
        "resume-error",
    ] {
        let descriptor = descriptor()?;
        let id = descriptor.id.clone();
        let mut manager = PluginManager::new(vec![PluginRegistration {
            descriptor,
            plugin: Box::new(process(mode)?),
        }])?;
        if mode == "not-ready" || mode == "readiness-error" {
            manager.initialize(&id, &mut allow)?;
            assert!(manager.start(&id, &mut allow).is_err());
        } else {
            manager.start_all(&mut allow)?;
            if mode == "pause-error" {
                assert!(manager.pause_all(&mut allow).is_err());
            } else {
                manager.pause_all(&mut allow)?;
                assert!(manager.resume_all(&mut allow).is_err());
            }
        }
        let status = manager.status(&id).expect("status");
        assert_eq!(status.state, PluginState::Failed);
        assert!(status.cleanup_pending);
        assert_eq!(
            status.health,
            if mode == "not-ready" {
                PluginHealth::NotReady
            } else {
                PluginHealth::Unhealthy
            }
        );
        manager.stop_all()?;
        let status = manager.status(&id).expect("status");
        assert_eq!(status.state, PluginState::Failed);
        assert!(!status.cleanup_pending);
    }
    Ok(())
}

#[test]
fn stop_protocol_failure_still_reaps_and_retry_clears_cleanup_obligation() -> TestResult {
    for mode in ["stop-error", "stop-hang"] {
        let mut plugin = process(mode)?;
        let descriptor = descriptor()?;
        let context = context(&descriptor);
        plugin.initialize(&context)?;
        let pid = plugin.child_id().expect("child");
        let began = Instant::now();
        assert!(plugin.stop(&context).is_err());
        assert!(began.elapsed() < Duration::from_secs(3));
        assert!(plugin.child_id().is_none());
        assert_reaped(pid);
        plugin.stop(&context)?;

        let id = descriptor.id.clone();
        let mut manager = PluginManager::new(vec![PluginRegistration {
            descriptor,
            plugin: Box::new(process(mode)?),
        }])?;
        manager.start_all(&mut allow)?;
        assert!(manager.stop_all().is_err());
        let failed = manager.status(&id).expect("status");
        assert!(failed.cleanup_pending);
        assert!(failed.cleanup_error.is_some());
        manager.stop_all()?;
        let cleaned = manager.status(&id).expect("status");
        assert_eq!(cleaned.state, PluginState::Failed);
        assert!(!cleaned.cleanup_pending);
        assert!(cleaned.cleanup_error.is_none());
    }
    Ok(())
}

#[test]
fn drop_terminates_and_reaps_live_direct_child_without_stop_protocol() -> TestResult {
    let mut plugin = process("stop-hang")?;
    let descriptor = descriptor()?;
    plugin.initialize(&context(&descriptor))?;
    let pid = plugin.child_id().expect("live child");
    let began = Instant::now();
    drop(plugin);
    assert!(began.elapsed() < Duration::from_secs(3));
    assert_reaped(pid);
    Ok(())
}

#[test]
fn spawn_failure_is_bounded_and_cleanup_is_idempotent() -> TestResult {
    let mut plugin = ProcessPlugin::new(ProcessPluginConfig {
        executable: PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("nonexistent-plugin-executable"),
        args: vec![],
        timeout: TIMEOUT,
    })?;
    let descriptor = descriptor()?;
    assert!(plugin.initialize(&context(&descriptor)).is_err());
    assert!(plugin.child_id().is_none());
    plugin.stop(&context(&descriptor))?;
    Ok(())
}
