use super::*;
use crate::plugin::{CONTRACT_VERSION, PluginId};
use palaco_foundation::EvidenceRef;
use std::{cell::Cell, rc::Rc};

const COMMANDS: [&str; 6] = ["INIT", "START", "READY", "PAUSE", "RESUME", "STOP"];
const ACTIONS: [PluginAction; 6] = [
    PluginAction::Initialize,
    PluginAction::Start,
    PluginAction::Readiness,
    PluginAction::Pause,
    PluginAction::Resume,
    PluginAction::Stop,
];

#[derive(Default)]
struct Probe {
    calls: Vec<PluginAction>,
    fault: Option<(PluginAction, bool)>,
    stop_fault: bool,
    probes: usize,
    cleanup_after_error: Option<Rc<Cell<bool>>>,
}

impl Probe {
    fn call(&mut self, action: PluginAction, context: &PluginContext<'_>) -> Result<(), String> {
        assert_eq!(context.id.as_str(), "local");
        assert_eq!(context.evidence.as_str(), "local-evidence");
        self.calls.push(action);
        if action == PluginAction::Stop
            && let Some(error_flushed) = &self.cleanup_after_error
        {
            assert!(error_flushed.get(), "ERROR must be flushed before cleanup");
        }
        if self.fault == Some((action, true)) {
            panic!("private-panic-payload");
        }
        if self.fault == Some((action, false)) || (action == PluginAction::Stop && self.stop_fault)
        {
            return Err("private-callback-details".into());
        }
        Ok(())
    }
}

impl Plugin for Probe {
    fn initialize(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(PluginAction::Initialize, context)
    }
    fn start(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(PluginAction::Start, context)
    }
    fn readiness(&mut self, context: &PluginContext<'_>) -> Result<bool, String> {
        self.call(PluginAction::Readiness, context)?;
        self.probes += 1;
        Ok(self.probes != 2)
    }
    fn pause(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(PluginAction::Pause, context)
    }
    fn resume(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(PluginAction::Resume, context)
    }
    fn stop(&mut self, context: &PluginContext<'_>) -> Result<(), String> {
        self.call(PluginAction::Stop, context)
    }
}

fn descriptor() -> PluginDescriptor {
    PluginDescriptor {
        id: PluginId::new("local").expect("valid local ID"),
        evidence: EvidenceRef::new("local-evidence").expect("valid local evidence"),
        contract_version: CONTRACT_VERSION,
        dependencies: vec![],
    }
}

fn wire(commands: &[&str]) -> Vec<u8> {
    commands
        .iter()
        .enumerate()
        .map(|(index, command)| format!("{} {command}\n", index + 1))
        .collect::<String>()
        .into_bytes()
}

fn run(probe: &mut Probe, input: &[u8]) -> (Result<(), ServeError>, String) {
    let mut output = Vec::new();
    let result = serve(probe, &descriptor(), input, &mut output);
    (result, String::from_utf8(output).expect("ASCII replies"))
}

#[test]
fn golden_lifecycle_and_recoverable_readiness() {
    let mut probe = Probe::default();
    let (result, output) = run(
        &mut probe,
        &wire(&[
            "INIT", "START", "READY", "READY", "READY", "PAUSE", "RESUME", "READY", "STOP",
        ]),
    );
    assert_eq!(result, Ok(()));
    assert_eq!(
        output,
        "1 OK\n2 OK\n3 READY\n4 NOT_READY\n5 READY\n6 OK\n7 OK\n8 READY\n9 OK\n"
    );
    assert_eq!(probe.calls.len(), 9);
}

#[test]
fn strict_protocol_never_dispatches_bad_input() {
    use ServeErrorKind::*;
    let cases: Vec<(Vec<u8>, ServeErrorKind)> = vec![
        (b"".to_vec(), UnexpectedEof),
        (b"1 INIT".to_vec(), Truncated),
        (b"1 INIT\r\n".to_vec(), Malformed),
        (b"1 INIT extra\n".to_vec(), Malformed),
        (b"1  INIT\n".to_vec(), Malformed),
        (b"1 INIT \n".to_vec(), Malformed),
        (b"1\tINIT\n".to_vec(), Malformed),
        (b"1 init\n".to_vec(), Malformed),
        (b"1 UNKNOWN\n".to_vec(), Malformed),
        (b"01 INIT\n".to_vec(), Malformed),
        (b"0 INIT\n".to_vec(), Malformed),
        (b"+1 INIT\n".to_vec(), Malformed),
        (b"-1 INIT\n".to_vec(), Malformed),
        (b"1 \xff\n".to_vec(), Malformed),
        (b"2 INIT\n".to_vec(), Sequence),
        (b"18446744073709551616 INIT\n".to_vec(), Sequence),
        ([vec![b'x'; 63], vec![b'\n']].concat(), Malformed),
        ([vec![b'x'; 64], vec![b'\n']].concat(), Oversized),
        (vec![b'x'; 65], Oversized),
    ];
    for (input, kind) in cases {
        let mut probe = Probe::default();
        let (result, output) = run(&mut probe, &input);
        assert_eq!(
            result,
            Err(ServeError {
                kind,
                cleanup_failed: false
            })
        );
        assert!(probe.calls.is_empty(), "{input:?}");
        assert!(output.is_empty());
    }
    for suffix in ["1 START\n", "3 START\n", "2 START", "2 READY\r\n"] {
        let mut probe = Probe::default();
        let input = format!("1 INIT\n{suffix}");
        let (result, output) = run(&mut probe, input.as_bytes());
        assert!(result.is_err());
        assert_eq!(output, "1 OK\n");
        assert_eq!(probe.calls, [PluginAction::Initialize, PluginAction::Stop]);
    }
}

