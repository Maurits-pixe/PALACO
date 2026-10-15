//! Trusted child-process adapter; address-space/crash isolation, NOT a sandbox.
//!
//! The host supplies an absolute executable and explicit arguments (no shell).
//! Environment is cleared, stderr discarded. Commands are ASCII lines
//! `<sequence> INIT|START|READY|PAUSE|RESUME|STOP\n`; replies are
//! `<same-sequence> OK|READY|NOT_READY|ERROR\n`. Only READY accepts READY/NOT_READY;
//! other commands accept OK. ERROR always fails. Lines are at most 64 bytes,
//! including newline; no logs, unsolicited replies, CRLF, or extra fields.
//! PAUSE/RESUME are cooperative plugin operations, not OS process suspension.
//!
//! One I/O worker and bounded one-slot channels per adapter keep blocked pipe I/O
//! off the lifecycle thread. Deadlines cover writes and reads together. Any error
//! terminates/reaps the direct child; stop also does so after a successful STOP.
//! Failed cleanup retains child ownership for retry. Drop attempts bounded cleanup.
//! No process-tree isolation: grandchildren may survive and inherit pipes. We
//! deliberately never join the worker, because inherited pipes can keep it blocked
//! after the direct child dies. Such descendants can retain that one worker until
//! they close the pipes. Use trusted cooperative executables and host OS supervision
//! when process-tree/resource guarantees are required. Filesystem/network access
//! is unrestricted; protocol data/identity is not authority.

use std::{
    ffi::OsString,
    io::{Read, Write},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::mpsc::{self, Receiver, SyncSender},
    thread,
    time::{Duration, Instant},
};

use super::{Plugin, PluginContext};

pub mod server;

const MAX_LINE: usize = 64;

/// Immutable process launch settings. No inherited environment or env opt-in.
pub struct ProcessPluginConfig {
    pub executable: PathBuf,
    pub args: Vec<OsString>,
    /// Per-command and per-reap deadline, strictly positive and <= 60 seconds.
    pub timeout: Duration,
}

struct Request {
    sequence: u64,
    command: &'static str,
}

/// Owns at most one child/worker; spawning occurs only in `initialize`.
pub struct ProcessPlugin {
    config: ProcessPluginConfig,
    child: Option<Child>,
    requests: Option<SyncSender<Request>>,
    replies: Option<Receiver<Result<String, &'static str>>>,
    sequence: u64,
    initialized: bool,
}

impl ProcessPlugin {
    pub fn new(config: ProcessPluginConfig) -> Result<Self, String> {
        if !config.executable.is_absolute()
            || config.timeout.is_zero()
            || config.timeout > Duration::from_secs(60)
        {
            return Err("absolute executable and timeout in (0, 60s] required".into());
        }
        Ok(Self {
            config,
            child: None,
            requests: None,
            replies: None,
            sequence: 0,
            initialized: false,
        })
    }

    /// OS identifier for supervision/diagnostics, not an authentication identity.
    pub fn child_id(&self) -> Option<u32> {
        self.child.as_ref().map(Child::id)
    }

