#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Local inspection entry point, not an execution host or authorization provider.

use std::{env, process::ExitCode};

const HELP: &str = "\
PALACO runtime inspection
Usage: palaco-runtime [status | --help]

status   Show this binary's capabilities (default).
--help   Show this help.

This command does not start services, authenticate evidence, grant authority,
execute RuntimePlans, or report the health of NEO, AETHER or BASTION.";

fn main() -> ExitCode {
    let mut args = env::args_os().skip(1);
    let command = args.next();
    if args.next().is_some() {
        eprintln!("Expected at most one command. Use --help.");
        return ExitCode::from(2);
    }
    match command.as_deref().and_then(|value| value.to_str()) {
        None if command.is_none() => status(),
        Some("status") => status(),
        Some("--help" | "-h") => {
            println!("{HELP}");
            ExitCode::SUCCESS
        }
        _ => {
            eprintln!("Unknown command. Use status or --help.");
            ExitCode::from(2)
        }
    }
}

fn status() -> ExitCode {
    println!("PALACO runtime {}", env!("CARGO_PKG_VERSION"));
    println!("mode=local-inspection");
    println!("execution_host=unavailable");
    println!("authority_provider=unavailable");
    println!("service_health=not-checked");
    println!("external_effects=disabled");
    println!("production_readiness=not-assessed");
    ExitCode::SUCCESS
}
