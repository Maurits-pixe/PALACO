"""Mocked lifecycle/privacy checks; actual TLS is proved separately by the ignored Rust test."""
from __future__ import annotations

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import tls_fixture as fixture

CANARY = "PRIVATE_FIXTURE_CANARY_MUST_NOT_PRINT"


@contextmanager
def local_root():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with (
            mock.patch.object(fixture, "ROOT", root),
            mock.patch.object(fixture, "REPO", root),
            mock.patch.object(fixture, "RUNTIME", root / ".tls-runtime"),
            mock.patch.object(fixture, "COMPOSE", root / "tls-compose.yaml"),
            mock.patch.object(fixture, "MANIFEST", root / "Cargo.toml"),
        ):
            yield root


def fake_commands(
    record: dict, *, cargo_code: int = 0, selected_case: bool = True,
    down_code: int = 0, tamper_marker: bool = False,
    bootstrap_code: int | None = None, bootstrap_selected: bool | None = None,
    bootstrap_case: str | None = None,
    service_code: int | None = None, service_selected: bool | None = None,
    service_case: str | None = None,
    oidc_code: int | None = None, oidc_selected: bool | None = None,
    oidc_case: str | None = None,
    restore_prepare_code: int | None = None, restore_prepare_selected: bool | None = None,
    restore_prepare_case: str | None = None,
    restore_verify_code: int | None = None, restore_verify_selected: bool | None = None,
    restore_verify_case: str | None = None,
    native_tls_code: int = 0, createdb_code: int = 0,
    backup_code: int = 0, restore_code: int = 0,
):
    def execute(arguments, **options):
        record.setdefault("commands", []).append(list(arguments))
        runtime = fixture.RUNTIME
        if runtime.exists():
            assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
            for path in runtime.iterdir():
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if arguments[0] == "cargo":
            selected_test = arguments[arguments.index("--locked") + 1]
            record.setdefault("rustTests", []).append(selected_test)
            metadata = os.fstat(options["stdout"].fileno())
            record.setdefault("rustTestLogs", []).append((metadata.st_dev, metadata.st_ino))
            password = options["env"]["RIO_PG_TLS_PASSWORD"]
            record["password"] = password
            record["test_environment"] = options["env"].copy()
            assert password not in " ".join(arguments)
            assert arguments[-3:] == ["--ignored", "--exact", "--color=never"]
            output = options["stdout"]
            output.write((CANARY + "\n" + password + "\n").encode())
            overrides = {
                fixture.BOOTSTRAP_TEST: (bootstrap_selected, bootstrap_case, bootstrap_code),
                fixture.SERVICE_TEST: (service_selected, service_case, service_code),
                fixture.OIDC_TEST: (oidc_selected, oidc_case, oidc_code),
                fixture.RESTORE_PREPARE_TEST: (
                    restore_prepare_selected, restore_prepare_case, restore_prepare_code,
                ),
                fixture.RESTORE_VERIFY_TEST: (
                    restore_verify_selected, restore_verify_case, restore_verify_code,
                ),
            }
            override_selected, override_case, override_code = overrides.get(selected_test, (None, None, None))
            selected = override_selected if override_selected is not None else selected_case
            case = override_case if override_case is not None else selected_test
            code = override_code if override_code is not None else cargo_code
            if selected:
                output.write(("test " + case + " ... ok\n").encode())
                output.write(b"test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;\n")
            else:
                output.write(b"test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured;\n")
            if tamper_marker:
                (runtime / ".owner.json").write_bytes(b'{"forged":true}\n')
            return SimpleNamespace(returncode=code)
        if arguments[0] == "docker" and "down" in arguments:
            return SimpleNamespace(returncode=down_code)
        if arguments[0] == "docker" and "exec" in arguments:
            native = {
                fixture.NATIVE_TLS_CONTROL_SCRIPT: ("tls", native_tls_code),
                fixture.CREATE_RESTORE_SCRIPT: ("createdb", createdb_code),
                fixture.BACKUP_SCRIPT: ("backup", backup_code),
                fixture.RESTORE_SCRIPT: ("restore", restore_code),
            }.get(arguments[-1])
            if native is not None:
                record.setdefault("nativePhases", []).append(native[0])
                options["stdout"].write((CANARY + "\n").encode())
                return SimpleNamespace(returncode=native[1])
        return SimpleNamespace(returncode=0)
    return execute


@contextmanager
def mock_commands(execute):
    # The orchestration contract fakes Cargo at its new lifecycle boundary.
    # Separate tests exercise that boundary with Popen/waitid/group-signal mocks.
    with (
        mock.patch.object(fixture.subprocess, "run", side_effect=execute) as process,
        mock.patch.object(
            fixture, "_run_owned_rust_process",
            side_effect=lambda arguments, **options: execute(arguments, **options).returncode,
        ),
    ):
        yield process


