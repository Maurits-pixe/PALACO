#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Local inspection entry point, not an execution host or authorization provider.

use palaco_runtime::inspection::{status, write_status, write_status_json};
use std::{
    env,
    io::{self, Write},
    process::ExitCode,
};

const HELP: &str = "\
PALACO runtime inspection
Usage: palaco-runtime [status [--json] | --help | --version]

status   Show this binary's capabilities (default).
--json   With status only: emit the versioned JSON report.
--help, -h      Show this help.
--version, -V   Show the package version only, not service health or readiness.

This command does not start services, authenticate evidence, grant authority,
execute RuntimePlans, or report the health of NEO, AETHER or BASTION.";

fn main() -> ExitCode {
    let mut stdout = io::stdout().lock();
    match run(&mut stdout) {
        Ok(code) => code,
        Err(_) => {
            let _ = writeln!(io::stderr().lock(), "Runtime output could not be written.");
            ExitCode::from(1)
        }
    }
}

fn run(output: &mut impl Write) -> io::Result<ExitCode> {
    let mut args = env::args_os().skip(1);
    let command = args.next();
    let format = args.next();
    if args.next().is_some()
        || format.is_some()
            && !(command.as_deref() == Some(std::ffi::OsStr::new("status"))
                && format.as_deref() == Some(std::ffi::OsStr::new("--json")))
    {
        let _ = writeln!(io::stderr().lock(), "Unsupported arguments. Use --help.");
        return Ok(ExitCode::from(2));
    }
    if format.is_some() {
        write_status_json(output)?;
        output.flush()?;
        return Ok(ExitCode::SUCCESS);
    }
    match command.as_deref().and_then(|value| value.to_str()) {
        None if command.is_none() => write_status(output)?,
        Some("status") => write_status(output)?,
        Some("--help" | "-h") => {
            writeln!(output, "{HELP}")?;
        }
        Some("--version" | "-V") => {
            writeln!(output, "PALACO runtime {}", status().runtime_version)?;
        }
        _ => {
            let _ = writeln!(
                io::stderr().lock(),
                "Unknown command. Use status or --help."
            );
            return Ok(ExitCode::from(2));
        }
    }
    output.flush()?;
    Ok(ExitCode::SUCCESS)
}
