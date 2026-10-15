//! Synchronous trusted plugins with host authorization and bounded pull events.
//! In-process callbacks have no timeout or sandbox. See [`process`] for optional
//! child-process crash isolation (also not an OS sandbox).

pub mod process;

use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    error::Error,
    fmt,
    panic::{AssertUnwindSafe, catch_unwind},
};

use palaco_foundation::{ContractDisposition, EvidenceRef, Validatable};

use crate::RuntimePlan;

/// The only supported callback contract version.
pub const CONTRACT_VERSION: u32 = 1;

/// Bounds evidence metadata copied into lifecycle observations.
pub const MAX_PLUGIN_EVIDENCE_BYTES: usize = 1024;

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
    /// Quiesce business work while retaining resources. Unsupported by default.
    fn pause(&mut self, _context: &PluginContext<'_>) -> Result<(), String> {
        Err("pause unsupported".into())
    }
    fn resume(&mut self, _context: &PluginContext<'_>) -> Result<(), String> {
        Err("resume unsupported".into())
    }
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
    /// Start/resume succeeded, but readiness has not yet been authorized/proven.
    Starting,
    Running,
    Paused,
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
    Pause,
    Resume,
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
    DependencyInUse(PluginId),
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

/// Called afresh immediately before every operational callback, including
/// readiness, pause, and resume. Cleanup deliberately bypasses authorization.
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

/// Redacted status: never includes plugin/authorizer error text or configuration.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PluginSnapshot {
    pub state: PluginState,
    pub health: PluginHealth,
    pub cleanup_pending: bool,
    pub failed: bool,
    pub cleanup_failed: bool,
}