def run_main() -> tuple[int, str, dict]:
    output = io.StringIO()
    with (
        mock.patch.object(sys, "argv", ["tls_fixture.py", "check"]),
        mock.patch.object(fixture.signal, "signal", return_value=signal.SIG_DFL),
        mock.patch("sys.stdout", output),
    ):
        code = fixture.main()
    text = output.getvalue()
    summary = next(line.removeprefix("RIO_TLS_FIXTURE_SUMMARY ") for line in text.splitlines()
                   if line.startswith("RIO_TLS_FIXTURE_SUMMARY "))
    return code, text, json.loads(summary)


@unittest.skipUnless(
    sys.platform.startswith("linux") and hasattr(os, "O_NOFOLLOW"),
    "The fixture targets Linux CI.",
)
class TlsFixtureTests(unittest.TestCase):
    def assert_closed(self, result):
        self.assertEqual(result["scope"], "LOCAL_SYNTHETIC_TLS_TEST")
        self.assertEqual(result["boundary"], {
            "account1": "HOLD", "personalAccounts": False, "contact": False,
            "operativeAuthority": "NONE", "deployment": "HOLD", "humanAcceptance": "HOLD",
        })

    def assert_private_output(self, output, record, root):
        self.assertNotIn(CANARY, output)
        self.assertNotIn(str(root), output)
        if "password" in record:
            self.assertNotIn(record["password"], output)
        self.assertNotIn("-----BEGIN", output)
        self.assertNotIn("rio-accounts-tls-", output)

    def assert_rust_results(self, result, passed):
        self.assertEqual(result["rustTests"], [
            {"name": test, "passed": test in passed} for test, _log in fixture.TESTS
        ])
        self.assertEqual(result["rustTest"], fixture.TEST)
        self.assertEqual(result["rustTestPassed"], fixture.TEST in passed)
        self.assertEqual(result["rustTestsPassed"], len(passed) == len(fixture.TESTS))

    def test_success_has_private_environment_exact_test_and_owned_cleanup(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record)):
                code, output, result = run_main()
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["rustTestPassed"])
            self.assertEqual(result["schemaVersion"], "RIO_TLS_FIXTURE_EVIDENCE_V2")
            self.assertTrue(result["rustTestsPassed"])
            self.assertEqual(result["rustTests"], [
                {"name": test, "passed": True} for test, _log in fixture.TESTS
            ])
            self.assertEqual(record["rustTests"], [test for test, _log in fixture.TESTS])
            self.assertEqual(len(set(record["rustTestLogs"])), len(fixture.TESTS))
            self.assertEqual(result["backupRestore"], {
                "tlsVerified": True, "restoreDatabaseCreated": True,
                "backupCreated": True, "restored": True,
            })
            for test, _log in fixture.TESTS:
                self.assertIn("RIO_TLS_RUST_TEST " + test + " PASS", output)
            self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)
            environment = record["test_environment"]
            self.assertEqual(len(environment["RIO_PG_TLS_PASSWORD"]), 64)
            self.assertEqual(environment["RIO_PG_TLS_CA_DER"], str(root / ".tls-runtime/ca.der"))
            self.assertEqual(environment["RIO_PG_TLS_OTHER_CA_DER"], str(root / ".tls-runtime/other-ca.der"))
            commands = record["commands"]
            up = next(command for command in commands if command[0] == "docker" and "up" in command)
            down = next(command for command in commands if command[0] == "docker" and "down" in command)
            self.assertEqual(up[up.index("--project-name") + 1], down[down.index("--project-name") + 1])
            self.assertIn("--volumes", down)
            for command in commands:
                if command[0] == "docker" and "exec" in command:
                    if command[-1] == fixture.READY_SCRIPT:
                        self.assertIn("--command=\"SELECT 1\"", command[-1])
                    self.assertNotIn(record["password"], " ".join(command))

    def test_failed_rust_test_never_echoes_private_logs_and_still_cleans(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, cargo_code=1)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertFalse(result["rustTestPassed"])
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)
            self.assertTrue(any("down" in command for command in record["commands"]))

    def test_zero_selected_rust_cases_cannot_be_reported_as_tls_proof(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, selected_case=False)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertFalse(result["rustTestPassed"])
            self.assertNotIn("RIO_TLS_RUST_TEST", output)
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def assert_bootstrap_rejected(self, overrides):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, **overrides)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assert_rust_results(result, {fixture.TEST})
            self.assertEqual(record["rustTests"], [fixture.TEST, fixture.BOOTSTRAP_TEST])
            self.assertEqual(len(set(record["rustTestLogs"])), 2)
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.BOOTSTRAP_TEST + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_bootstrap_failure_cannot_reuse_storage_pass_and_still_cleans(self):
        self.assert_bootstrap_rejected({"bootstrap_code": 1})

    def test_zero_selected_bootstrap_case_cannot_reuse_storage_pass(self):
        self.assert_bootstrap_rejected({"bootstrap_selected": False})

    def test_bootstrap_log_with_only_storage_case_cannot_prove_bootstrap(self):
        self.assert_bootstrap_rejected({"bootstrap_case": fixture.TEST})

    def test_preexisting_bootstrap_log_cannot_be_reused(self):
        with local_root() as root:
            record = {}
            execute = fake_commands(record)
            def stale_bootstrap_log(arguments, **options):
                completed = execute(arguments, **options)
                if arguments[0] == "cargo":
                    (fixture.RUNTIME / "bootstrap-test.log").write_bytes((
                        "test " + fixture.BOOTSTRAP_TEST + " ... ok\n"
                        "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;\n"
                    ).encode())
                return completed
            with mock_commands(stale_bootstrap_log):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assert_rust_results(result, {fixture.TEST})
            self.assertEqual(record["rustTests"], [fixture.TEST])
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.BOOTSTRAP_TEST + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_service_failure_cannot_reuse_earlier_passes_and_still_cleans(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, service_code=1)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assert_rust_results(result, {fixture.TEST, fixture.BOOTSTRAP_TEST})
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.SERVICE_TEST + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_zero_selected_service_case_cannot_reuse_earlier_passes(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, service_selected=False)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assert_rust_results(result, {fixture.TEST, fixture.BOOTSTRAP_TEST})
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.SERVICE_TEST + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_service_log_with_only_storage_case_pass_cannot_prove_service_test(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, service_case=fixture.TEST)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assert_rust_results(result, {fixture.TEST, fixture.BOOTSTRAP_TEST})
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.SERVICE_TEST + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_preexisting_service_log_is_rejected_before_cargo_can_use_stale_pass(self):
        with local_root() as root:
            record = {}
            execute = fake_commands(record)
            def stale_service_log(arguments, **options):
                completed = execute(arguments, **options)
                if arguments[0] == "cargo":
                    (fixture.RUNTIME / "service-test.log").write_bytes((
                        "test " + fixture.SERVICE_TEST + " ... ok\n"
                        "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;\n"
                    ).encode())
                return completed
            with mock_commands(stale_service_log):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assert_rust_results(result, {fixture.TEST, fixture.BOOTSTRAP_TEST})
            self.assertEqual(record["rustTests"], [fixture.TEST, fixture.BOOTSTRAP_TEST])
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.SERVICE_TEST + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_oidc_case_requires_its_own_selected_success_and_cleans_on_failure(self):
        for overrides in (
            {"oidc_code": 1}, {"oidc_selected": False},
            {"oidc_case": fixture.TEST}, {"oidc_case": fixture.BOOTSTRAP_TEST},
            {"oidc_case": fixture.SERVICE_TEST},
        ):
            with self.subTest(overrides=overrides), local_root() as root:
                record = {}
                with mock_commands(fake_commands(record, **overrides)):
                    code, output, result = run_main()
                self.assertEqual(code, 1)
                self.assertEqual(result["error"], "RUST_TEST_FAILED")
                self.assert_rust_results(result, {fixture.TEST, fixture.BOOTSTRAP_TEST, fixture.SERVICE_TEST})
                self.assertEqual(record["rustTests"], [test for test, _log in fixture.BASE_TESTS])
                self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.OIDC_TEST + " PASS", output)
                self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
                self.assertFalse(fixture.RUNTIME.exists())
                self.assert_private_output(output, record, root)
                self.assert_closed(result)

    def test_preexisting_oidc_log_or_browser_summary_cannot_be_reused(self):
        for stale_name in ("oidc-test.log", "oidc-summary.json"):
            with self.subTest(stale_name=stale_name), local_root() as root:
                record = {}
                execute = fake_commands(record)
                def stale_oidc_proof(arguments, **options):
                    completed = execute(arguments, **options)
                    if arguments[0] == "cargo" and arguments[arguments.index("--locked") + 1] == fixture.SERVICE_TEST:
                        (fixture.RUNTIME / stale_name).write_bytes((
                            "test " + fixture.OIDC_TEST + " ... ok\n"
                            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;\n"
                        ).encode())
                    return completed
                with mock_commands(stale_oidc_proof):
                    code, output, result = run_main()
                self.assertEqual(code, 1)
                self.assertEqual(result["error"], "RUST_TEST_FAILED")
                self.assert_rust_results(result, {fixture.TEST, fixture.BOOTSTRAP_TEST, fixture.SERVICE_TEST})
                self.assertEqual(record["rustTests"], [fixture.TEST, fixture.BOOTSTRAP_TEST, fixture.SERVICE_TEST])
                self.assertFalse(fixture.RUNTIME.exists())
                self.assert_private_output(output, record, root)
                self.assert_closed(result)

    def test_native_tls_createdb_prepare_dump_restore_verify_are_ordered(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record)):
                code, output, result = run_main()
            self.assertEqual(code, 0)
            steps = []
            native = {
                fixture.NATIVE_TLS_CONTROL_SCRIPT: "tls",
                fixture.CREATE_RESTORE_SCRIPT: "createdb",
                fixture.BACKUP_SCRIPT: "backup",
                fixture.RESTORE_SCRIPT: "restore",
            }
            for command in record["commands"]:
                if command[0] == "cargo":
                    steps.append(command[command.index("--locked") + 1])
                elif command[-1] in native:
                    self.assertEqual(command[-4:-1], ["postgres_tls", "sh", "-ceu"])
                    steps.append(native[command[-1]])
            self.assertEqual(steps, [
                *[test for test, _log in fixture.BASE_TESTS], "tls", "createdb",
                fixture.RESTORE_PREPARE_TEST, "backup", "restore", fixture.RESTORE_VERIFY_TEST,
            ])
            self.assertTrue(result["rustTestsPassed"])
            self.assert_private_output(output, record, root)

    def test_native_failure_does_not_turn_source_passes_into_restore_proof(self):
        cases = (
            ("native_tls_code", "READINESS_FAILED", [], set(), 4),
            ("createdb_code", "CREATE_RESTORE_FAILED", ["tls"], {"tlsVerified"}, 4),
            ("backup_code", "BACKUP_FAILED", ["tls", "createdb"],
             {"tlsVerified", "restoreDatabaseCreated"}, 5),
            ("restore_code", "RESTORE_FAILED", ["tls", "createdb", "backup"],
             {"tlsVerified", "restoreDatabaseCreated", "backupCreated"}, 5),
        )
        for option, failure, completed, native_passed, rust_count in cases:
            with self.subTest(option=option), local_root() as root:
                record = {}
                with mock_commands(fake_commands(record, **{option: 1})):
                    code, output, result = run_main()
                self.assertEqual(code, 1)
                self.assertEqual(result["error"], failure)
                self.assertEqual(result["status"], "FAIL")
                self.assert_rust_results(result, {test for test, _log in fixture.TESTS[:rust_count]})
                self.assertEqual(
                    {key for key, value in result["backupRestore"].items() if value}, native_passed,
                )
                self.assertEqual(record["nativePhases"][:-1], completed)
                self.assertFalse(fixture.RUNTIME.exists())
                self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
                self.assert_private_output(output, record, root)

    def test_restore_cases_require_their_own_selected_success(self):
        for name, prefix, earlier_count in (
            (fixture.RESTORE_PREPARE_TEST, "restore_prepare", 4),
            (fixture.RESTORE_VERIFY_TEST, "restore_verify", 5),
        ):
            for option, value in (("code", 1), ("selected", False), ("case", fixture.TEST)):
                with self.subTest(case=name, option=option), local_root() as root:
                    record = {}
                    with mock_commands(fake_commands(record, **{prefix + "_" + option: value})):
                        code, output, result = run_main()
                    self.assertEqual(code, 1)
                    self.assertEqual(result["error"], "RUST_TEST_FAILED")
                    self.assert_rust_results(result, {test for test, _log in fixture.TESTS[:earlier_count]})
                    self.assertEqual(record["rustTests"][-1], name)
                    self.assertNotIn("RIO_TLS_RUST_TEST " + name + " PASS", output)
                    self.assertFalse(fixture.RUNTIME.exists())
                    self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
                    self.assert_private_output(output, record, root)

    def test_stale_restore_prepare_or_verify_log_is_rejected_before_invocation(self):
        for index in (4, 5):
            with self.subTest(index=index), local_root() as root:
                record = {}
                execute = fake_commands(record)
                name, log = fixture.TESTS[index]
                previous_name = fixture.TESTS[index - 1][0]
                def stale_restore_log(arguments, **options):
                    completed = execute(arguments, **options)
                    if arguments[0] == "cargo" and arguments[arguments.index("--locked") + 1] == previous_name:
                        (fixture.RUNTIME / log).write_bytes((
                            "test " + name + " ... ok\n"
                            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;\n"
                        ).encode())
                    return completed
                with mock_commands(stale_restore_log):
                    code, output, result = run_main()
                self.assertEqual(code, 1)
                self.assertEqual(result["error"], "RUST_TEST_FAILED")
                self.assert_rust_results(result, {test for test, _log in fixture.TESTS[:index]})
                self.assertNotIn(name, record["rustTests"])
                self.assertFalse(fixture.RUNTIME.exists())
                self.assert_private_output(output, record, root)

    def test_native_timeout_or_cancellation_always_cleans_without_exception_payload(self):
        for error, category in (
            (subprocess.TimeoutExpired(CANARY, 60), "BACKUP_FAILED"),
            (KeyboardInterrupt(CANARY), "CANCELLED"),
        ):
            with self.subTest(category=category), local_root() as root:
                record = {}
                execute = fake_commands(record)
                def interrupted_backup(arguments, **options):
                    if arguments[-1] == fixture.BACKUP_SCRIPT:
                        raise error
                    return execute(arguments, **options)
                with mock_commands(interrupted_backup):
                    code, output, result = run_main()
                self.assertEqual(code, 1)
                self.assertEqual(result["error"], category)
                self.assertFalse(result["backupRestore"]["backupCreated"])
                self.assertFalse(result["backupRestore"]["restored"])
                self.assertFalse(fixture.RUNTIME.exists())
                self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
                self.assert_private_output(output, record, root)

    def test_namespace_cleanup_failure_prevents_overall_pass_but_removes_private_files(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, down_code=1)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertTrue(result["rustTestPassed"])
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["error"], "CLEANUP_FAILED")
            self.assertEqual(result["cleanup"], {"namespaceClosed": False, "privateFilesRemoved": True})
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_existing_runtime_and_unrelated_files_are_never_reused_or_removed(self):
        with local_root() as root:
            fixture.RUNTIME.mkdir()
            unrelated = fixture.RUNTIME / "user-owned.txt"
            unrelated.write_text(CANARY)
            with mock_commands(AssertionError("no process allowed")) as process:
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertFalse(result["createdOwnedFixture"])
            self.assertEqual(result["error"], "PREPARATION_FAILED")
            self.assertEqual(unrelated.read_text(), CANARY)
            process.assert_not_called()
            self.assert_private_output(output, {}, root)
            self.assert_closed(result)

    def test_runtime_symlink_never_targets_or_deletes_another_directory(self):
        with local_root() as root:
            target = root / "other-directory"
            target.mkdir()
            unrelated = target / "user-owned.txt"
            unrelated.write_text(CANARY)
            fixture.RUNTIME.symlink_to(target, target_is_directory=True)
            with mock_commands(AssertionError("no process allowed")) as process:
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertFalse(result["createdOwnedFixture"])
            self.assertEqual(unrelated.read_text(), CANARY)
            self.assertTrue(fixture.RUNTIME.is_symlink())
            process.assert_not_called()
            self.assert_private_output(output, {}, root)
            self.assert_closed(result)

    def test_changed_ownership_marker_blocks_namespace_commands_and_file_deletion(self):
        with local_root() as root:
            record = {}
            with mock_commands(fake_commands(record, tamper_marker=True)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "CLEANUP_FAILED")
            self.assertEqual(result["cleanup"], {"namespaceClosed": False, "privateFilesRemoved": False})
            self.assertTrue((fixture.RUNTIME / "password").exists())
            self.assertFalse(any("down" in command for command in record["commands"]))
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_cancelled_owned_process_is_closed_without_printing_exception_payload(self):
        with local_root() as root:
            record = {}
            execute = fake_commands(record)
            def cancel_test(arguments, **options):
                if arguments[0] == "cargo":
                    raise KeyboardInterrupt(CANARY)
                return execute(arguments, **options)
            with mock_commands(cancel_test):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "CANCELLED")
            self.assertFalse(fixture.RUNTIME.exists())
            self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_inherited_remote_docker_configuration_cannot_change_the_daemon(self):
        with local_root() as root:
            record = {}
            remote = {
                "DOCKER_HOST": "tcp://" + CANARY + ":2376",
                "DOCKER_CONTEXT": CANARY,
                "DOCKER_TLS_VERIFY": "1",
                "DOCKER_CERT_PATH": "/" + CANARY,
            }
            with (
                mock.patch.dict(os.environ, remote),
                mock_commands(fake_commands(record)),
            ):
                code, output, result = run_main()
            self.assertEqual(code, 0)
            for command in record["commands"]:
                if command[0] == "docker":
                    self.assertEqual(command[1:3], ["--host", "unix:///var/run/docker.sock"])
            for key in remote:
                self.assertNotIn(key, record["test_environment"])
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_remaining_owned_resources_prevent_a_cleanup_pass(self):
        with local_root() as root:
            record = {}
            execute = fake_commands(record)
            def leftover(arguments, **options):
                completed = execute(arguments, **options)
                if arguments[0] == "docker" and "volume" in arguments:
                    options["stdout"].write(b"SYNTHETIC_OWNED_VOLUME_REMAINS\n")
                return completed
            with mock_commands(leftover):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "CLEANUP_FAILED")
            self.assertEqual(result["cleanup"], {"namespaceClosed": False, "privateFilesRemoved": True})
            self.assertNotIn("SYNTHETIC_OWNED_VOLUME_REMAINS", output)
            self.assert_private_output(output, record, root)
            self.assert_closed(result)


