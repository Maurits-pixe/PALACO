use std::{cell::RefCell, error::Error, rc::Rc};

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef, Validatable};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginError,
        PluginHealth, PluginId, PluginManager, PluginRegistration, PluginState,
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
        Ok(!self.behavior.not_ready)
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