#[test]
fn invalid_transitions_reply_error_without_operational_dispatch() {
    for (prefix, rejected) in [
        (vec![], "STOP"),
        (vec![], "START"),
        (vec![], "READY"),
        (vec![], "PAUSE"),
        (vec![], "RESUME"),
        (vec!["INIT"], "INIT"),
        (vec!["INIT"], "READY"),
        (vec!["INIT"], "PAUSE"),
        (vec!["INIT"], "RESUME"),
        (vec!["INIT", "START"], "START"),
        (vec!["INIT", "START"], "RESUME"),
        (vec!["INIT", "START", "PAUSE"], "PAUSE"),
        (vec!["INIT", "START", "PAUSE"], "READY"),
        (vec!["INIT", "START", "PAUSE"], "START"),
    ] {
        let mut probe = Probe::default();
        let mut commands = prefix.clone();
        commands.push(rejected);
        let (result, output) = run(&mut probe, &wire(&commands));
        assert_eq!(
            result.expect_err("invalid transition").kind,
            ServeErrorKind::InvalidTransition
        );
        assert!(output.ends_with(&format!("{} ERROR\n", commands.len())));
        let mut expected = ACTIONS[..prefix.len()].to_vec();
        // This prefix uses PAUSE rather than READY as its third callback.
        if expected.len() == 3 {
            expected[2] = PluginAction::Pause;
        }
        if !prefix.is_empty() {
            expected.push(PluginAction::Stop);
        }
        assert_eq!(probe.calls, expected);
    }
    for commands in [vec!["INIT", "STOP"], vec!["INIT", "START", "PAUSE", "STOP"]] {
        assert_eq!(run(&mut Probe::default(), &wire(&commands)).0, Ok(()));
    }
}

#[test]
fn all_callback_errors_and_panics_are_redacted_and_cleanup_is_once() {
    for (index, action) in ACTIONS.into_iter().enumerate() {
        for panics in [false, true] {
            for cleanup_fault in [false, true] {
                let mut probe = Probe {
                    fault: Some((action, panics)),
                    stop_fault: cleanup_fault,
                    ..Probe::default()
                };
                let (result, output) = run(&mut probe, &wire(&COMMANDS));
                let error = result.expect_err("callback fault");
                assert_eq!(
                    error.kind,
                    if panics {
                        ServeErrorKind::CallbackPanicked(action)
                    } else {
                        ServeErrorKind::CallbackFailed(action)
                    }
                );
                assert_eq!(
                    error.cleanup_failed,
                    action == PluginAction::Stop || cleanup_fault
                );
                assert_eq!(
                    probe
                        .calls
                        .iter()
                        .filter(|&&a| a == PluginAction::Stop)
                        .count(),
                    1
                );
                assert_eq!(probe.calls.len(), (index + 2).min(6));
                assert!(output.ends_with(&format!("{} ERROR\n", index + 1)));
                for text in [output, error.to_string(), format!("{error:?}")] {
                    assert!(!text.contains("private"));
                }
            }
        }
    }
}

struct FaultWriter {
    bytes: Vec<u8>,
    fail_after: usize,
    flush_failure: bool,
}

impl Write for FaultWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.bytes.len() >= self.fail_after {
            return Err(io::Error::other("private-write-details"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        if self.flush_failure && self.bytes.len() >= self.fail_after {
            Err(io::Error::other("private-flush-details"))
        } else {
            Ok(())
        }
    }
}

#[test]
fn eof_and_io_failures_cleanup_once_even_after_successful_stop() {
    for commands in [&COMMANDS[..1], &COMMANDS[..2], &COMMANDS[..5]] {
        let mut probe = Probe::default();
        assert_eq!(
            run(&mut probe, &wire(commands)).0.expect_err("EOF").kind,
            ServeErrorKind::UnexpectedEof
        );
        assert_eq!(probe.calls.last(), Some(&PluginAction::Stop));
        assert_eq!(probe.calls.len(), commands.len() + 1);
    }
    for flush_failure in [false, true] {
        for fail_after in [0, 5, 10] {
            let mut writer = FaultWriter {
                bytes: vec![],
                fail_after,
                flush_failure,
            };
            let mut probe = Probe::default();
            let result = serve(
                &mut probe,
                &descriptor(),
                &wire(&["INIT", "STOP"])[..],
                &mut writer,
            );
            // Two five-byte replies: write failure at 10 is never reached.
            if !flush_failure && fail_after == 10 {
                assert_eq!(result, Ok(()));
            } else {
                assert_eq!(
                    result.expect_err("writer failure").kind,
                    ServeErrorKind::Write
                );
            }
            assert_eq!(probe.calls, [PluginAction::Initialize, PluginAction::Stop]);
        }
    }
}

struct FaultReader {
    input: io::Cursor<Vec<u8>>,
}

impl Read for FaultReader {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if self.input.position() as usize == self.input.get_ref().len() {
            Err(io::Error::other("private-read-details"))
        } else {
            self.input.read(bytes)
        }
    }
}

