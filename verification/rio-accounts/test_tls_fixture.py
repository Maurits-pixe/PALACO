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
        self.assertEqual(result["rustTestsPassed"], len(passed) == 4)

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
            self.assertEqual(len(set(record["rustTestLogs"])), 4)
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
                self.assertEqual(record["rustTests"], [test for test, _log in fixture.TESTS])
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
