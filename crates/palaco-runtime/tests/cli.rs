use std::process::{Command, Output};

fn run(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_palaco-runtime"))
        .args(args)
        .output()
        .expect("runtime CLI must launch")
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
}
