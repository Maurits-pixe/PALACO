//! Trusted, statically linked, synchronous plugins. This is not a sandbox or an
//! authentication system. There are no hard timeouts, cancellation, hot reload,
//! async workers, or event engine. Unwinding callback panics are caught; aborting
//! panics and plugin-created tasks/resources are not isolated. Hosts must keep
//! the manager alive and retry failed cleanup before releasing plugin resources.

use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fmt,
    panic::{AssertUnwindSafe, catch_unwind},
};

use palaco_foundation::{ContractDisposition, EvidenceRef, Validatable};

use crate::RuntimePlan;

/// The only supported callback contract version.
pub const CONTRACT_VERSION: u32 = 1;

/// Stable ASCII identity: 1–64 lowercase letters, digits, `-`, `_`, or `.`;
/// the first character must be a letter.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct PluginId(String);

impl PluginId {
    /// Validates a host-supplied identity.
    pub fn new(value: impl Into<String>) -> Result<Self, PluginError> {
        let value = value.into();
        if value.is_empty()
            || value.len() > 64
            || !value.as_bytes()[0].is_ascii_lowercase()
            || !value
                .bytes()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"-_.".contains(&c))
        {
            return Err(PluginError::InvalidDescriptor("invalid plugin ID".into()));
        }
        Ok(Self(value))
    }

    /// Identity as supplied by the host.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Declarative metadata, never execution authority. Dependencies are required
/// IDs, not unenforceable package-version promises.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginDescriptor {
    pub id: PluginId,
    pub contract_version: u32,
    pub dependencies: Vec<PluginId>,
    pub evidence: EvidenceRef,
}

/// Callback context intentionally exposes no subsystem handles or authority.
pub struct PluginContext<'a> {
    pub id: &'a PluginId,
    pub evidence: &'a EvidenceRef,
}

