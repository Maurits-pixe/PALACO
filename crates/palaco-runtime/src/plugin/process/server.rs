//! Child-side server for trusted [`Plugin`] implementations.
//!
//! The locally supplied descriptor is callback metadata, not host authentication:
//! the wire carries neither identity nor authority. Host `PluginManager` gates
//! operations. Reserve stdout exclusively for this protocol; logging belongs on
//! stderr. Unwinding callback panics are caught, but the standard panic hook can
//! still write to stderr. Aborting panics cannot be caught.
//!
//! Callbacks are synchronous with no child-side deadline. The host adapter owns
//! deadlines and kills/reaps the direct child on failure; this is not a sandbox.

use std::{
    error::Error,
    fmt,
    io::{self, Read, Write},
    panic::{AssertUnwindSafe, catch_unwind},
};

use super::{
    super::{Plugin, PluginAction, PluginContext, PluginDescriptor},
    MAX_LINE,
};

/// Sanitized primary failure, never arbitrary input or callback error text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServeErrorKind {
    Read,
    Write,
    UnexpectedEof,
    Truncated,
    Oversized,
    Malformed,
    Sequence,
    InvalidTransition,
    CallbackFailed(PluginAction),
    CallbackPanicked(PluginAction),
}

/// The primary failure plus whether the single cleanup attempt failed.
/// `cleanup_failed` means resources may still be owned; the host must terminate
/// the child. This server never automatically retries a failed stop callback.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ServeError {
    pub kind: ServeErrorKind,
    pub cleanup_failed: bool,
}

impl fmt::Display for ServeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "plugin server {:?}; cleanup failed: {}",
            self.kind, self.cleanup_failed
        )
    }
}

impl Error for ServeError {}

#[derive(Clone, Copy)]
enum State {
    New,
    Initialized,
    Active,
    Paused,
}

fn read_request(
    reader: &mut impl Read,
    expected: Option<u64>,
) -> Result<(u64, PluginAction), ServeErrorKind> {
    let mut bytes = [0; MAX_LINE];
    let mut length = 0;
    loop {
        if length == MAX_LINE {
            return Err(ServeErrorKind::Oversized);
        }
        match reader.read(&mut bytes[length..length + 1]) {
            Ok(0) => {
                return Err(if length == 0 {
                    ServeErrorKind::UnexpectedEof
                } else {
                    ServeErrorKind::Truncated
                });
            }
            Ok(_) => {
                length += 1;
                if bytes[length - 1] == b'\n' {
                    break;
                }
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(ServeErrorKind::Read),
        }
    }
    let line = std::str::from_utf8(&bytes[..length - 1]).map_err(|_| ServeErrorKind::Malformed)?;
    let (sequence, command) = line.split_once(' ').ok_or(ServeErrorKind::Malformed)?;
    if sequence.is_empty()
        || sequence.starts_with('0')
        || !sequence.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(ServeErrorKind::Malformed);
    }
    let sequence: u64 = sequence.parse().map_err(|_| ServeErrorKind::Sequence)?;
    if Some(sequence) != expected {
        return Err(ServeErrorKind::Sequence);
    }
    let action = match command {
        "INIT" => PluginAction::Initialize,
        "START" => PluginAction::Start,
        "READY" => PluginAction::Readiness,
        "PAUSE" => PluginAction::Pause,
        "RESUME" => PluginAction::Resume,
        "STOP" => PluginAction::Stop,
        _ => return Err(ServeErrorKind::Malformed),
    };
    Ok((sequence, action))
}

fn callback<T>(
    action: PluginAction,
    call: impl FnOnce() -> Result<T, String>,
) -> Result<T, ServeErrorKind> {
    match catch_unwind(AssertUnwindSafe(call)) {
        Ok(Ok(value)) => Ok(value),
        Ok(Err(_)) => Err(ServeErrorKind::CallbackFailed(action)),
        Err(_) => Err(ServeErrorKind::CallbackPanicked(action)),
    }
}