#[test]
fn read_failure_and_cleanup_failure_preserve_primary_kind() {
    for initialized in [false, true] {
        let mut probe = Probe {
            stop_fault: true,
            ..Probe::default()
        };
        let reader = FaultReader {
            input: io::Cursor::new(if initialized { wire(&["INIT"]) } else { vec![] }),
        };
        let error =
            serve(&mut probe, &descriptor(), reader, Vec::new()).expect_err("reader failure");
        assert_eq!(error.kind, ServeErrorKind::Read);
        assert_eq!(error.cleanup_failed, initialized);
        assert_eq!(probe.calls.len(), if initialized { 2 } else { 0 });
    }
}

#[test]
fn bounded_reads_and_sequence_exhaustion_fail_without_dispatch() {
    let mut reader = io::Cursor::new(vec![b'x'; 1024]);
    assert_eq!(
        read_request(&mut reader, Some(1)),
        Err(ServeErrorKind::Oversized)
    );
    assert_eq!(reader.position(), MAX_LINE as u64);
    assert_eq!(
        read_request(&mut &b"18446744073709551615 INIT\n"[..], Some(u64::MAX)),
        Ok((u64::MAX, PluginAction::Initialize))
    );
    assert_eq!(
        read_request(&mut &b"1 STOP\n"[..], None),
        Err(ServeErrorKind::Sequence)
    );
}

#[test]
fn protocol_and_error_reply_failures_retain_primary_error_and_cleanup_status() {
    for stop_fault in [false, true] {
        let mut probe = Probe {
            stop_fault,
            ..Probe::default()
        };
        let (result, output) = run(&mut probe, b"1 INIT\n2 START\r\n");
        assert_eq!(
            result,
            Err(ServeError {
                kind: ServeErrorKind::Malformed,
                cleanup_failed: stop_fault,
            })
        );
        assert_eq!(output, "1 OK\n");
        assert_eq!(probe.calls, [PluginAction::Initialize, PluginAction::Stop]);

        let mut probe = Probe {
            fault: Some((PluginAction::Initialize, false)),
            stop_fault,
            ..Probe::default()
        };
        let writer = FaultWriter {
            bytes: vec![],
            fail_after: 0,
            flush_failure: false,
        };
        assert_eq!(
            serve(&mut probe, &descriptor(), &b"1 INIT\n"[..], writer),
            Err(ServeError {
                kind: ServeErrorKind::CallbackFailed(PluginAction::Initialize),
                cleanup_failed: stop_fault,
            })
        );
        assert_eq!(probe.calls, [PluginAction::Initialize, PluginAction::Stop]);
    }
}

#[test]
fn interrupted_read_is_retried_without_consuming_sequence() {
    struct InterruptedOnce<'a>(bool, &'a [u8]);
    impl Read for InterruptedOnce<'_> {
        fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
            if !self.0 {
                self.0 = true;
                Err(io::ErrorKind::Interrupted.into())
            } else {
                self.1.read(bytes)
            }
        }
    }
    let mut probe = Probe::default();
    assert_eq!(
        serve(
            &mut probe,
            &descriptor(),
            InterruptedOnce(false, b"1 INIT\n2 STOP\n"),
            Vec::new()
        ),
        Ok(())
    );
    assert_eq!(probe.calls, [PluginAction::Initialize, PluginAction::Stop]);
}

#[test]
fn callback_error_is_flushed_before_cleanup_can_block() {
    struct ErrorObserver {
        bytes: Vec<u8>,
        error_flushed: Rc<Cell<bool>>,
    }
    impl Write for ErrorObserver {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.bytes.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            if self.bytes.ends_with(b"ERROR\n") {
                self.error_flushed.set(true);
            }
            Ok(())
        }
    }
    for panics in [false, true] {
        let error_flushed = Rc::new(Cell::new(false));
        let mut probe = Probe {
            fault: Some((PluginAction::Initialize, panics)),
            cleanup_after_error: Some(error_flushed.clone()),
            ..Probe::default()
        };
        let mut writer = ErrorObserver {
            bytes: vec![],
            error_flushed,
        };
        let error = serve(&mut probe, &descriptor(), &b"1 INIT\n"[..], &mut writer)
            .expect_err("initialization fault");
        assert!(
            !error.cleanup_failed,
            "cleanup must observe a flushed ERROR"
        );
        assert_eq!(writer.bytes, b"1 ERROR\n");
        assert_eq!(probe.calls, [PluginAction::Initialize, PluginAction::Stop]);
    }
}