    fn spawn(&mut self) -> Result<(), String> {
        if self.initialized {
            return Err("process initialization is single-use".into());
        }
        self.initialized = true;
        let child = Command::new(&self.config.executable)
            .args(&self.config.args)
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "process spawn failed")?;
        self.child = Some(child);
        let child = self.child.as_mut().expect("spawned child");
        let mut stdin = child.stdin.take().ok_or("missing process stdin")?;
        let mut stdout = child.stdout.take().ok_or("missing process stdout")?;
        let (request_tx, request_rx) = mpsc::sync_channel::<Request>(1);
        let (reply_tx, reply_rx) = mpsc::sync_channel(1);
        thread::Builder::new()
            .name("palaco-plugin-io".into())
            .spawn(move || {
                while let Ok(request) = request_rx.recv() {
                    let result = (|| {
                        writeln!(stdin, "{} {}", request.sequence, request.command)
                            .and_then(|()| stdin.flush())
                            .map_err(|_| "process write failed")?;
                        let mut bytes = Vec::with_capacity(MAX_LINE);
                        loop {
                            let mut byte = [0];
                            if stdout.read(&mut byte).map_err(|_| "process read failed")? == 0 {
                                return Err("process EOF");
                            }
                            bytes.push(byte[0]);
                            if bytes.len() > MAX_LINE {
                                return Err("process reply oversized");
                            }
                            if byte[0] == b'\n' {
                                break;
                            }
                        }
                        let line =
                            std::str::from_utf8(&bytes).map_err(|_| "invalid process reply")?;
                        let prefix = format!("{} ", request.sequence);
                        let reply = line
                            .strip_prefix(&prefix)
                            .and_then(|line| line.strip_suffix('\n'))
                            .ok_or("uncorrelated process reply")?;
                        if !matches!(reply, "OK" | "READY" | "NOT_READY" | "ERROR") {
                            return Err("invalid process reply");
                        }
                        Ok(reply.to_owned())
                    })();
                    let failed = result.is_err();
                    if reply_tx.try_send(result).is_err() || failed {
                        break;
                    }
                }
            })
            .map_err(|_| "process worker spawn failed")?;
        self.requests = Some(request_tx);
        self.replies = Some(reply_rx);
        Ok(())
    }

    fn exchange(&mut self, command: &'static str) -> Result<bool, String> {
        let result = self.exchange_inner(command);
        if result.is_err() {
            // Preserve the protocol error; the manager keeps cleanup pending and
            // stop retries reaping if termination was unsuccessful.
            let _ = self.terminate();
        }
        result
    }

    fn exchange_inner(&mut self, command: &'static str) -> Result<bool, String> {
        let deadline = Instant::now() + self.config.timeout;
        let child = self.child.as_mut().ok_or("process not running")?;
        if child
            .try_wait()
            .map_err(|_| "process status failed")?
            .is_some()
        {
            return Err("process exited".into());
        }
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or("process sequence exhausted")?;
        self.requests
            .as_ref()
            .ok_or("process worker unavailable")?
            .try_send(Request {
                sequence: self.sequence,
                command,
            })
            .map_err(|_| "process worker unavailable")?;
        let reply = self
            .replies
            .as_ref()
            .ok_or("process worker unavailable")?
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .map_err(|_| "process reply deadline/disconnection")?
            .map_err(str::to_owned)?;
        match (command, reply.as_str()) {
            ("READY", "READY") => Ok(true),
            ("READY", "NOT_READY") => Ok(false),
            (_, "OK") if command != "READY" => Ok(true),
            (_, "ERROR") => Err("process reported ERROR".into()),
            _ => Err("unexpected process reply".into()),
        }
    }

    fn terminate(&mut self) -> Result<(), String> {
        self.requests = None;
        self.replies = None;
        let Some(child) = self.child.as_mut() else {
            return Ok(());
        };
        let deadline = Instant::now() + self.config.timeout;
        if matches!(child.try_wait(), Ok(Some(_))) {
            self.child = None;
            return Ok(());
        }
        // A concurrent exit can make kill fail; try_wait remains authoritative.
        let _ = child.kill();
        loop {
            match child.try_wait() {
                Ok(Some(_)) => {
                    self.child = None;
                    return Ok(());
                }
                Err(_) => return Err("process reap failed".into()),
                Ok(None) => {}
            }
            if Instant::now() >= deadline {
                return Err("process reap deadline exceeded".into());
            }
            thread::sleep(
                Duration::from_millis(1).min(deadline.saturating_duration_since(Instant::now())),
            );
        }
    }
}

impl Plugin for ProcessPlugin {
    fn initialize(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        if let Err(error) = self.spawn() {
            let _ = self.terminate();
            return Err(error);
        }
        self.exchange("INIT").map(|_| ())
    }

    fn start(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        self.exchange("START").map(|_| ())
    }

    fn readiness(&mut self, _: &PluginContext<'_>) -> Result<bool, String> {
        self.exchange("READY")
    }

    fn pause(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        self.exchange("PAUSE").map(|_| ())
    }

    fn resume(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        self.exchange("RESUME").map(|_| ())
    }

    fn stop(&mut self, _: &PluginContext<'_>) -> Result<(), String> {
        if let Some(child) = self.child.as_mut()
            && matches!(child.try_wait(), Ok(Some(_)))
        {
            // Already-exited children have no remaining cleanup obligation.
            // Original lifecycle errors are retained separately by the manager.
            return self.terminate();
        }
        let protocol = if self.child.is_some() && self.requests.is_some() {
            self.exchange_inner("STOP").map(|_| ())
        } else {
            Ok(())
        };
        let cleanup = self.terminate();
        cleanup.and(protocol)
    }
}

impl Drop for ProcessPlugin {
    fn drop(&mut self) {
        let _ = self.terminate();
    }
}
