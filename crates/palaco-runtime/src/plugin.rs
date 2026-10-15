//! Synchronous trusted plugins with host authorization and bounded pull events.
//! In-process callbacks have no timeout or sandbox. See [`process`] for optional
//! child-process crash isolation (also not an OS sandbox).
//! Selective and fleet cleanup bypass authorization and retain dependencies until
//! their dependents finish cleanup.

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
    DependencyNotReady(PluginId),
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

/// Owned, redacted current observation of one node, including inactive nodes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FleetEntry {
    pub id: PluginId,
    pub snapshot: PluginSnapshot,
    /// Direct dependency IDs in lexicographic order, not a transitive closure.
    pub dependencies: Vec<PluginId>,
    /// Direct dependent IDs in lexicographic order, regardless of lifecycle state.
    pub dependents: Vec<PluginId>,
}

/// Manager-local event counters, observed without draining or resetting them.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventBufferSnapshot {
    capacity: usize,
    queued: usize,
    last_sequence: u64,
    lost_events: u64,
}

impl EventBufferSnapshot {
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn queued(&self) -> usize {
        self.queued
    }

    /// Last emitted sequence, including dropped/drained events; zero before any.
    /// Manager-local only: not globally unique, authenticated, or an audit record.
    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }

    /// Cumulative overflow loss, including every emission at zero capacity.
    pub fn lost_events(&self) -> u64 {
        self.lost_events
    }
}

/// Immutable owned fleet observation; may become stale immediately.
/// Retained health is not a fresh probe, continuous readiness, or authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FleetInventory {
    entries: Vec<FleetEntry>,
    event_buffer: EventBufferSnapshot,
}

impl FleetInventory {
    /// Entire fleet in deterministic topological order, in any lifecycle state.
    pub fn entries(&self) -> &[FleetEntry] {
        &self.entries
    }

    pub fn event_buffer(&self) -> &EventBufferSnapshot {
        &self.event_buffer
    }
}

/// Local startup preflight eligibility, not simulated dependency readiness or
/// a guarantee that initialization, startup, or readiness callbacks will succeed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StartupDisposition {
    /// Registered: expected to start after earlier prerequisites in the plan.
    Start,
    /// Running with retained Ready health; scoped startup skips this node.
    AlreadyRunning,
    /// Running without retained Ready health, including at the root.
    NotReady,
    /// Neither Registered nor Running; see the step's snapshot for its state.
    InvalidState,
}

impl StartupDisposition {
    fn classify(snapshot: PluginSnapshot) -> Self {
        match snapshot.state {
            PluginState::Registered => Self::Start,
            PluginState::Running if snapshot.health == PluginHealth::Ready => Self::AlreadyRunning,
            PluginState::Running => Self::NotReady,
            _ => Self::InvalidState,
        }
    }
}

/// Owned, redacted observation of one selected startup node.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartupStep {
    pub id: PluginId,
    pub snapshot: PluginSnapshot,
    pub disposition: StartupDisposition,
}

/// Immutable read-only startup preview, not authority or an executable token.
/// Snapshots can become stale; live startup recomputes selection and preflight.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartupPlan {
    steps: Vec<StartupStep>,
}

impl StartupPlan {
    /// All selected nodes, including blockers and no-ops, in topological order.
    pub fn steps(&self) -> &[StartupStep] {
        &self.steps
    }

    /// Every node is locally eligible for scoped startup at this snapshot.
    /// The entire scope must pass preflight before any callback; a Start node
    /// may still have a blocked prerequisite. This is no success guarantee.
    pub fn can_start(&self) -> bool {
        self.steps.iter().all(|step| {
            matches!(
                step.disposition,
                StartupDisposition::Start | StartupDisposition::AlreadyRunning
            )
        })
    }
}

/// Fresh probe outcome, independent of any readiness retained in the snapshot.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HealthOutcome {
    Ready,
    NotReady,
    Rejected,
    Error,
    Panicked,
    SkippedPaused,
    /// A preceding probe failed or was rejected; no authorization was requested.
    NotAttempted,
}