@unittest.skipUnless(sys.platform.startswith("linux"), "Native archive guards use Linux shell/fd semantics.")
class NativeArchiveScriptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        (self.private / "password").write_text(CANARY)
        (self.private / "password").chmod(0o600)
        self.archive = self.private / "tls-snapshot.dump"
        self.restored = self.private / "restored"
        self.bin = self.root / "bin"
        self.bin.mkdir(mode=0o700)
        self.program("id", "printf '%s\\n' " + str(os.getuid()))
        self.program("pg_dump", "printf 'PGDMP_SYNTHETIC_FIXTURE_PAYLOAD'")
        self.program("pg_restore", (
            "test \"$(cat)\" = PGDMP_SYNTHETIC_FIXTURE_PAYLOAD\n"
            "printf restored > '" + str(self.restored) + "'"
        ))

    def program(self, name, script):
        target = self.bin / name
        target.write_text("#!/bin/sh\nset -eu\n" + script + "\n")
        target.chmod(0o700)

    def execute(self, script):
        # Only tests substitute paths; fixture commands contain fixed constants.
        script = script.replace("/run/rio-proof", str(self.private))
        result = subprocess.run(
            ["sh", "-ceu", script], cwd=self.root,
            env={"PATH": str(self.bin) + os.pathsep + os.environ["PATH"]},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
        )
        self.assertNotIn(CANARY.encode(), result.stdout + result.stderr)
        return result.returncode

    def test_custom_archive_is_private_and_restore_reads_all_bytes_from_checked_descriptor(self):
        self.assertEqual(self.execute(fixture.BACKUP_SCRIPT), 0)
        self.assertEqual(self.archive.read_bytes(), b"PGDMP_SYNTHETIC_FIXTURE_PAYLOAD")
        self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode), 0o600)
        self.assertEqual(self.archive.stat().st_nlink, 1)
        self.assertEqual(self.execute(fixture.RESTORE_SCRIPT), 0)
        self.assertEqual(self.restored.read_text(), "restored")

    def test_backup_never_overwrites_a_preexisting_file_or_link(self):
        target = self.private / "unrelated"
        target.write_bytes(b"PRESERVE")
        for kind in ("file", "symlink", "dangling", "hardlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    self.archive.write_bytes(b"PRESERVE")
                elif kind == "symlink":
                    self.archive.symlink_to(target)
                elif kind == "dangling":
                    self.archive.symlink_to(self.private / "absent")
                else:
                    os.link(target, self.archive)
                self.assertNotEqual(self.execute(fixture.BACKUP_SCRIPT), 0)
                self.assertEqual(target.read_bytes(), b"PRESERVE")
                if kind == "file":
                    self.assertEqual(self.archive.read_bytes(), b"PRESERVE")
                self.archive.unlink()

    def test_restore_rejects_links_permissions_empty_magic_and_oversized_archives(self):
        target = self.private / "unrelated"
        target.write_bytes(b"PGDMP_SYNTHETIC_FIXTURE_PAYLOAD")
        target.chmod(0o600)
        for kind in ("symlink", "hardlink", "permissions", "empty", "magic", "oversized"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    self.archive.symlink_to(target)
                elif kind == "hardlink":
                    os.link(target, self.archive)
                else:
                    self.archive.write_bytes(
                        b"" if kind == "empty" else b"WRONG" if kind == "magic" else target.read_bytes()
                    )
                    self.archive.chmod(0o644 if kind == "permissions" else 0o600)
                    if kind == "oversized":
                        with self.archive.open("r+b") as archive:
                            archive.truncate(16_777_217)
                self.assertNotEqual(self.execute(fixture.RESTORE_SCRIPT), 0)
                self.assertFalse(self.restored.exists())
                self.archive.unlink()

    def test_failed_dump_cannot_be_restored_as_a_successful_archive(self):
        self.program("pg_dump", "exit 7")
        self.assertNotEqual(self.execute(fixture.BACKUP_SCRIPT), 0)
        self.assertNotEqual(self.execute(fixture.RESTORE_SCRIPT), 0)
        self.assertFalse(self.restored.exists())


class NativeTlsCommandTests(unittest.TestCase):
    def test_native_clients_keep_fixed_verified_tls_and_private_credential_source(self):
        for script in (
            fixture.NATIVE_TLS_CONTROL_SCRIPT, fixture.CREATE_RESTORE_SCRIPT,
            fixture.BACKUP_SCRIPT, fixture.RESTORE_SCRIPT,
        ):
            with self.subTest(script=script.splitlines()[-1]):
                self.assertTrue(script.startswith(fixture.NATIVE_TLS_ENV))
                self.assertIn('PGPASSWORD="$(cat /run/rio-proof/password)"', script)
                for required in (
                    "PGHOST=localhost", "PGHOSTADDR=127.0.0.1", "PGPORT=5432", "PGUSER=rio_dev",
                    "PGSSLMODE=verify-full", "PGSSLROOTCERT=/run/rio-proof-input/ca.pem",
                    "PGCHANNELBINDING=require", "PGGSSENCMODE=disable",
                    "PGSSLMINPROTOCOLVERSION=TLSv1.2", "PGCONNECT_TIMEOUT=8",
                ):
                    self.assertIn(required, script)
                self.assertNotIn("sslmode=prefer", script)
                self.assertNotIn("sslmode=require", script)
                self.assertNotIn("postgres://", script)
                self.assertNotIn("--password=", script)
        self.assertIn("other-ca.pem psql", fixture.NATIVE_TLS_CONTROL_SCRIPT)
        self.assertIn("pg_stat_ssl", fixture.NATIVE_TLS_CONTROL_SCRIPT)
        self.assertIn("--maintenance-db=rio_synthetic_tls", fixture.CREATE_RESTORE_SCRIPT)
        self.assertIn("--template=template0 rio_synthetic_tls_restore", fixture.CREATE_RESTORE_SCRIPT)
        self.assertNotIn("--if-exists", fixture.CREATE_RESTORE_SCRIPT)
        self.assertIn("umask 077", fixture.BACKUP_SCRIPT)
        self.assertIn("set -C\nexec 3>", fixture.BACKUP_SCRIPT)
        self.assertIn("--schema=rio_synthetic --format=custom >&3", fixture.BACKUP_SCRIPT)
        self.assertNotIn("--schema-only", fixture.BACKUP_SCRIPT)
        self.assertNotIn("--data-only", fixture.BACKUP_SCRIPT)
        self.assertIn("--single-transaction --exit-on-error --no-owner --no-privileges", fixture.RESTORE_SCRIPT)
        self.assertIn("--dbname=rio_synthetic_tls_restore <&4", fixture.RESTORE_SCRIPT)
        self.assertNotIn("--clean", fixture.RESTORE_SCRIPT)
        for script in (fixture.BACKUP_SCRIPT, fixture.RESTORE_SCRIPT):
            self.assertIn("test ! -L /run/rio-proof/tls-snapshot.dump", script)
            self.assertIn('"600:$(id -u):1"', script)
            self.assertIn('test "$size" -ge 5 && test "$size" -le 16777216', script)
            self.assertIn("= PGDMP", script)
        self.assertIn("/proc/self/fd/4", fixture.RESTORE_SCRIPT)

    def test_native_failure_is_fixed_and_has_bounded_private_execution(self):
        owner = mock.Mock()
        for script, category in (
            (fixture.NATIVE_TLS_CONTROL_SCRIPT, "READINESS_FAILED"),
            (fixture.CREATE_RESTORE_SCRIPT, "CREATE_RESTORE_FAILED"),
            (fixture.BACKUP_SCRIPT, "BACKUP_FAILED"),
            (fixture.RESTORE_SCRIPT, "RESTORE_FAILED"),
        ):
            with (
                self.subTest(category=category),
                mock.patch.object(fixture, "_compose", return_value=["docker", "exec", script]),
                mock.patch.object(fixture, "_run_private", return_value=1) as private,
            ):
                with self.assertRaisesRegex(fixture.FixtureFailure, "^" + category + "$"):
                    fixture._run_native(owner, script, category, timeout=30)
                private.assert_called_once_with(owner, ["docker", "exec", script], timeout=30)


class OwnedRustProcessTests(unittest.TestCase):
    def setUp(self):
        self.child = mock.Mock(pid=43123)
        self.child.wait.return_value = 0
        self.process = self.patch(fixture.subprocess, "Popen", return_value=self.child)
        self.waitid = self.patch(
            fixture.os, "waitid", create=True,
            return_value=SimpleNamespace(si_pid=self.child.pid),
        )
        self.patch(fixture.os, "getpgid", create=True, return_value=self.child.pid)
        self.patch(fixture.os, "getsid", create=True, return_value=self.child.pid)
        self.killpg = self.patch(fixture.os, "killpg", create=True)
        for name, value in (("P_PID", 1), ("WEXITED", 4), ("WNOHANG", 1), ("WNOWAIT", 0x1000000)):
            self.patch(fixture.os, name, value, create=True)
        for name, value in (("SIG_BLOCK", 0), ("SIG_SETMASK", 2), ("SIGKILL", 9)):
            self.patch(fixture.signal, name, value, create=True)
        self.sigmask = self.patch(fixture.signal, "pthread_sigmask", create=True, return_value=set())
        self.sleep = self.patch(fixture.time, "sleep")
        self.clock = self.patch(fixture.time, "monotonic", return_value=0)

    def patch(self, target, name, *arguments, **options):
        patcher = mock.patch.object(target, name, *arguments, **options)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def run_process(self):
        return fixture._run_owned_rust_process(
            ["cargo", "test"], cwd=Path("."), env={}, stdout=io.BytesIO(),
            stderr=subprocess.STDOUT, timeout=1,
        )

    def assert_group_closed_before_reap(self):
        self.assertEqual(self.killpg.call_args_list, [
            mock.call(self.child.pid, signal.SIGTERM), mock.call(self.child.pid, fixture.signal.SIGKILL),
        ])
        self.sleep.assert_called_once_with(fixture.RUST_PROCESS_GRACE)
        self.child.wait.assert_called_once_with(timeout=fixture.RUST_PROCESS_REAP_TIMEOUT)
        self.sigmask.assert_any_call(fixture.signal.SIG_SETMASK, set())

    def test_success_retains_child_identity_until_both_group_signals_then_reaps(self):
        def signal_group(_pid, _signum):
            self.child.wait.assert_not_called()
        self.killpg.side_effect = signal_group
        self.assertEqual(self.run_process(), 0)
        self.assert_group_closed_before_reap()
        self.assertTrue(self.process.call_args.kwargs["start_new_session"])
        self.assertEqual(self.process.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(self.waitid.call_count, 3)
        for call in self.waitid.call_args_list:
            self.assertEqual(call, mock.call(
                fixture.os.P_PID, self.child.pid,
                fixture.os.WEXITED | fixture.os.WNOHANG | fixture.os.WNOWAIT,
            ))

    def test_timeout_gives_term_grace_kill_and_reap_before_exception(self):
        self.waitid.return_value = None
        self.clock.side_effect = [0, 2]
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_process()
        self.assert_group_closed_before_reap()

    def test_cancellation_gives_term_grace_kill_and_reap_without_printing_payload(self):
        self.waitid.side_effect = [KeyboardInterrupt(CANARY), None, None]
        output = io.StringIO()
        with mock.patch("sys.stdout", output), mock.patch("sys.stderr", output):
            with self.assertRaises(KeyboardInterrupt):
                self.run_process()
        self.assert_group_closed_before_reap()
        self.assertEqual(output.getvalue(), "")

    def test_changed_group_never_signals_an_unowned_group_and_fails_closed(self):
        self.patch(fixture.os, "getpgid", create=True, return_value=self.child.pid + 1)
        with self.assertRaisesRegex(fixture.FixtureFailure, "^CLEANUP_FAILED$"):
            self.run_process()
        self.killpg.assert_not_called()
        self.child.kill.assert_called_once_with()
        self.child.wait.assert_called_once_with(timeout=fixture.RUST_PROCESS_REAP_TIMEOUT)

    def test_lost_child_relationship_never_signals_a_potentially_reused_pid(self):
        self.waitid.side_effect = ChildProcessError(CANARY)
        with self.assertRaisesRegex(fixture.FixtureFailure, "^CLEANUP_FAILED$"):
            self.run_process()
        self.killpg.assert_not_called()
        self.child.kill.assert_not_called()
        self.child.wait.assert_called_once_with(timeout=fixture.RUST_PROCESS_REAP_TIMEOUT)

    def test_reap_failure_is_a_fixed_cleanup_failure(self):
        self.child.wait.side_effect = subprocess.TimeoutExpired(CANARY, 5)
        with self.assertRaisesRegex(fixture.FixtureFailure, "^CLEANUP_FAILED$"):
            self.run_process()
        self.assert_group_closed_before_reap()


if __name__ == "__main__":
    unittest.main()
