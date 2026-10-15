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
    service_code: int | None = None, service_selected: bool | None = None,
    service_case: str | None = None,
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
            is_service = selected_test == fixture.TESTS[1][0]
            selected = service_selected if is_service and service_selected is not None else selected_case
            case = service_case if is_service and service_case is not None else selected_test
            code = service_code if is_service and service_code is not None else cargo_code
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
        return SimpleNamespace(returncode=0)
    return execute


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


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "The fixture targets Linux CI.")
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

    def test_success_has_private_environment_exact_test_and_owned_cleanup(self):
        with local_root() as root:
            record = {}
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record)):
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
            self.assertEqual(len(set(record["rustTestLogs"])), 2)
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
                    self.assertIn("--command=\"SELECT 1\"", command[-1])
                    self.assertNotIn(record["password"], " ".join(command))

    def test_failed_rust_test_never_echoes_private_logs_and_still_cleans(self):
        with local_root() as root:
            record = {}
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, cargo_code=1)):
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
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, selected_case=False)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertFalse(result["rustTestPassed"])
            self.assertNotIn("RIO_TLS_RUST_TEST", output)
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_second_rust_failure_cannot_reuse_first_pass_and_still_cleans(self):
        with local_root() as root:
            record = {}
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, service_code=1)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertTrue(result["rustTestPassed"])
            self.assertFalse(result["rustTestsPassed"])
            self.assertEqual(result["rustTests"], [
                {"name": fixture.TESTS[0][0], "passed": True},
                {"name": fixture.TESTS[1][0], "passed": False},
            ])
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.TESTS[1][0] + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assertEqual(result["cleanup"], {"namespaceClosed": True, "privateFilesRemoved": True})
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_zero_selected_second_rust_case_cannot_reuse_first_pass(self):
        with local_root() as root:
            record = {}
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, service_selected=False)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertTrue(result["rustTestPassed"])
            self.assertFalse(result["rustTestsPassed"])
            self.assertFalse(result["rustTests"][1]["passed"])
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.TESTS[1][0] + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_second_log_with_only_first_case_pass_cannot_prove_service_test(self):
        with local_root() as root:
            record = {}
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, service_case=fixture.TEST)):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertTrue(result["rustTestPassed"])
            self.assertFalse(result["rustTestsPassed"])
            self.assertFalse(result["rustTests"][1]["passed"])
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.TESTS[1][0] + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_preexisting_second_log_is_rejected_before_cargo_can_use_stale_pass(self):
        with local_root() as root:
            record = {}
            execute = fake_commands(record)
            def stale_service_log(arguments, **options):
                completed = execute(arguments, **options)
                if arguments[0] == "cargo":
                    (fixture.RUNTIME / fixture.TESTS[1][1]).write_bytes((
                        "test " + fixture.TESTS[1][0] + " ... ok\n"
                        "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;\n"
                    ).encode())
                return completed
            with mock.patch.object(fixture.subprocess, "run", side_effect=stale_service_log):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "RUST_TEST_FAILED")
            self.assertTrue(result["rustTestPassed"])
            self.assertFalse(result["rustTestsPassed"])
            self.assertEqual(record["rustTests"], [fixture.TEST])
            self.assertNotIn("RIO_TLS_RUST_TEST " + fixture.TESTS[1][0] + " PASS", output)
            self.assertFalse(fixture.RUNTIME.exists())
            self.assert_private_output(output, record, root)
            self.assert_closed(result)

    def test_namespace_cleanup_failure_prevents_overall_pass_but_removes_private_files(self):
        with local_root() as root:
            record = {}
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, down_code=1)):
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
            with mock.patch.object(fixture.subprocess, "run", side_effect=AssertionError("no process allowed")) as process:
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
            with mock.patch.object(fixture.subprocess, "run", side_effect=AssertionError("no process allowed")) as process:
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
            with mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record, tamper_marker=True)):
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
            with mock.patch.object(fixture.subprocess, "run", side_effect=cancel_test):
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
                mock.patch.object(fixture.subprocess, "run", side_effect=fake_commands(record)),
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
            with mock.patch.object(fixture.subprocess, "run", side_effect=leftover):
                code, output, result = run_main()
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "CLEANUP_FAILED")
            self.assertEqual(result["cleanup"], {"namespaceClosed": False, "privateFilesRemoved": True})
            self.assertNotIn("SYNTHETIC_OWNED_VOLUME_REMAINS", output)
            self.assert_private_output(output, record, root)
            self.assert_closed(result)


if __name__ == "__main__":
    unittest.main()
