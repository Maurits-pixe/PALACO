#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Local inspection entry point, not an execution host or authorization provider.

use std::{env, process::ExitCode};

const HELP: &str = "\
PALACO runtime inspection
Usage: palaco-runtime [status [--json] | --help]

status   Show this binary's capabilities (default).
--json   With status only: emit the versioned JSON report.
--help   Show this help.

This command does not start services, authenticate evidence, grant authority,
execute RuntimePlans, or report the health of NEO, AETHER or BASTION.";

fn main() -> ExitCode {
    let mut args = env::args_os().skip(1);
    let command = args.next();
    let format = args.next();
    if args.next().is_some()
        || format.is_some()
            && !(command.as_deref() == Some(std::ffi::OsStr::new("status"))
                && format.as_deref() == Some(std::ffi::OsStr::new("--json")))
    {
        eprintln!("Unsupported arguments. Use --help.");
        return ExitCode::from(2);
    }
    if format.is_some() {
        return json_status();
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

fn json_status() -> ExitCode {
    println!(
        concat!(
            "{{\"schema_version\":1,\"runtime_version\":\"{}\",",
            "\"mode\":\"local-inspection\",",
            "\"execution_host\":\"unavailable\",",
            "\"authority_provider\":\"unavailable\",",
            "\"service_health\":\"not-checked\",",
            "\"external_effects\":\"disabled\",",
            "\"production_readiness\":\"not-assessed\"}}"
        ),
        env!("CARGO_PKG_VERSION")
    );
    ExitCode::SUCCESS
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