/// Implementations must tolerate cleanup after partially completed callbacks.
/// `stop` must release all owned work and be safe to retry after an error.
pub trait Plugin {
    fn initialize(&mut self, context: &PluginContext<'_>) -> Result<(), String>;
    fn start(&mut self, context: &PluginContext<'_>) -> Result<(), String>;
    fn readiness(&mut self, context: &PluginContext<'_>) -> Result<bool, String>;
    fn stop(&mut self, context: &PluginContext<'_>) -> Result<(), String>;
}

/// Host-controlled registration, with no plugin callbacks during discovery.
pub struct PluginRegistration {
    pub descriptor: PluginDescriptor,
    pub plugin: Box<dyn Plugin>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginState {
    Registered,
    Initialized,
    Running,
    Stopped,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginHealth {
    Unknown,
    Ready,
    NotReady,
    Unhealthy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginAction {
    Initialize,
    Start,
    Readiness,
    Stop,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginFailure {
    pub action: PluginAction,
    pub message: String,
    pub panicked: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PluginError {
    InvalidDescriptor(String),
    UnknownPlugin(PluginId),
    InvalidTransition(PluginId, PluginState),
    DependencyNotRunning(PluginId),
    Authorization(PluginId, String),
    Callback(PluginId, PluginFailure),
}

impl fmt::Display for PluginError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PluginError {}

/// Read-only through the manager; the first lifecycle failure is retained
/// separately from the latest cleanup failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginStatus {
    pub state: PluginState,
    pub health: PluginHealth,
    pub failure: Option<PluginFailure>,
    pub cleanup_error: Option<PluginFailure>,
    pub cleanup_pending: bool,
}

/// Called afresh immediately before each initialization and startup callback.
/// The host must evaluate its *current* plan for this exact plugin and action;
/// neither metadata nor previously returned plans authenticate a plugin.
pub trait PluginAuthorizer {
    fn authorize(
        &mut self,
        descriptor: &PluginDescriptor,
        action: PluginAction,
    ) -> Result<RuntimePlan, String>;
}

impl<F> PluginAuthorizer for F
where
    F: FnMut(&PluginDescriptor, PluginAction) -> Result<RuntimePlan, String>,
{
    fn authorize(
        &mut self,
        descriptor: &PluginDescriptor,
        action: PluginAction,
    ) -> Result<RuntimePlan, String> {
        self(descriptor, action)
    }
}

struct Entry {
    registration: PluginRegistration,
    status: PluginStatus,
}

/// Exclusive synchronous lifecycle ownership. There is deliberately no unload
/// operation or public state setter, and no automatic initialization/start retry.
/// Registration is immutable after construction; shutdown is only via
/// `stop_all`, so a live dependent cannot be bypassed by stopping its dependency.
pub struct PluginManager {
    entries: BTreeMap<PluginId, Entry>,
    order: Vec<PluginId>,
}

impl PluginManager {
    /// Validates the entire graph before accepting registrations or invoking any
    /// callbacks. Ready DAG nodes are ordered lexicographically by ID.
    pub fn new(mut registrations: Vec<PluginRegistration>) -> Result<Self, PluginError> {
        registrations.sort_by(|a, b| a.descriptor.id.cmp(&b.descriptor.id));
        let mut entries = BTreeMap::new();
        for mut registration in registrations {
            registration.descriptor.dependencies.sort();
            let descriptor = &registration.descriptor;
            let unique: BTreeSet<_> = descriptor.dependencies.iter().collect();
            if descriptor.contract_version != CONTRACT_VERSION
                || descriptor.evidence.validate().is_err()
                || unique.len() != descriptor.dependencies.len()
                || entries.contains_key(&descriptor.id)
            {
                return Err(PluginError::InvalidDescriptor(format!(
                    "duplicate ID/dependency, unsupported contract, or invalid evidence: {}",
                    descriptor.id.as_str()
                )));
            }

            entries.insert(
                descriptor.id.clone(),
                Entry {
                    registration,
                    status: PluginStatus {
                        state: PluginState::Registered,
                        health: PluginHealth::Unknown,
                        failure: None,
                        cleanup_error: None,
                        cleanup_pending: false,
                    },
                },
            );
        }
        for entry in entries.values() {
            for dependency in &entry.registration.descriptor.dependencies {
                if !entries.contains_key(dependency) {
                    return Err(PluginError::InvalidDescriptor(format!(
                        "missing dependency: {}",
                        dependency.as_str()
                    )));
                }
            }
        }
        let mut remaining: BTreeSet<_> = entries.keys().cloned().collect();
        let mut order = Vec::new();
        while !remaining.is_empty() {
            let next = remaining.iter().find(|id| {
                entries[*id]
                    .registration
                    .descriptor
                    .dependencies
                    .iter()
                    .all(|dep| !remaining.contains(dep))
            });
            let Some(next) = next.cloned() else {
                return Err(PluginError::InvalidDescriptor("dependency cycle".into()));
            };
            remaining.remove(&next);
            order.push(next);
        }
        Ok(Self { entries, order })
    }

    pub fn order(&self) -> &[PluginId] {
        &self.order
    }

    pub fn descriptor(&self, id: &PluginId) -> Option<&PluginDescriptor> {
        self.entries.get(id).map(|e| &e.registration.descriptor)
    }

    pub fn status(&self, id: &PluginId) -> Option<&PluginStatus> {
        self.entries.get(id).map(|e| &e.status)
    }

    /// Initializes once. A callback failure marks the plugin Failed and leaves
    /// cleanup pending; call `stop_all` to release partially acquired resources.
    pub fn initialize(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_state(id, PluginState::Registered)?;
        self.authorize(id, PluginAction::Initialize, authorizer)?;
        self.invoke(id, PluginAction::Initialize)
    }

    /// Startup includes a synchronous readiness check under the fresh startup
    /// authorization. Running means that check succeeded, not continuous health.
    /// Callback failure leaves cleanup pending until `stop_all` is called.
    pub fn start(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_state(id, PluginState::Initialized)?;
        for dependency in &self.entries[id].registration.descriptor.dependencies {
            if self.entries[dependency].status.state != PluginState::Running {
                return Err(PluginError::DependencyNotRunning(dependency.clone()));
            }
        }
        self.authorize(id, PluginAction::Start, authorizer)?;
        self.invoke(id, PluginAction::Start)?;
        self.invoke(id, PluginAction::Readiness)
    }

    /// Starts a fresh manager in DAG order. Callback failures roll back acquired
    /// resources in reverse DAG order. Authorization denial leaves prior work
    /// untouched (and performs no callbacks); the host may explicitly stop it.
    pub fn start_all(&mut self, authorizer: &mut impl PluginAuthorizer) -> Result<(), PluginError> {
        for id in &self.order {
            self.require_state(id, PluginState::Registered)?;
        }
        for id in self.order.clone() {
            let result = self
                .initialize(&id, authorizer)
                .and_then(|()| self.start(&id, authorizer));
            if let Err(error) = result {
                if matches!(error, PluginError::Callback(..)) {
                    let _ = self.stop_all();
                }
                return Err(error);
            }
        }
        Ok(())
    }

    /// Always available without authorization, even after revocation. Attempts
    /// every eligible cleanup; errors remain queryable per plugin. A dependency
    /// is retained while any dependent's cleanup is pending.
    pub fn stop_all(&mut self) -> Result<(), PluginError> {
        let mut first_error = None;
        for id in self.order.clone().into_iter().rev() {
            let blocked = self.entries.values().any(|entry| {
                entry.status.cleanup_pending
                    && entry.registration.descriptor.dependencies.contains(&id)
            });
            if blocked || !self.entries[&id].status.cleanup_pending {
                continue;
            }
            if let Err(error) = self.invoke(&id, PluginAction::Stop) {
                first_error.get_or_insert(error);
            }
        }
        first_error.map_or(Ok(()), Err)
    }

    fn require_state(&self, id: &PluginId, state: PluginState) -> Result<(), PluginError> {
        let entry = self
            .entries
            .get(id)
            .ok_or_else(|| PluginError::UnknownPlugin(id.clone()))?;
        if entry.status.state != state {
            return Err(PluginError::InvalidTransition(
                id.clone(),
                entry.status.state,
            ));
        }
        Ok(())
    }

    fn authorize(
        &self,
        id: &PluginId,
        action: PluginAction,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        let result = catch_unwind(AssertUnwindSafe(|| {
            let plan = authorizer.authorize(&self.entries[id].registration.descriptor, action)?;
            plan.validate().map_err(|error| error.to_string())?;
            if plan.disposition() != ContractDisposition::Execute {
                return Err(format!("execution not permitted: {:?}", plan.disposition()));
            }
            Ok(())
        }))
        .unwrap_or_else(|_| Err("authorizer panicked".into()));
        result.map_err(|message| PluginError::Authorization(id.clone(), message))
    }

    fn invoke(&mut self, id: &PluginId, action: PluginAction) -> Result<(), PluginError> {
        let entry = self.entries.get_mut(id).expect("validated plugin ID");
        entry.status.cleanup_pending = true;
        let context = PluginContext {
            id: &entry.registration.descriptor.id,
            evidence: &entry.registration.descriptor.evidence,
        };
        let plugin = &mut entry.registration.plugin;
        let result = catch_unwind(AssertUnwindSafe(|| match action {
            PluginAction::Initialize => plugin.initialize(&context).map(|()| true),
            PluginAction::Start => plugin.start(&context).map(|()| true),
            PluginAction::Readiness => plugin.readiness(&context),
            PluginAction::Stop => plugin.stop(&context).map(|()| true),
        }));
        let not_ready = matches!(result, Ok(Ok(false)));
        let failure = match result {
            Ok(Ok(true)) => {
                match action {
                    PluginAction::Initialize => entry.status.state = PluginState::Initialized,
                    PluginAction::Start => {}
                    PluginAction::Readiness => {
                        entry.status.state = PluginState::Running;
                        entry.status.health = PluginHealth::Ready;
                    }
                    PluginAction::Stop => {
                        entry.status.cleanup_pending = false;
                        entry.status.cleanup_error = None;
                        if entry.status.failure.is_none() {
                            entry.status.state = PluginState::Stopped;
                            entry.status.health = PluginHealth::Unknown;
                        }
                    }
                }
                return Ok(());
            }
            Ok(Ok(false)) => PluginFailure {
                action,
                message: "plugin is not ready".into(),
                panicked: false,
            },
            Ok(Err(message)) => PluginFailure {
                action,
                message,
                panicked: false,
            },
            Err(_) => PluginFailure {
                action,
                message: "plugin callback panicked".into(),
                panicked: true,
            },
        };
        entry.status.state = PluginState::Failed;
        entry.status.health = if not_ready {
            PluginHealth::NotReady
        } else {
            PluginHealth::Unhealthy
        };
        if action == PluginAction::Stop {
            entry.status.cleanup_error = Some(failure.clone());
        }
        if entry.status.failure.is_none() {
            entry.status.failure = Some(failure.clone());
        }
        Err(PluginError::Callback(id.clone(), failure))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct NoCallbacks;

    impl Plugin for NoCallbacks {
        fn initialize(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
            panic!("unexpected initialize");
        }

        fn start(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
            panic!("unexpected start");
        }

        fn readiness(&mut self, _: &PluginContext<'_>) -> Result<bool, String> {
            panic!("unexpected readiness");
        }

        fn stop(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
            panic!("unexpected cleanup");
        }
    }

    fn registration(id: &str, dependencies: &[&str]) -> PluginRegistration {
        PluginRegistration {
            descriptor: PluginDescriptor {
                id: PluginId::new(id).expect("valid test ID"),
                contract_version: CONTRACT_VERSION,
                dependencies: dependencies
                    .iter()
                    .map(|id| PluginId::new(*id).expect("valid dependency"))
                    .collect(),
                evidence: EvidenceRef::new("test-evidence").expect("valid evidence"),
            },
            plugin: Box::new(NoCallbacks),
        }
    }

    #[test]
    fn descriptor_graph_validation_precedes_every_callback() {
        for registrations in [
            vec![registration("a", &[]), registration("a", &[])],
            vec![registration("a", &["missing"])],
            vec![registration("a", &["b"]), registration("b", &["a"])],
            vec![registration("a", &["a"])],
            vec![registration("a", &["b", "b"]), registration("b", &[])],
        ] {
            assert!(matches!(
                PluginManager::new(registrations),
                Err(PluginError::InvalidDescriptor(_))
            ));
        }
        let mut bad = registration("bad", &[]);
        bad.descriptor.contract_version = CONTRACT_VERSION + 1;
        assert!(PluginManager::new(vec![registration("good", &[]), bad]).is_err());
    }

    #[test]
    fn id_validation_is_strict_and_bounded() {
        for id in ["", "A", "-a", "a b", "a/b", "é"] {
            assert!(PluginId::new(id).is_err());
        }
        assert!(PluginId::new("a".repeat(65)).is_err());
        assert!(PluginId::new("a-1_x.y").is_ok());
        assert!(
            PluginManager::new(Vec::new())
                .expect("empty manager")
                .order()
                .is_empty()
        );
    }

    #[test]
    fn denial_does_not_advance_state_or_acquire_cleanup_obligations() {
        let mut manager = PluginManager::new(vec![registration("a", &[])]).expect("valid graph");
        let a = PluginId::new("a").expect("valid ID");
        let before = manager.status(&a).expect("status").clone();
        let mut deny = |_: &PluginDescriptor, _: PluginAction| Err("host denies".into());
        assert!(matches!(
            manager.initialize(&a, &mut deny),
            Err(PluginError::Authorization(..))
        ));
        assert_eq!(manager.status(&a), Some(&before));
        manager.stop_all().expect("nothing to clean up");
        assert_eq!(manager.status(&a), Some(&before));
    }
}