fn reply(writer: &mut impl Write, sequence: u64, status: &str) -> Result<(), ServeErrorKind> {
    writeln!(writer, "{sequence} {status}")
        .and_then(|()| writer.flush())
        .map_err(|_| ServeErrorKind::Write)
}

/// Serve exactly one lifecycle until a successful STOP or the first failure.
///
/// Requests are ASCII, LF-only, at most 64 bytes including LF. Sequences start
/// at 1 and are contiguous positive decimal integers without leading zeroes.
/// Malformed requests produce no reply. Valid but invalid-state requests produce
/// correlated ERROR, then terminate. READY may repeatedly return NOT_READY and
/// recover without changing the active state. STOP is allowed after INIT entry.
///
/// Every failure after INIT entry attempts stop once, including partial init,
/// unless STOP itself was already attempted. Primary failures are preserved even
/// if sending ERROR fails. ERROR is flushed before cleanup so the host can
/// observe failure and terminate the child even if cleanup hangs. Cleanup failure
/// is exposed separately; cleanup can be interrupted by host termination.
pub fn serve<P: Plugin + ?Sized>(
    plugin: &mut P,
    descriptor: &PluginDescriptor,
    mut reader: impl Read,
    mut writer: impl Write,
) -> Result<(), ServeError> {
    let context = PluginContext {
        id: &descriptor.id,
        evidence: &descriptor.evidence,
    };
    let mut state = State::New;
    let mut pending = false;
    let mut stop_attempted = false;
    let result = (|| {
        let mut expected = Some(1);
        loop {
            let (sequence, action) = read_request(&mut reader, expected)?;
            expected = sequence.checked_add(1);
            let valid = matches!(
                (state, action),
                (State::New, PluginAction::Initialize)
                    | (State::Initialized, PluginAction::Start)
                    | (State::Active, PluginAction::Readiness | PluginAction::Pause)
                    | (State::Paused, PluginAction::Resume)
            ) || (pending && action == PluginAction::Stop);
            let outcome = if !valid {
                Err(ServeErrorKind::InvalidTransition)
            } else {
                match action {
                    PluginAction::Initialize => {
                        pending = true;
                        callback(action, || plugin.initialize(&context)).map(|()| {
                            state = State::Initialized;
                            "OK"
                        })
                    }
                    PluginAction::Start | PluginAction::Resume => callback(action, || {
                        if action == PluginAction::Start {
                            plugin.start(&context)
                        } else {
                            plugin.resume(&context)
                        }
                    })
                    .map(|()| {
                        state = State::Active;
                        "OK"
                    }),
                    PluginAction::Readiness => callback(action, || plugin.readiness(&context))
                        .map(|ready| if ready { "READY" } else { "NOT_READY" }),
                    PluginAction::Pause => callback(action, || plugin.pause(&context)).map(|()| {
                        state = State::Paused;
                        "OK"
                    }),
                    PluginAction::Stop => {
                        stop_attempted = true;
                        callback(action, || plugin.stop(&context)).map(|()| {
                            pending = false;
                            "OK"
                        })
                    }
                }
            };
            let status = match outcome {
                Ok(status) => status,
                Err(kind) => {
                    let _ = reply(&mut writer, sequence, "ERROR");
                    return Err(kind);
                }
            };
            reply(&mut writer, sequence, status)?;
            if action == PluginAction::Stop {
                return Ok(());
            }
        }
    })();
    let mut cleanup_failed = pending && stop_attempted;
    if pending && !stop_attempted {
        cleanup_failed = callback(PluginAction::Stop, || plugin.stop(&context)).is_err();
    }
    result.map_err(|kind| ServeError {
        kind,
        cleanup_failed,
    })
}

/// Serve on locked stdin/stdout. Do not print anything else to stdout.
pub fn serve_stdio<P: Plugin + ?Sized>(
    plugin: &mut P,
    descriptor: &PluginDescriptor,
) -> Result<(), ServeError> {
    serve(plugin, descriptor, io::stdin().lock(), io::stdout().lock())
}

#[cfg(test)]
mod tests;
