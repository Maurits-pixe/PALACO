#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

//! Local inspection entry point, not an execution host or authorization provider.

use palaco_runtime::inspection::{status, write_status, write_status_json};
use std::{
    env,
    ffi::OsString,
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
    let mut stderr = io::stderr().lock();
    match run(env::args_os().skip(1), &mut stdout, &mut stderr) {
        Ok(code) => code,
        Err(_) => {
            let _ = writeln!(stderr, "Runtime output could not be written.");
            ExitCode::from(1)
        }
    }
}

fn run(
    mut args: impl Iterator<Item = OsString>,
    output: &mut impl Write,
    errors: &mut impl Write,
) -> io::Result<ExitCode> {
    let command = args.next();
    let format = args.next();
    if args.next().is_some()
        || format.is_some()
            && !(command.as_deref() == Some(std::ffi::OsStr::new("status"))
                && format.as_deref() == Some(std::ffi::OsStr::new("--json")))
    {
        let _ = writeln!(errors, "Unsupported arguments. Use --help.");
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
            let _ = writeln!(errors, "Unknown command. Use status or --help.");
            return Ok(ExitCode::from(2));
        }
    }
    output.flush()?;
    Ok(ExitCode::SUCCESS)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::BufWriter;

    const COMMANDS: &[&[&str]] = &[
        &[],
        &["status"],
        &["status", "--json"],
        &["--help"],
        &["-h"],
        &["--version"],
        &["-V"],
    ];

    #[derive(Default)]
    struct Destination {
        bytes: Vec<u8>,
        flushes: usize,
        fail_write: bool,
        fail_flush: bool,
    }

    impl Write for Destination {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.fail_write {
                return Err(io::ErrorKind::BrokenPipe.into());
            }
            self.bytes.extend_from_slice(bytes);
            Ok(bytes.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            self.flushes += 1;
            if self.fail_flush {
                return Err(io::ErrorKind::PermissionDenied.into());
            }
            Ok(())
        }
    }

    #[test]
    fn successful_commands_flush_buffered_output_before_success() -> io::Result<()> {
        for command in COMMANDS {
            let mut output = BufWriter::with_capacity(4096, Destination::default());
            let mut errors = Vec::new();
            let code = run(command.iter().map(OsString::from), &mut output, &mut errors)?;
            assert_eq!(code, ExitCode::SUCCESS);
            assert!(output.buffer().is_empty());
            assert!(!output.get_ref().bytes.is_empty());
            assert_eq!(output.get_ref().flushes, 1);
            assert!(errors.is_empty());
        }
        Ok(())
    }

    #[test]
    fn flush_failures_propagate_even_after_all_bytes_are_written() {
        for command in COMMANDS {
            let mut output = BufWriter::with_capacity(
                4096,
                Destination {
                    fail_flush: true,
                    ..Destination::default()
                },
            );
            let mut errors = Vec::new();
            let error = run(command.iter().map(OsString::from), &mut output, &mut errors)
                .expect_err("flush failure must prevent success");
            assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
            assert!(output.buffer().is_empty());
            assert!(!output.get_ref().bytes.is_empty());
            assert_eq!(output.get_ref().flushes, 1);
            assert!(errors.is_empty());
        }
    }

    #[test]
    fn writes_accepted_by_buffer_can_still_fail_during_flush() {
        for command in COMMANDS {
            let mut output = BufWriter::with_capacity(
                4096,
                Destination {
                    fail_write: true,
                    ..Destination::default()
                },
            );
            let mut errors = Vec::new();
            let error = run(command.iter().map(OsString::from), &mut output, &mut errors)
                .expect_err("buffered write failure must prevent success");
            assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
            assert!(!output.buffer().is_empty());
            assert!(output.get_ref().bytes.is_empty());
            assert_eq!(output.get_ref().flushes, 0);
            assert!(errors.is_empty());
            let _ = output.into_parts();
        }
    }

    #[test]
    fn invalid_arguments_neither_write_nor_flush_stdout() -> io::Result<()> {
        for command in [
            &["execute"][..],
            &["status", "extra"][..],
            &["--version", "--json"][..],
            &["status", "--json", "extra"][..],
        ] {
            let mut output = Destination {
                fail_write: true,
                fail_flush: true,
                ..Destination::default()
            };
            let mut errors = Destination {
                fail_write: true,
                fail_flush: true,
                ..Destination::default()
            };
            let code = run(command.iter().map(OsString::from), &mut output, &mut errors)?;
            assert_eq!(code, ExitCode::from(2));
            assert!(output.bytes.is_empty());
            assert_eq!(output.flushes, 0);
            assert_eq!(errors.flushes, 0);
        }
        Ok(())
    }
}
