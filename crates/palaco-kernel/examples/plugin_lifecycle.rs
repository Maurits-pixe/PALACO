use std::error::Error;

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginId,
        PluginManager, PluginRegistration,
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

fn main() -> Result<(), Box<dyn Error>> {
    let mut manager = PluginManager::new(vec![
        registration("worker", vec![PluginId::new("service")?])?,
        registration("service", vec![])?,
    ])?;
    let lifecycle = manager
        .start_all(&mut synthetic_authorizer)
        // A host chooses when to probe; these are direct, non-transitive snapshots.
        .and_then(|()| {
            for (id, health) in manager.check_health_all(&mut synthetic_authorizer)? {
                println!("{} health: {health:?}", id.as_str());
            }
            Ok(())
        })
        .and_then(|()| manager.pause_all(&mut synthetic_authorizer))
        .and_then(|()| manager.resume_all(&mut synthetic_authorizer))
        .and_then(|()| {
            manager
                .check_health(&PluginId::new("service")?, &mut synthetic_authorizer)
                .map(|_| ())
        });
    // Never short-circuit cleanup on an operational failure. A real host must
    // retain the manager and explicitly retry if cleanup itself fails.
    let cleanup = manager.stop_all();
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
    Ok(())
}