/// Owned, redacted observation of one fleet node, without evidence or error text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HealthEntry {
    pub id: PluginId,
    pub previous: PluginSnapshot,
    pub current: PluginSnapshot,
    pub outcome: HealthOutcome,
}

/// Immutable result of side-effecting readiness probes, not authority or an audit.
/// Snapshots may become stale; entries are retained independently of event loss.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HealthReport {
    entries: Vec<HealthEntry>,
}

impl HealthReport {
    /// Every fleet node in deterministic topological order, including skipped nodes.
    pub fn entries(&self) -> &[HealthEntry] {
        &self.entries
    }

    /// All Running nodes were successfully probed; Paused nodes are skipped by policy.
    /// NotReady is complete. Empty and entirely Paused fleets are complete.
    pub fn complete(&self) -> bool {
        self.entries.iter().all(|entry| {
            matches!(
                entry.outcome,
                HealthOutcome::Ready | HealthOutcome::NotReady | HealthOutcome::SkippedPaused
            )
        })
    }

    /// Every fleet entry was freshly Ready. Paused nodes make this false;
    /// an empty fleet is vacuously all ready. Never inferred from stored health.
    pub fn all_ready(&self) -> bool {
        self.entries
            .iter()
            .all(|entry| entry.outcome == HealthOutcome::Ready)
    }
}

/// Graph selection for shutdown preview or side-effecting execution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShutdownScope {
    Single(PluginId),
    /// Root and all transitive dependents, including inactive intermediaries.
    WithDependents(PluginId),
    All,
}

/// One shutdown candidate, including candidates with no pending cleanup.
/// Contains bounded IDs and redacted status, never error text or evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShutdownStep {
    pub id: PluginId,
    pub snapshot: PluginSnapshot,
    /// All direct dependents currently pending cleanup, lexicographically sorted,
    /// even outside the scope. Not predicted blockers at execution time: an earlier
    /// step may successfully clean up a dependent and unblock this candidate.
    pub blockers: Vec<PluginId>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShutdownOutcome {
    /// No pending cleanup; no callback was attempted.
    NoOp,
    /// Cleanup succeeded, even if the lifecycle state remains Failed.
    Stopped,
    Blocked,
    Error,
    Panicked,
}

/// Owned, redacted observation of one execution turn, not an authenticated audit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShutdownEntry {
    pub id: PluginId,
    pub previous: PluginSnapshot,
    pub current: PluginSnapshot,
    pub outcome: ShutdownOutcome,
    /// Sorted direct blockers observed at this turn, after earlier cleanup.
    /// Populated only for Blocked pending targets, never for no-ops.
    pub blockers: Vec<PluginId>,
}

/// Immutable owned snapshot returned by side-effecting shutdown; may become stale.
/// Contains no error text, panic payloads, evidence, configuration, or authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShutdownReport {
    entries: Vec<ShutdownEntry>,
    complete: bool,
}

impl ShutdownReport {
    /// All selected nodes, including no-ops, in reverse topological order.
    pub fn entries(&self) -> &[ShutdownEntry] {
        &self.entries
    }

