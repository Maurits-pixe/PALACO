//! One executable acts as host or trusted child, with no external resources.
use std::{error::Error, time::Duration};

use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_foundation::{AuthorityState, EvidenceRef};
use palaco_quay::ProvenanceRecord;
use palaco_runtime::{
    RuntimePlan,
    plugin::{
        CONTRACT_VERSION, Plugin, PluginAction, PluginContext, PluginDescriptor, PluginId,
        PluginManager, PluginRegistration, ShutdownScope,
        process::{ProcessPlugin, ProcessPluginConfig, server},
    },
};

#[derive(Default)]
struct MemoryWorker {
    queue: Option<Vec<u64>>,
    active: bool,
    completed: usize,
}

impl Plugin for MemoryWorker {
    fn initialize(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        if self.queue.is_some() {
            return Err("worker already initialized".into());
        }
        self.queue = Some(Vec::new());
        Ok(())
    }

    fn start(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        let queue = self.queue.as_mut().ok_or("worker not initialized")?;
        if self.active {
            return Err("worker already active".into());
        }
        queue.extend([1, 2, 3]);
        self.active = true;
        Ok(())
    }

    fn readiness(&mut self, _: &PluginContext<'_>) -> Result<bool, String> {
        Ok(self.active && self.queue.is_some())
    }

    fn pause(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        if !self.active {
            return Err("worker not active".into());
        }
        let queue = self.queue.as_mut().ok_or("worker not initialized")?;
        self.completed += queue.len();
        queue.clear();
        self.active = false;
        Ok(())
    }

    fn resume(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        if self.completed == 0 {
            return Err("worker has not quiesced".into());
        }
        self.start(context)
    }

    fn stop(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        self.active = false;
        self.queue = None;
        Ok(())
    }
}

fn descriptor() -> Result<PluginDescriptor, Box<dyn Error>> {
    Ok(PluginDescriptor {
        id: PluginId::new("memory-worker")?,
        contract_version: CONTRACT_VERSION,
        dependencies: vec![],
        evidence: EvidenceRef::new("local-demo-evidence")?,
    })
}

// Synthetic policy, not authentication or a production authorization decision.
fn synthetic_authorizer(_: &PluginDescriptor, _: PluginAction) -> Result<RuntimePlan, String> {
    Ok(RuntimePlan::new(ExecutionBoundary::new(
        ProvenanceRecord::new(
            EventEnvelope::new(
                "demo.process",
                EvidenceRef::new("synthetic-host-evidence").map_err(|error| error.to_string())?,
            ),
            AuthorityState::Authorized,
        ),
    )))
}

fn main() -> Result<(), Box<dyn Error>> {
    let descriptor = descriptor()?;
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("--child")) {
        // Local metadata only: no identity or authority arrives over this wire.
        server::serve_stdio(&mut MemoryWorker::default(), &descriptor)?;
        return Ok(());
    }

    let mut manager = PluginManager::new(vec![PluginRegistration {
        descriptor,
        plugin: Box::new(ProcessPlugin::new(ProcessPluginConfig {
            executable: std::env::current_exe()?,
            args: vec!["--child".into()],
            timeout: Duration::from_secs(2),
        })?),
    }])?;
    let lifecycle = (|| -> Result<(), Box<dyn Error>> {
        manager.start_all(&mut synthetic_authorizer)?;
        for round in 0..2 {
            let report = manager.check_health_report(&mut synthetic_authorizer)?;
            println!(
                "health {round}: complete={}, all_ready={}",
                report.complete(),
                report.all_ready()
            );
            if !report.complete() || !report.all_ready() {
                return Err("child health report incomplete or not ready".into());
            }
            if round == 0 {
                manager.pause_all(&mut synthetic_authorizer)?;
                manager.resume_all(&mut synthetic_authorizer)?;
                println!("child paused and resumed");
            }
        }
        Ok(())
    })();
    // Always attempt cleanup, including after partial or failed startup.
    let cleanup = manager.execute_shutdown(ShutdownScope::All);
    if let Ok(report) = &cleanup {
        for entry in report.entries() {
            println!("shutdown {}: {:?}", entry.id.as_str(), entry.outcome);
        }
        println!("cleanup complete={}", report.complete());
    }
    lifecycle?;
    if !cleanup?.complete() {
        return Err("cleanup incomplete; production hosts must retain ownership and retry".into());
    }
    Ok(())
}
