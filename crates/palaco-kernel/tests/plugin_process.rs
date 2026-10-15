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
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginError,
        PluginEventKind, PluginHealth, PluginId, PluginManager, PluginOutcome, PluginRegistration,
        PluginState, ShutdownOutcome, ShutdownScope,
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
fn shutdown_preview_never_spawns_or_calls_a_running_process() -> TestResult {
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