impl From<&PluginStatus> for PluginSnapshot {
    fn from(status: &PluginStatus) -> Self {
        Self {
            state: status.state,
            health: status.health,
            cleanup_pending: status.cleanup_pending,
            failed: status.failure.is_some(),
            cleanup_failed: status.cleanup_error.is_some(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginEventKind {
    Registered,
    Callback(PluginAction),
    AuthorizationRejected(PluginAction),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginOutcome {
    Success,
    NotReady,
    Error,
    Panicked,
    Rejected,
}

/// Manager-local observations, not authenticated or persistent audit records.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginEvent {
    pub sequence: u64,
    pub id: PluginId,
    pub evidence: EvidenceRef,
    pub kind: PluginEventKind,
    pub previous: PluginSnapshot,
    pub current: PluginSnapshot,
    pub outcome: PluginOutcome,
}

pub const DEFAULT_EVENT_CAPACITY: usize = 256;

/// Exclusive synchronous lifecycle ownership. There is deliberately no unload
/// operation or public state setter, and no automatic initialization/start retry.
/// Registration is immutable after construction; shutdown is only via
/// `stop_all`, so a live dependent cannot be bypassed by stopping its dependency.
pub struct PluginManager {
    entries: BTreeMap<PluginId, Entry>,
    order: Vec<PluginId>,
    events: VecDeque<PluginEvent>,
    event_capacity: usize,
    sequence: u64,
    lost_events: u64,
}

impl PluginManager {
    /// Validates the entire graph before accepting registrations or invoking any
    /// callbacks. Ready DAG nodes are ordered lexicographically by ID.
    pub fn new(registrations: Vec<PluginRegistration>) -> Result<Self, PluginError> {
        Self::with_event_capacity(registrations, DEFAULT_EVENT_CAPACITY)
    }

    /// Drop the oldest event on overflow; zero capacity drops every event.
    /// The capacity is limited to 65,536. Loss is cumulative across drains.
    pub fn with_event_capacity(
        mut registrations: Vec<PluginRegistration>,
        event_capacity: usize,
    ) -> Result<Self, PluginError> {
        if event_capacity > 65_536 {
            return Err(PluginError::InvalidDescriptor(
                "event capacity too large".into(),
            ));
        }
        registrations.sort_by(|a, b| a.descriptor.id.cmp(&b.descriptor.id));
        let mut entries = BTreeMap::new();
        for mut registration in registrations {
            registration.descriptor.dependencies.sort();
            let descriptor = &registration.descriptor;
            let unique: BTreeSet<_> = descriptor.dependencies.iter().collect();
            if descriptor.contract_version != CONTRACT_VERSION
                || descriptor.evidence.validate().is_err()
                || descriptor.evidence.as_str().len() > MAX_PLUGIN_EVIDENCE_BYTES
                || unique.len() != descriptor.dependencies.len()
                || entries.contains_key(&descriptor.id)
            {
                return Err(PluginError::InvalidDescriptor(format!(
                    "duplicate ID/dependency, unsupported contract, or invalid/oversized evidence: {}",
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
        let mut manager = Self {
            entries,
            order,
            events: VecDeque::new(),
            event_capacity,
            sequence: 0,
            lost_events: 0,
        };
        for id in manager.order.clone() {
            let snapshot = PluginSnapshot::from(&manager.entries[&id].status);
            manager.record(
                &id,
                PluginEventKind::Registered,
                snapshot,
                PluginOutcome::Success,
            );
        }
        Ok(manager)
    }

    pub fn drain_events(&mut self) -> impl Iterator<Item = PluginEvent> + '_ {
        self.events.drain(..)
    }

    pub fn lost_events(&self) -> u64 {
        self.lost_events
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

    /// Startup includes a separately authorized synchronous readiness check.
    /// Running means that check succeeded, not continuous health.
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
        self.authorize(id, PluginAction::Readiness, authorizer)?;
        self.invoke(id, PluginAction::Readiness)
    }

    /// Pause dependents before dependencies. Paused dependents retain resources
    /// but promise no active business work; they still block dependency shutdown.
    /// Failed dependents with pending cleanup block both pause and shutdown.
    pub fn pause(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_state(id, PluginState::Running)?;
        if let Some((dependent, _)) = self.entries.iter().find(|(_, entry)| {
            entry.registration.descriptor.dependencies.contains(id)
                && (matches!(
                    entry.status.state,
                    PluginState::Running | PluginState::Starting
                ) || (entry.status.state == PluginState::Failed
                    && entry.status.cleanup_pending))
        }) {
            return Err(PluginError::DependencyInUse(dependent.clone()));
        }
        self.authorize(id, PluginAction::Pause, authorizer)?;
        self.invoke(id, PluginAction::Pause)
    }

    /// Resume dependencies first. Both resume and readiness need fresh authority.
    pub fn resume(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_state(id, PluginState::Paused)?;
        for dependency in &self.entries[id].registration.descriptor.dependencies {
            if self.entries[dependency].status.state != PluginState::Running {
                return Err(PluginError::DependencyNotRunning(dependency.clone()));
            }
        }
        self.authorize(id, PluginAction::Resume, authorizer)?;
        self.invoke(id, PluginAction::Resume)?;
        self.authorize(id, PluginAction::Readiness, authorizer)?;
        self.invoke(id, PluginAction::Readiness)
    }

    /// Pauses Running plugins in reverse DAG order, skipping Paused plugins.
    /// Preflights the entire fleet before authorization or callbacks: only
    /// Running/Paused states are accepted (an empty fleet succeeds). The first
    /// invalid state in DAG order is returned without events or side effects.
    /// Stops on the first error without rollback, retry, or automatic cleanup;
    /// partial progress and per-plugin failure/cleanup tracking are retained.
    pub fn pause_all(&mut self, authorizer: &mut impl PluginAuthorizer) -> Result<(), PluginError> {
        self.require_running_or_paused()?;
        for id in self.order.clone().into_iter().rev() {
            if self.entries[&id].status.state == PluginState::Running {
                self.pause(&id, authorizer)?;
            }
        }
        Ok(())
    }

    /// Resumes Paused plugins in DAG order, skipping Running plugins.
    /// Uses the same fleet preflight and partial-progress semantics as
    /// [`Self::pause_all`]. Resume and readiness each require fresh authority.
    /// Pure authorization rejection permits retry while all states remain
    /// Running/Paused; Starting or Failed requires explicit `stop_all` cleanup,
    /// not a business-operation retry.
    pub fn resume_all(
        &mut self,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_running_or_paused()?;
        for id in self.order.clone() {
            if self.entries[&id].status.state == PluginState::Paused {
                self.resume(&id, authorizer)?;
            }
        }
        Ok(())
    }

    fn require_running_or_paused(&self) -> Result<(), PluginError> {
        for id in &self.order {
            let state = self.entries[id].status.state;
            if !matches!(state, PluginState::Running | PluginState::Paused) {
                return Err(PluginError::InvalidTransition(id.clone(), state));
            }
        }
        Ok(())
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
        &mut self,
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
        result.map_err(|message| {
            let snapshot = PluginSnapshot::from(&self.entries[id].status);
            self.record(
                id,
                PluginEventKind::AuthorizationRejected(action),
                snapshot,
                PluginOutcome::Rejected,
            );
            PluginError::Authorization(id.clone(), message)
        })
    }

    fn invoke(&mut self, id: &PluginId, action: PluginAction) -> Result<(), PluginError> {
        let entry = self.entries.get_mut(id).expect("validated plugin ID");
        let previous = PluginSnapshot::from(&entry.status);
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
            PluginAction::Pause => plugin.pause(&context).map(|()| true),
            PluginAction::Resume => plugin.resume(&context).map(|()| true),
            PluginAction::Stop => plugin.stop(&context).map(|()| true),
        }));
        let not_ready = matches!(result, Ok(Ok(false)));
        let failure = match result {
            Ok(Ok(true)) => {
                match action {
                    PluginAction::Initialize => entry.status.state = PluginState::Initialized,
                    PluginAction::Start | PluginAction::Resume => {
                        // A successful resume may already have activated work.
                        // Track active work even if readiness authorization is denied.
                        entry.status.state = PluginState::Starting;
                        entry.status.health = PluginHealth::Unknown;
                    }
                    PluginAction::Pause => {
                        entry.status.state = PluginState::Paused;
                        entry.status.health = PluginHealth::Unknown;
                    }
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
                self.record(
                    id,
                    PluginEventKind::Callback(action),
                    previous,
                    PluginOutcome::Success,
                );
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
        let outcome = if failure.panicked {
            PluginOutcome::Panicked
        } else if not_ready {
            PluginOutcome::NotReady
        } else {
            PluginOutcome::Error
        };
        self.record(id, PluginEventKind::Callback(action), previous, outcome);
        Err(PluginError::Callback(id.clone(), failure))
    }

    fn record(
        &mut self,
        id: &PluginId,
        kind: PluginEventKind,
        previous: PluginSnapshot,
        outcome: PluginOutcome,
    ) {
        self.sequence = self
            .sequence
            .checked_add(1)
            .expect("event sequence exhausted");
        if self.events.len() == self.event_capacity {
            self.events.pop_front();
            self.lost_events = self.lost_events.saturating_add(1);
        }
        if self.event_capacity == 0 {
            return;
        }
        let entry = &self.entries[id];
        self.events.push_back(PluginEvent {
            sequence: self.sequence,
            id: id.clone(),
            evidence: entry.registration.descriptor.evidence.clone(),
            kind,
            previous,
            current: PluginSnapshot::from(&entry.status),
            outcome,
        });
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
        let mut bad = registration("bad", &[]);
        bad.descriptor.evidence =
            EvidenceRef::new("e".repeat(MAX_PLUGIN_EVIDENCE_BYTES + 1)).expect("nonempty evidence");
        assert!(PluginManager::new(vec![bad]).is_err());
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