    /// True exactly when all selected nodes had no pending cleanup at return.
    /// Registered no-ops count as complete; unrelated plugins may still be running.
    pub fn complete(&self) -> bool {
        self.complete
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
/// Registration is immutable after construction; all cleanup operations retain
/// dependencies while a dependent has pending cleanup.
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

    /// Reads the entire current fleet without lifecycle preflight, authorization,
    /// callbacks, probes, process I/O/spawning, events, or counter/status changes.
    /// Copies bounded IDs and redacted status only, never evidence, errors, panic
    /// payloads, configuration, executable arguments, or process identifiers.
    /// Direct graph relations include inactive nodes; no transitive health,
    /// registry/PCR integration, authority, or authenticated auditing is implied.
    pub fn inventory(&self) -> FleetInventory {
        let entries = self
            .order
            .iter()
            .map(|id| {
                let entry = &self.entries[id];
                let mut dependencies = entry.registration.descriptor.dependencies.clone();
                dependencies.sort();
                let dependents = self
                    .entries
                    .iter()
                    .filter(|(_, entry)| entry.registration.descriptor.dependencies.contains(id))
                    .map(|(id, _)| id.clone())
                    .collect();
                FleetEntry {
                    id: id.clone(),
                    snapshot: PluginSnapshot::from(&entry.status),
                    dependencies,
                    dependents,
                }
            })
            .collect();
        FleetInventory {
            entries,
            event_buffer: EventBufferSnapshot {
                capacity: self.event_capacity,
                queued: self.events.len(),
                last_sequence: self.sequence,
                lost_events: self.lost_events,
            },
        }
    }

    /// Previews every selected node in reverse-topological execution candidate
    /// order, including no-ops. Unknown roots return `UnknownPlugin`.
    /// Reads only the current graph/status: no authorization, callbacks, process
    /// spawning, events, or state changes. This is not an executable token,
    /// authorization, reservation, or guarantee of callback success. Normal stop
    /// methods re-evaluate live state; blockers are current, not simulated.
    pub fn plan_shutdown(&self, scope: ShutdownScope) -> Result<Vec<ShutdownStep>, PluginError> {
        Ok(self
            .shutdown_selection(scope)?
            .into_iter()
            .map(|id| ShutdownStep {
                snapshot: PluginSnapshot::from(&self.entries[&id].status),
                blockers: self.cleanup_blockers(&id).cloned().collect(),
                id,
            })
            .collect())
    }

    /// **Executes cleanup callbacks**, not a dry run or cached-preview executor.
    /// Recalculates live selection; unknown roots fail before any side effects.
    /// No authorization is required, including after revocation. Each eligible
    /// pending node is attempted once; errors/panics retain status and cleanup
    /// obligations while independent nodes continue. Blocked Single returns an
    /// Ok report, unlike `stop`'s DependencyInUse error. Inspect `complete()`, not
    /// just Ok: callback failures and blockers are typed report outcomes.
    /// Only actual callbacks emit existing lifecycle events; no-ops and blockers
    /// emit nothing. Reports are independent of event queue overflow.
    pub fn execute_shutdown(
        &mut self,
        scope: ShutdownScope,
    ) -> Result<ShutdownReport, PluginError> {
        let selected = self.shutdown_selection(scope)?;
        let mut entries = Vec::with_capacity(selected.len());
        for id in &selected {
            let previous = PluginSnapshot::from(&self.entries[id].status);
            let mut blockers = Vec::new();
            let outcome = if !previous.cleanup_pending {
                ShutdownOutcome::NoOp
            } else {
                blockers = self.cleanup_blockers(id).cloned().collect();
                if !blockers.is_empty() {
                    ShutdownOutcome::Blocked
                } else {
                    match self.invoke(id, PluginAction::Stop) {
                        Ok(()) => ShutdownOutcome::Stopped,
                        Err(PluginError::Callback(_, failure)) if failure.panicked => {
                            ShutdownOutcome::Panicked
                        }
                        Err(_) => ShutdownOutcome::Error,
                    }
                }
            };
            entries.push(ShutdownEntry {
                id: id.clone(),
                previous,
                current: PluginSnapshot::from(&self.entries[id].status),
                outcome,
                blockers,
            });
        }
        let complete = selected
            .iter()
            .all(|id| !self.entries[id].status.cleanup_pending);
        Ok(ShutdownReport { entries, complete })
    }

    fn shutdown_selection(&self, scope: ShutdownScope) -> Result<Vec<PluginId>, PluginError> {
        let selected = match scope {
            ShutdownScope::Single(id) => {
                if !self.entries.contains_key(&id) {
                    return Err(PluginError::UnknownPlugin(id));
                }
                BTreeSet::from([id])
            }
            ShutdownScope::WithDependents(id) => self.dependent_closure(&id)?,
            ShutdownScope::All => self.entries.keys().cloned().collect(),
        };
        Ok(self
            .order
            .iter()
            .rev()
            .filter(|id| selected.contains(*id))
            .cloned()
            .collect())
    }

    /// Initializes once. A callback failure marks the plugin Failed and leaves
    /// cleanup pending; call `stop` or `stop_all` to release acquired resources.
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
    /// Direct dependencies must be Running and Ready. Running means startup
    /// readiness succeeded; later probes may report NotReady, not continuous health.
    /// Callback failure leaves cleanup pending until `stop` or `stop_all` is called.
    pub fn start(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_state(id, PluginState::Initialized)?;
        self.require_dependencies_ready(id)?;
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

    /// Resume dependencies first: each must be Running and Ready.
    /// Both resume and readiness need fresh authority.
    pub fn resume(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        self.require_state(id, PluginState::Paused)?;
        self.require_dependencies_ready(id)?;
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
    /// Running/Paused; Starting or Failed requires explicit `stop`/`stop_all` cleanup,
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

    /// Host-scheduled direct readiness snapshot, not transitive health or authority.
    /// False retains Running and cleanup obligations; errors/panics are terminal.
    /// In-process callbacks have no timeout. Scheduling belongs to the host.
    pub fn check_health(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<PluginHealth, PluginError> {
        self.require_state(id, PluginState::Running)?;
        self.authorize(id, PluginAction::Readiness, authorizer)?;
        self.invoke(id, PluginAction::Readiness)?;
        Ok(self.entries[id].status.health)
    }

    /// Preflights Running/Paused like [`Self::pause_all`], then probes Running
    /// plugins in DAG order, skipping Paused. NotReady does not abort the batch.
    /// The first error stops probing; prior snapshots/events remain available.
    pub fn check_health_all(
        &mut self,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<Vec<(PluginId, PluginHealth)>, PluginError> {
        self.require_running_or_paused()?;
        let mut health = Vec::new();
        for id in self.order.clone() {
            if self.entries[&id].status.state == PluginState::Running {
                let snapshot = self.check_health(&id, authorizer)?;
                health.push((id, snapshot));
            }
        }
        Ok(health)
    }

    /// Side-effecting, host-scheduled fleet readiness probes with partial results.
    /// Preflights all states before any side effects. Only preflight returns Err;
    /// Ok does not imply health success: inspect complete, all_ready, and entries.
    /// Probing stops at the first rejection/error/panic, but every node is reported.
    /// No retries, automatic cleanup, transitive inference, or extra events.
    pub fn check_health_report(
        &mut self,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<HealthReport, PluginError> {
        self.require_running_or_paused()?;
        let mut entries = Vec::with_capacity(self.order.len());
        let mut halted = false;
        for id in self.order.clone() {
            let previous = PluginSnapshot::from(&self.entries[&id].status);
            let outcome = if previous.state == PluginState::Paused {
                HealthOutcome::SkippedPaused
            } else if halted {
                HealthOutcome::NotAttempted
            } else {
                match self.check_health(&id, authorizer) {
                    Ok(PluginHealth::Ready) => HealthOutcome::Ready,
                    Ok(_) => HealthOutcome::NotReady,
                    Err(error) => {
                        halted = true;
                        match error {
                            PluginError::Authorization(..) => HealthOutcome::Rejected,
                            PluginError::Callback(_, failure) if failure.panicked => {
                                HealthOutcome::Panicked
                            }
                            _ => HealthOutcome::Error,
                        }
                    }
                }
            };
            entries.push(HealthEntry {
                current: PluginSnapshot::from(&self.entries[&id].status),
                id,
                previous,
                outcome,
            });
        }
        Ok(HealthReport { entries })
    }

    fn require_dependencies_ready(&self, id: &PluginId) -> Result<(), PluginError> {
        let dependencies = &self.entries[id].registration.descriptor.dependencies;
        // Preserve existing non-Running dependency errors before checking health.
        for dependency in dependencies {
            if self.entries[dependency].status.state != PluginState::Running {
                return Err(PluginError::DependencyNotRunning(dependency.clone()));
            }
        }
        for dependency in dependencies {
            if self.entries[dependency].status.health != PluginHealth::Ready {
                return Err(PluginError::DependencyNotReady(dependency.clone()));
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

    /// Previews exactly the root and its transitive required dependencies in
    /// deterministic DAG order, including every blocker. Only an unknown root
    /// returns an error. Dispositions describe local eligibility, not simulated
    /// startup: Registered prerequisites are expected to start earlier.
    /// No authorization, callbacks, health probes, process I/O/spawning, events,
    /// or status changes occur. This is no reservation or time-valid guarantee;
    /// `start_with_dependencies` recomputes live preflight and authorizes actions.
    pub fn plan_startup(&self, id: &PluginId) -> Result<StartupPlan, PluginError> {
        Ok(StartupPlan {
            steps: self
                .startup_selection(id)?
                .into_iter()
                .map(|id| {
                    let snapshot = PluginSnapshot::from(&self.entries[&id].status);
                    StartupStep {
                        id,
                        snapshot,
                        disposition: StartupDisposition::classify(snapshot),
                    }
                })
                .collect(),
        })
    }

    /// Starts exactly the root and its transitive required dependencies in DAG order.
    /// Preflights the entire closure before side effects: only Registered or
    /// Running+Ready is accepted. Running without Ready returns DependencyNotReady
    /// (including the root); other states return InvalidTransition. Unknown roots
    /// return UnknownPlugin. Unrelated states do not participate.
    /// Running+Ready nodes are no-ops, without authorization, callbacks, or events;
    /// their retained health snapshots are not new authentication or health probes.
    /// Each new initialize/start/readiness callback requires fresh authorization.
    /// Callback failures roll back only resources acquired during this call, in
    /// reverse DAG order with normal dependency guards. Independent eligible
    /// cleanup continues after failures; cleanup errors remain queryable while
    /// the original startup error is returned. Authorization and other noncallback
    /// errors leave partial progress untouched for explicit scoped/fleet cleanup.
    /// No implicit resume, restart, recovery, or business retry is provided.
    pub fn start_with_dependencies(
        &mut self,
        id: &PluginId,
        authorizer: &mut impl PluginAuthorizer,
    ) -> Result<(), PluginError> {
        let order = self.startup_selection(id)?;
        self.startup_preflight(&order)?;
        let mut acquired = Vec::new();
        for id in order {
            if self.entries[&id].status.state == PluginState::Running {
                continue;
            }
            let result = self.initialize(&id, authorizer);
            // invoke marks ownership before entering even a failing initialize.
            if self.entries[&id].status.cleanup_pending {
                acquired.push(id.clone());
            }
            let result = result.and_then(|()| self.start(&id, authorizer));
            if let Err(error) = result {
                if matches!(error, PluginError::Callback(..)) {
                    for acquired_id in acquired.iter().rev() {
                        if self.entries[acquired_id].status.cleanup_pending
                            && self.cleanup_blocker(acquired_id).is_none()
                        {
                            let _ = self.stop(acquired_id);
                        }
                    }
                }
                return Err(error);
            }
        }
        Ok(())
    }

    fn startup_selection(&self, id: &PluginId) -> Result<Vec<PluginId>, PluginError> {
        if !self.entries.contains_key(id) {
            return Err(PluginError::UnknownPlugin(id.clone()));
        }
        let mut selected = BTreeSet::from([id.clone()]);
        for candidate in self.order.iter().rev() {
            if selected.contains(candidate) {
                selected.extend(
                    self.entries[candidate]
                        .registration
                        .descriptor
                        .dependencies
                        .iter()
                        .cloned(),
                );
            }
        }
        Ok(self
            .order
            .iter()
            .filter(|id| selected.contains(*id))
            .cloned()
            .collect())
    }

    fn startup_preflight(&self, order: &[PluginId]) -> Result<(), PluginError> {
        for id in order {
            let snapshot = PluginSnapshot::from(&self.entries[id].status);
            match StartupDisposition::classify(snapshot) {
                StartupDisposition::Start | StartupDisposition::AlreadyRunning => {}
                StartupDisposition::NotReady => {
                    return Err(PluginError::DependencyNotReady(id.clone()));
                }
                StartupDisposition::InvalidState => {
                    return Err(PluginError::InvalidTransition(id.clone(), snapshot.state));
                }
            }
        }
        Ok(())
    }

    /// Cleans up one plugin without authorization, even after revocation.
    /// Unknown IDs return `UnknownPlugin`; no pending cleanup is a no-op, including
    /// never-initialized Registered plugins (which remain Registered).
    /// A direct dependent with pending cleanup blocks before callbacks or events;
    /// the lexicographically first dependent ID is returned in `DependencyInUse`.
    /// There is no cascade. Cleanup failures remain pending for explicit retry;
    /// successful retry clears the cleanup error but retains the first failure.
    pub fn stop(&mut self, id: &PluginId) -> Result<(), PluginError> {
        let entry = self
            .entries
            .get(id)
            .ok_or_else(|| PluginError::UnknownPlugin(id.clone()))?;
        if !entry.status.cleanup_pending {
            return Ok(());
        }
        if let Some(dependent) = self.cleanup_blocker(id) {
            return Err(PluginError::DependencyInUse(dependent.clone()));
        }
        self.invoke(id, PluginAction::Stop)
    }

    /// Explicitly cleans up the root and all transitive dependents in the immutable
    /// descriptor graph, never its dependencies or unrelated plugins. Traversal
    /// includes never-initialized and already-cleaned intermediary nodes.
    /// Unknown roots fail without side effects. No authorization is required,
    /// even after revocation. Eligible cleanup runs in reverse topological order;
    /// blocked dependencies and nodes without pending cleanup are silently skipped.
    /// Independent branches continue after errors/panics; the first callback error
    /// is returned. Failed cleanup retains dependencies until explicit retry.
    pub fn stop_with_dependents(&mut self, id: &PluginId) -> Result<(), PluginError> {
        let mut first_error = None;
        for id in self.shutdown_selection(ShutdownScope::WithDependents(id.clone()))? {
            if !self.entries[&id].status.cleanup_pending || self.cleanup_blocker(&id).is_some() {
                continue;
            }
            if let Err(error) = self.invoke(&id, PluginAction::Stop) {
                first_error.get_or_insert(error);
            }
        }
        first_error.map_or(Ok(()), Err)
    }

    fn dependent_closure(&self, id: &PluginId) -> Result<BTreeSet<PluginId>, PluginError> {
        if !self.entries.contains_key(id) {
            return Err(PluginError::UnknownPlugin(id.clone()));
        }
        let mut closure = BTreeSet::from([id.clone()]);
        for candidate in &self.order {
            if self.entries[candidate]
                .registration
                .descriptor
                .dependencies
                .iter()
                .any(|dependency| closure.contains(dependency))
            {
                closure.insert(candidate.clone());
            }
        }
        Ok(closure)
    }

    fn cleanup_blocker<'a>(&'a self, id: &'a PluginId) -> Option<&'a PluginId> {
        self.cleanup_blockers(id).next()
    }

    fn cleanup_blockers<'a>(&'a self, id: &'a PluginId) -> impl Iterator<Item = &'a PluginId> {
        self.entries.iter().filter_map(move |(dependent, entry)| {
            (entry.status.cleanup_pending
                && entry.registration.descriptor.dependencies.contains(id))
            .then_some(dependent)
        })
    }

    /// Always available without authorization, even after revocation. Attempts
    /// every eligible cleanup; errors remain queryable per plugin. A dependency
    /// is retained while any dependent's cleanup is pending.
    pub fn stop_all(&mut self) -> Result<(), PluginError> {
        let mut first_error = None;
        for id in self.order.clone().into_iter().rev() {
            if self.cleanup_blocker(&id).is_some() || !self.entries[&id].status.cleanup_pending {
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
            // Only an ongoing probe may report false without failing lifecycle.
            // Startup/resume readiness still fails closed from Starting.
            Ok(Ok(false))
                if action == PluginAction::Readiness && previous.state == PluginState::Running =>
            {
                entry.status.health = PluginHealth::NotReady;
                self.record(
                    id,
                    PluginEventKind::Callback(action),
                    previous,
                    PluginOutcome::NotReady,
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
    fn inventory_diamond_is_deterministic_and_relations_are_only_direct() {
        let mut expected = None;
        for rotation in 0..4 {
            for reverse in [false, true] {
                let mut registrations = vec![
                    registration("a", &[]),
                    registration("b", &["a"]),
                    registration("c", &["a"]),
                    registration("root", if reverse { &["c", "b"] } else { &["b", "c"] }),
                ];
                registrations.rotate_left(rotation);
                if reverse {
                    registrations.reverse();
                }
                let manager = PluginManager::new(registrations).expect("diamond");
                let inventory = manager.inventory();
                let relations: Vec<_> = inventory
                    .entries()
                    .iter()
                    .map(|entry| {
                        (
                            entry.id.as_str(),
                            entry
                                .dependencies
                                .iter()
                                .map(PluginId::as_str)
                                .collect::<Vec<_>>(),
                            entry
                                .dependents
                                .iter()
                                .map(PluginId::as_str)
                                .collect::<Vec<_>>(),
                        )
                    })
                    .collect();
                assert_eq!(
                    relations,
                    [
                        ("a", vec![], vec!["b", "c"]),
                        ("b", vec!["a"], vec!["root"]),
                        ("c", vec!["a"], vec!["root"]),
                        ("root", vec!["b", "c"], vec![]),
                    ]
                );
                assert!(inventory.entries().iter().all(|entry| {
                    entry.snapshot.state == PluginState::Registered
                        && !entry.snapshot.cleanup_pending
                }));
                if let Some(expected) = &expected {
                    assert_eq!(&inventory, expected);
                } else {
                    expected = Some(inventory);
                }
            }
        }
    }

    #[test]
    fn inventory_accepts_every_state_and_redacts_retained_failures() {
        let mut manager = PluginManager::new(vec![registration("a", &[])]).expect("manager");
        let id = PluginId::new("a").expect("ID");
        let initial = manager.inventory();
        for state in [
            PluginState::Registered,
            PluginState::Initialized,
            PluginState::Starting,
            PluginState::Running,
            PluginState::Paused,
            PluginState::Stopped,
            PluginState::Failed,
        ] {
            for pending in [false, true] {
                let status = &mut manager.entries.get_mut(&id).expect("entry").status;
                status.state = state;
                status.cleanup_pending = pending;
                status.failure = Some(PluginFailure {
                    action: PluginAction::Readiness,
                    message: "arbitrary-private-panic-payload".into(),
                    panicked: true,
                });
                status.cleanup_error = Some(PluginFailure {
                    action: PluginAction::Stop,
                    message: "arbitrary-private-error".into(),
                    panicked: false,
                });
                let snapshot = PluginSnapshot::from(&*status);
                let inventory = manager.inventory();
                assert_eq!(inventory.entries().len(), 1);
                assert_eq!(inventory.entries()[0].snapshot, snapshot);
                let rendered = format!("{inventory:?}");
                for excluded in ["arbitrary-private", "test-evidence"] {
                    assert!(!rendered.contains(excluded));
                }
            }
        }
        assert_eq!(initial.entries()[0].snapshot.state, PluginState::Registered);
        assert!(!initial.entries()[0].snapshot.failed);
    }

    #[test]
    fn inventory_preserves_queue_counters_status_and_sequence_even_after_drain() {
        for capacity in [0, 1, 8] {
            for empty in [false, true] {
                let mut manager = PluginManager::with_event_capacity(
                    if empty {
                        vec![]
                    } else {
                        vec![registration("a", &[]), registration("b", &[])]
                    },
                    capacity,
                )
                .expect("manager");
                let emitted = if empty { 0 } else { 2 };
                for drained in [false, true] {
                    if drained {
                        manager.drain_events().for_each(drop);
                    }
                    let events = manager.events.clone();
                    let statuses: Vec<_> = manager
                        .entries
                        .values()
                        .map(|entry| entry.status.clone())
                        .collect();
                    let first = manager.inventory();
                    let counters = first.event_buffer();
                    assert_eq!(counters.capacity(), capacity);
                    assert_eq!(
                        counters.queued(),
                        if drained { 0 } else { capacity.min(emitted) }
                    );
                    assert_eq!(counters.last_sequence(), emitted as u64);
                    assert_eq!(
                        counters.lost_events(),
                        emitted.saturating_sub(capacity) as u64
                    );
                    for _ in 0..3 {
                        assert_eq!(manager.inventory(), first);
                    }
                    assert_eq!(manager.events, events);
                    assert_eq!(manager.sequence, counters.last_sequence());
                    assert_eq!(manager.lost_events, counters.lost_events());
                    assert_eq!(
                        manager
                            .entries
                            .values()
                            .map(|entry| entry.status.clone())
                            .collect::<Vec<_>>(),
                        statuses
                    );
                }
                if !empty {
                    let mut deny =
                        |_: &PluginDescriptor, _: PluginAction| Err("private denial".into());
                    assert!(
                        manager
                            .initialize(&PluginId::new("a").expect("ID"), &mut deny)
                            .is_err()
                    );
                    let inventory = manager.inventory();
                    assert_eq!(inventory.event_buffer().last_sequence(), 3);
                    assert_eq!(inventory.event_buffer().queued(), capacity.min(1));
                    assert_eq!(
                        inventory.event_buffer().lost_events(),
                        2_usize.saturating_sub(capacity) as u64 + u64::from(capacity == 0)
                    );
                }
            }
        }
    }

    #[test]
    fn startup_preview_preserves_observations_even_with_zero_or_full_event_queue() {
        let root = PluginId::new("root").expect("ID");
        let missing = PluginId::new("missing").expect("ID");
        for capacity in [0, 1, 2, 8] {
            let mut manager = PluginManager::with_event_capacity(
                vec![registration("root", &["a"]), registration("a", &[])],
                capacity,
            )
            .expect("valid graph");
            let statuses: Vec<_> = manager
                .order()
                .iter()
                .map(|id| manager.status(id).cloned())
                .collect();
            let events = manager.events.clone();
            let sequence = manager.sequence;
            let loss = manager.lost_events();
            let first = manager.plan_startup(&root).expect("preview");
            for _ in 0..3 {
                assert_eq!(manager.plan_startup(&root), Ok(first.clone()));
                assert_eq!(
                    manager.plan_startup(&missing),
                    Err(PluginError::UnknownPlugin(missing.clone()))
                );
            }
            assert_eq!(manager.events, events);
            assert_eq!(manager.sequence, sequence);
            assert_eq!(manager.lost_events(), loss);
            assert_eq!(
                manager
                    .order()
                    .iter()
                    .map(|id| manager.status(id).cloned())
                    .collect::<Vec<_>>(),
                statuses
            );
            // The next real event retains the original sequence, even at capacity zero.
            let mut deny = |_: &PluginDescriptor, _: PluginAction| Err("denied".into());
            assert!(matches!(
                manager.initialize(&root, &mut deny),
                Err(PluginError::Authorization(..))
            ));
            assert_eq!(manager.sequence, sequence + 1);
        }
    }

    #[test]
    fn startup_preview_classifies_every_retained_running_health_without_probing() {
        let a = PluginId::new("a").expect("ID");
        let root = PluginId::new("root").expect("ID");
        let mut manager =
            PluginManager::new(vec![registration("a", &[]), registration("root", &["a"])])
                .expect("valid graph");
        for health in [
            PluginHealth::Unknown,
            PluginHealth::Ready,
            PluginHealth::NotReady,
            PluginHealth::Unhealthy,
        ] {
            let status = &mut manager.entries.get_mut(&a).expect("entry").status;
            status.state = PluginState::Running;
            status.health = health;
            let preview = manager.plan_startup(&root).expect("preview");
            assert_eq!(preview.steps()[0].snapshot.health, health);
            assert_eq!(
                preview.steps()[0].disposition,
                if health == PluginHealth::Ready {
                    StartupDisposition::AlreadyRunning
                } else {
                    StartupDisposition::NotReady
                }
            );
            assert_eq!(preview.steps()[1].disposition, StartupDisposition::Start);
            assert_eq!(preview.can_start(), health == PluginHealth::Ready);
            assert_eq!(
                manager.startup_preflight(&manager.startup_selection(&root).expect("selection")),
                if health == PluginHealth::Ready {
                    Ok(())
                } else {
                    Err(PluginError::DependencyNotReady(a.clone()))
                }
            );
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
