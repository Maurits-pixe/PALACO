#![cfg(feature = "plugin-process-tests")]

use std::{
    error::Error,
    path::PathBuf,
    time::{Duration, Instant},
};

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginEventKind,
        PluginHealth, PluginId, PluginManager, PluginOutcome, PluginRegistration, PluginState,
        process::{ProcessPlugin, ProcessPluginConfig},
    },
};

type TestResult = Result<(), Box<dyn Error>>;
const TIMEOUT: Duration = Duration::from_millis(500);

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
    let mut manager = PluginManager::new(vec![PluginRegistration {
        descriptor,
        plugin: Box::new(process("healthy")?),
    }])?;
    manager.start_all(&mut allow)?;
    manager.pause(&id, &mut allow)?;
    assert_eq!(
        manager.status(&id).expect("status").state,
        PluginState::Paused
    );
    manager.resume(&id, &mut allow)?;
    assert_eq!(
        manager.status(&id).expect("status").health,
        PluginHealth::Ready
    );
    manager.stop_all()?;
    let events = manager.drain_events().collect::<Vec<_>>();
    assert_eq!(events.len(), 8);
    assert!(
        events
            .iter()
            .all(|event| event.outcome == PluginOutcome::Success)
    );
    assert_eq!(
        events.last().expect("stop event").kind,
        PluginEventKind::Callback(PluginAction::Stop)
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
                assert!(manager.pause(&id, &mut allow).is_err());
            } else {
                manager.pause(&id, &mut allow)?;
                assert!(manager.resume(&id, &mut allow).is_err());
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
