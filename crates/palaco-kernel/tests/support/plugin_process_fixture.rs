//! Opt-in integration-test subprocess, never used for plugin discovery.
use std::{
    io::{self, BufRead, Write},
    time::Duration,
};

fn main() -> io::Result<()> {
    let Some(mode) = std::env::args().nth(1) else {
        return Ok(());
    };
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    let mut readiness_count = 0;
    for line in stdin.lock().lines() {
        let line = line?;
        let Some((sequence, command)) = line.split_once(' ') else {
            return Ok(());
        };
        if command == "INIT" {
            match mode.as_str() {
                "error" => {
                    writeln!(stdout, "{sequence} ERROR")?;
                    stdout.flush()?;
                    continue;
                }
                "eof" => return Ok(()),
                "crash" => std::process::exit(37),
                "hang" => std::thread::sleep(Duration::from_secs(30)),
                "partial" => {
                    write!(stdout, "{sequence} O")?;
                    stdout.flush()?;
                    std::thread::sleep(Duration::from_secs(30));
                }
                "oversize" => {
                    writeln!(stdout, "{}", "X".repeat(128))?;
                    stdout.flush()?;
                    continue;
                }
                "malformed" => {
                    writeln!(stdout, "{sequence} private-secret-details")?;
                    stdout.flush()?;
                    continue;
                }
                "wrong-sequence" => {
                    writeln!(stdout, "999 OK")?;
                    stdout.flush()?;
                    continue;
                }
                _ => {}
            }
        }
        if command == "STOP" {
            match mode.as_str() {
                "stop-hang" => std::thread::sleep(Duration::from_secs(30)),
                "stop-error" => {
                    writeln!(stdout, "{sequence} ERROR")?;
                    stdout.flush()?;
                    continue;
                }
                _ => {}
            }
        }
        if command == "READY" {
            readiness_count += 1;
            if readiness_count > 1 && mode == "probe-hang" {
                std::thread::sleep(Duration::from_secs(30));
            }
        }
        if mode == "stderr" {
            io::stderr().write_all(&vec![b'x'; 128 * 1024])?;
        }
        let reply = if std::env::var_os("CARGO").is_some() {
            "ERROR" // The host environment must not leak into the child.
        } else if command == "READY" {
            match mode.as_str() {
                "not-ready" => "NOT_READY",
                "readiness-error" => "ERROR",
                "health-cycle" if readiness_count == 2 => "NOT_READY",
                "probe-error" if readiness_count > 1 => "ERROR",
                _ => "READY",
            }
        } else if (mode == "start-error" && command == "START")
            || (mode == "pause-error" && command == "PAUSE")
            || (mode == "resume-error" && command == "RESUME")
        {
            "ERROR"
        } else {
            "OK"
        };
        writeln!(stdout, "{sequence} {reply}")?;
        if mode == "extra" && command == "INIT" {
            writeln!(stdout, "{sequence} OK")?;
        }
        stdout.flush()?;
        if mode == "exit-after-init" && command == "INIT" {
            return Ok(());
        }
        if mode == "exit-after-ready" && command == "READY" {
            return Ok(());
        }
        if command == "STOP" {
            return Ok(());
        }
    }
    Ok(())
}
