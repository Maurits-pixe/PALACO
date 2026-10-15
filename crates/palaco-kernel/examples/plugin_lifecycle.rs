use std::error::Error;

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginId,
        PluginManager, PluginRegistration, ShutdownScope,
    },
};

struct TrustedPlugin;

impl Plugin for TrustedPlugin {
    fn initialize(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        Ok(())
    }

    fn start(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        Ok(())
    }

    fn readiness(&mut self, _: &PluginContext<'_>) -> Result<bool, String> {
        Ok(true)
    }

    fn pause(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        Ok(())
    }

    fn resume(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        Ok(())
    }

    fn stop(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        Ok(())
    }
}

// Synthetic demonstration only: this does NOT authenticate plugins or implement
// production host policy. Real hosts must evaluate current authority per action.
fn synthetic_authorizer(_: &PluginDescriptor, _: PluginAction) -> Result<RuntimePlan, String> {
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(
            EventEnvelope::new(
                "demo.lifecycle",
                EvidenceRef::new("demo-host-evidence").map_err(|error| error.to_string())?,
            ),
            AuthorityState::Authorized,
        ),
    )))
}

fn registration(
    name: &str,
    dependencies: Vec<PluginId>,
) -> Result<PluginRegistration, Box<dyn Error>> {
    Ok(PluginRegistration {
        descriptor: PluginDescriptor {
            id: PluginId::new(name)?,
            contract_version: CONTRACT_VERSION,
            dependencies,
            evidence: EvidenceRef::new("demo-plugin-evidence")?,
        },
        plugin: Box::new(TrustedPlugin),
    })
}

fn print_inventory(manager: &PluginManager) {
    let inventory = manager.inventory();
    for entry in inventory.entries() {
        println!(
            "inventory {}: {:?}, retained health {:?}, pending {}, failed {}, cleanup failed {}, dependencies {}, dependents {}",
            entry.id.as_str(),
            entry.snapshot.state,
            entry.snapshot.health,
            entry.snapshot.cleanup_pending,
            entry.snapshot.failed,
            entry.snapshot.cleanup_failed,
            entry.dependencies.len(),
            entry.dependents.len(),
        );
    }
    let buffer = inventory.event_buffer();
    println!(
        "inventory events: capacity {}, queued {}, last local sequence {}, lost {}",
        buffer.capacity(),
        buffer.queued(),
        buffer.last_sequence(),
        buffer.lost_events(),
    );
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut manager = PluginManager::new(vec![
        registration("worker", vec![PluginId::new("service")?])?,
        registration("service", vec![])?,
        registration("independent", vec![])?,
    ])?;
    let service = PluginId::new("service")?;
    let worker = PluginId::new("worker")?;
    let independent = PluginId::new("independent")?;
    print_inventory(&manager);
    let mut scoped_complete = true;
    let lifecycle = manager
        .plan_startup(&worker)
        .map_err(Box::<dyn Error>::from)
        .and_then(|preview| {
            for step in preview.steps() {
                println!("startup {}: {:?}", step.id.as_str(), step.disposition);
            }
            println!("startup can_start: {}", preview.can_start());
            if !preview.can_start() {
                return Err("startup scope failed local preflight".into());
            }
            // Recompute live preflight and authorize each action, not the preview.
            Ok(manager.start_with_dependencies(&worker, &mut synthetic_authorizer)?)
        })
        .and_then(
            |()| Ok(manager.start_with_dependencies(&independent, &mut synthetic_authorizer)?),
        )
        // A host chooses when to probe; these are direct, non-transitive snapshots.
        .and_then(|()| {
            let report = manager.check_health_report(&mut synthetic_authorizer)?;
            for entry in report.entries() {
                println!("{} health: {:?}", entry.id.as_str(), entry.outcome);
            }
            println!(
                "health probes complete: {}, all ready: {}",
                report.complete(),
                report.all_ready()
            );
            if !report.complete() || !report.all_ready() {
                return Err("health probes incomplete or fleet not fully ready".into());
            }
            Ok(())
        })
        .and_then(|()| Ok(manager.pause_all(&mut synthetic_authorizer)?))
        .and_then(|()| Ok(manager.resume_all(&mut synthetic_authorizer)?))
        .and_then(|()| {
            manager
                .check_health(&service, &mut synthetic_authorizer)
                .map(|_| ())
                .map_err(Box::<dyn Error>::from)
        })
        // Explicit opt-in cascade stops worker before service, not the whole fleet.
        // In contrast, stop(&service) alone would reject while worker owns resources.
        .and_then(|()| {
            for step in manager.plan_shutdown(ShutdownScope::WithDependents(service.clone()))? {
                println!(
                    "shutdown {}: current blockers {:?}",
                    step.id.as_str(),
                    step.blockers
                );
            }
            let report =
                manager.execute_shutdown(ShutdownScope::WithDependents(service.clone()))?;
            for entry in report.entries() {
                println!(
                    "executed shutdown {}: {:?}, live blockers {:?}",
                    entry.id.as_str(),
                    entry.outcome,
                    entry.blockers
                );
            }
            scoped_complete = report.complete();
            println!("scoped cleanup complete: {scoped_complete} (not whole-fleet shutdown)");
            if !scoped_complete {
                eprintln!("scoped cleanup incomplete; retain ownership and explicitly retry");
            }
            Ok(())
        })
        .and_then(|()| {
            let health = manager.check_health(&independent, &mut synthetic_authorizer)?;
            println!("independent retained after scoped shutdown: {health:?}");
            Ok(())
        });
    print_inventory(&manager);
    // Never short-circuit cleanup on an operational failure. A real host must
    // retain the manager and explicitly retry if cleanup itself fails.
    let cleanup = manager.stop_all();
    print_inventory(&manager);
    for event in manager.drain_events() {
        println!(
            "{} {} {:?}: {:?}",
            event.sequence,
            event.id.as_str(),
            event.kind,
            event.outcome
        );
    }
    if cleanup.is_err() {
        eprintln!("cleanup failed; production hosts must retain ownership and retry cleanup");
    }
    lifecycle?;
    cleanup?;
    if !scoped_complete {
        return Err("scoped shutdown was incomplete; final fleet cleanup was attempted".into());
    }
    Ok(())
}
