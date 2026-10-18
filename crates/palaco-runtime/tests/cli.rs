use std::process::{Command, Output};

fn run(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
        .args(args)
        .output()
        .expect("runtime CLI must launch")
}

#[test]
fn cli_and_embedded_reports_are_identical() -> std::io::Result<()> {
    let mut text = Vec::new();
    let mut json = Vec::new();
    palaco_runtime::inspection::write_status(&mut text)?;
    palaco_runtime::inspection::write_status_json(&mut json)?;
    assert_eq!(run(&["status"]).stdout, text);
    assert_eq!(run(&["status", "--json"]).stdout, json);
    Ok(())
}

#[test]
fn default_and_status_report_only_local_inspection() {
    let default = run(&[]);
    let status = run(&["status"]);
    assert!(default.status.success());
    assert!(status.status.success());
    assert_eq!(default.stdout, status.stdout);
    assert!(default.stderr.is_empty());
    assert!(status.stderr.is_empty());
    let text = String::from_utf8(status.stdout).expect("UTF-8 output");
    assert!(text.starts_with(concat!("PALACO runtime ", env!("CARGO_PKG_VERSION"), "\n")));
    for line in [
        "mode=local-inspection",
        "execution_host=unavailable",
        "authority_provider=unavailable",
        "service_health=not-checked",
        "external_effects=disabled",
        "production_readiness=not-assessed",
    ] {
        assert!(text.lines().any(|value| value == line), "{line}");
    }
}

#[test]
fn json_status_is_a_single_versioned_report_with_the_same_boundaries() {
    let output = run(&["status", "--json"]);
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let text = String::from_utf8(output.stdout).expect("UTF-8 JSON");
    assert_eq!(
        text,
        concat!(
            "{\"schema_version\":1,\"runtime_version\":\"",
            env!("CARGO_PKG_VERSION"),
            "\",\"mode\":\"local-inspection\",",
            "\"execution_host\":\"unavailable\",",
            "\"authority_provider\":\"unavailable\",",
            "\"service_health\":\"not-checked\",",
            "\"external_effects\":\"disabled\",",
            "\"production_readiness\":\"not-assessed\"}\n"
        )
    );
    let plain = String::from_utf8(run(&["status"]).stdout).expect("UTF-8 status");
    for field in text.trim().trim_matches(['{', '}']).split(',').skip(2) {
        let (key, value) = field.split_once(':').expect("key/value");
        assert!(plain.lines().any(|line| {
            line == format!("{}={}", key.trim_matches('"'), value.trim_matches('"'))
        }));
    }
}

#[test]
fn help_explains_boundaries_without_reporting_service_health() {
    for flag in ["--help", "-h"] {
        let output = run(&[flag]);
        assert!(output.status.success());
        assert!(output.stderr.is_empty());
        let text = String::from_utf8(output.stdout).expect("UTF-8 help");
        assert!(text.contains("Usage: palaco-runtime"));
        assert!(text.contains("does not start services"));
        assert!(text.contains("execute RuntimePlans"));
    }
}

#[test]
fn unsupported_commands_and_extra_arguments_fail_without_status_output() {
    for args in [
        vec!["execute"],
        vec!["--authorize"],
        vec!["--production"],
        vec![""],
        vec!["status", "extra"],
        vec!["--help", "extra"],
        vec!["--json"],
        vec!["--help", "--json"],
        vec!["--json", "status"],
        vec!["status", "--JSON"],
        vec!["status", "--json", "extra"],
        vec!["status", "--json", "--json"],
    ] {
        let output = run(&args);
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert!(!output.stderr.is_empty());
    }
}

#[cfg(unix)]
#[test]
fn non_utf8_command_is_rejected() {
    use std::{ffi::OsString, os::unix::ffi::OsStringExt};

    let output = Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
        .arg(OsString::from_vec(vec![0xff]))
        .output()
        .expect("runtime CLI must launch");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    let output = Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
        .arg("status")
        .arg(OsString::from_vec(vec![0xff]))
        .output()
        .expect("runtime CLI must launch");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
}

#[cfg(unix)]
#[test]
fn closed_output_pipe_returns_one_without_panic() {
    use std::{os::fd::OwnedFd, os::unix::net::UnixStream, process::Stdio};

    for args in [
        vec![],
        vec!["status"],
        vec!["status", "--json"],
        vec!["--help"],
    ] {
        let (writer, reader) = UnixStream::pair().expect("socket pair");
        drop(reader);
        let output = Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
            .args(args)
            .stdout(Stdio::from(OwnedFd::from(writer)))
            .output()
            .expect("runtime CLI must launch");
        assert_eq!(output.status.code(), Some(1));
        assert_eq!(output.stderr, b"Runtime output could not be written.\n");
    }
}

#[cfg(target_os = "linux")]
#[test]
fn full_output_device_returns_one_without_panic() {
    for args in [vec!["status"], vec!["status", "--json"], vec!["--help"]] {
        let full = std::fs::OpenOptions::new()
            .write(true)
            .open("/dev/full")
            .expect("Linux full device");
        let output = Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
            .args(args)
            .stdout(full)
            .output()
            .expect("runtime CLI must launch");
        assert_eq!(output.status.code(), Some(1));
        assert_eq!(output.stderr, b"Runtime output could not be written.\n");
    }
}

#[cfg(unix)]
#[test]
fn unavailable_stderr_preserves_argument_error_exit_code() {
    use std::{os::fd::OwnedFd, os::unix::net::UnixStream, process::Stdio};

    for args in [vec!["execute"], vec!["status", "extra"]] {
        let (writer, reader) = UnixStream::pair().expect("socket pair");
        drop(reader);
        let output = Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
            .args(args)
            .stderr(Stdio::from(OwnedFd::from(writer)))
            .output()
            .expect("runtime CLI must launch");
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
    }
}
