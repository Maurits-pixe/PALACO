"""Security and lifecycle checks for the synthetic fixture; no Docker required."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().with_name("fixture.py")
SPEC = importlib.util.spec_from_file_location("rio_fixture_under_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot import the fixture module.")
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)

class FixtureSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rio-fixture-unit-")
        self.root = Path(self.temporary.name)
        self.runtime_patch = patch.object(fixture, "RUNTIME", self.root / ".runtime")
        self.runtime_patch.start()

    def tearDown(self):
        self.runtime_patch.stop()
        self.temporary.cleanup()

    def prepare(self):
        output = io.StringIO()
        # Certificate execution is mocked; these tests do not claim TLS validity.
        with patch.object(fixture.shutil, "which", return_value="/test/openssl"):
            with patch.object(fixture.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                with redirect_stdout(output):
                    fixture.prepare()
        return output.getvalue(), run

    def credentials(self):
        return json.loads((fixture.RUNTIME / "test-credentials.json").read_text(encoding="utf-8"))

    def imported_realm(self):
        return json.loads((fixture.RUNTIME / "rio-synthetic-realm.json").read_text(encoding="utf-8"))

    def test_realm_allows_only_synthetic_browser_code_login(self):
        self.prepare()
        realm = self.imported_realm()
        for key in ("registrationAllowed", "registrationEmailAsUsername",
                    "loginWithEmailAllowed", "resetPasswordAllowed", "rememberMe",
                    "verifyEmail", "editUsernameAllowed"):
            self.assertIs(realm[key], False, key)
        self.assertEqual(realm["smtpServer"], {})
        self.assertEqual(realm["identityProviders"], [])
        self.assertEqual(realm["defaultSignatureAlgorithm"], "RS256")
        self.assertEqual(len(realm["clients"]), 1)
        client = realm["clients"][0]
        self.assertEqual(client["clientId"], "rio-bff")
        self.assertIs(client["publicClient"], False)
        self.assertIs(client["standardFlowEnabled"], True)
        for key in ("directAccessGrantsEnabled", "implicitFlowEnabled",
                    "serviceAccountsEnabled", "authorizationServicesEnabled", "fullScopeAllowed"):
            self.assertIs(client[key], False, key)
        self.assertEqual(client["attributes"]["pkce.code.challenge.method"], "S256")
        self.assertEqual(client["attributes"]["id.token.signed.response.alg"], "RS256")
        self.assertEqual(client["attributes"]["oauth2.device.authorization.grant.enabled"], "false")
        self.assertEqual(client["attributes"]["oidc.ciba.grant.enabled"], "false")
        self.assertEqual(client["redirectUris"], ["https://localhost:8088/auth/callback"])
        self.assertEqual(client["webOrigins"], [])
        self.assertEqual(client["defaultClientScopes"], [])
        self.assertEqual(client["optionalClientScopes"], [])

    def test_subjects_and_optional_profile_never_require_email(self):
        self.prepare()
        realm = self.imported_realm()
        expected = {
            "TST-alpha": "11111111-1111-4111-8111-111111111111",
            "TST-beta": "22222222-2222-4222-8222-222222222222",
        }
        self.assertEqual({user["username"]: user["id"] for user in realm["users"]}, expected)
        for user in realm["users"]:
            self.assertNotIn("email", user)
            self.assertNotIn("firstName", user)
            self.assertNotIn("lastName", user)
            self.assertEqual(user["requiredActions"], [])
            self.assertIs(user["credentials"][0]["temporary"], False)
        component = realm["components"]["org.keycloak.userprofile.UserProfileProvider"][0]
        self.assertEqual(component["providerId"], "declarative-user-profile")
        profile = json.loads(component["config"]["kc.user.profile.config"][0])
        attributes = {attribute["name"]: attribute for attribute in profile["attributes"]}
        for name in ("email", "firstName", "lastName"):
            self.assertNotIn("required", attributes[name])
        self.assertNotIn("unmanagedAttributePolicy", profile)
        # UPConfig only accepts ENABLED, ADMIN_VIEW or ADMIN_EDIT; absent means disabled.

    def test_runtime_secrets_are_random_private_and_never_printed(self):
        output, run = self.prepare()
        env = fixture.read_bff_environment()
        secret = env["RIO_DEV_CLIENT_SECRET"]
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", secret) is not None,
                        "Client secret must be 32 random bytes encoded as 64 hexadecimal characters.")
        self.assertTrue(secret not in output, "Client secret must never be printed.")
        self.assertTrue(secret == self.imported_realm()["clients"][0]["secret"],
                        "Client secret must match in the BFF and realm import.")
        self.assertEqual(env["RIO_DEV_MODE"], "SYNTHETIC_ONLY")
        for user in self.credentials().values():
            self.assertTrue(len(user["password"]) >= 24, "Synthetic password must be generated.")
            self.assertTrue(user["password"] not in output, "Synthetic passwords must never be printed.")
        self.assertEqual({path.name for path in self.root.iterdir()}, {".runtime"})
        self.assertEqual({path.name for path in fixture.RUNTIME.iterdir()}, set(fixture.GENERATED_FILES))
        self.assertEqual(run.call_count, 1)
        args = run.call_args.args[0]
        self.assertEqual(args[0], "openssl")
        self.assertIn("subjectAltName=IP:127.0.0.1,DNS:localhost", args)
        self.assertEqual(args[args.index("-days") + 1], "1")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(fixture.RUNTIME.stat().st_mode), 0o700)
            for name in fixture.PRIVATE_FILES:
                self.assertEqual(stat.S_IMODE((fixture.RUNTIME / name).stat().st_mode), 0o600, name)
            self.assertEqual(stat.S_IMODE((fixture.RUNTIME / "rio-synthetic-realm.json").stat().st_mode), 0o644)

    def test_complete_runtime_is_reused_and_new_runtime_rotates_secrets(self):
        self.prepare()
        initial = fixture.read_bff_environment()["RIO_DEV_CLIENT_SECRET"]
        with patch.object(fixture.subprocess, "run") as run:
            with redirect_stdout(io.StringIO()):
                fixture.prepare()
            run.assert_not_called()
        self.assertTrue(initial == fixture.read_bff_environment()["RIO_DEV_CLIENT_SECRET"],
                        "Repeated prepare must not silently invalidate a running client.")
        with patch.object(fixture, "compose"):
            with redirect_stdout(io.StringIO()):
                fixture.down()
        self.prepare()
        self.assertTrue(initial != fixture.read_bff_environment()["RIO_DEV_CLIENT_SECRET"],
                        "A fresh runtime must have a different client secret.")

    def test_incomplete_runtime_refuses_to_overwrite(self):
        fixture.RUNTIME.mkdir()
        sentinel = fixture.RUNTIME / "metadata.json"
        sentinel.write_text("sentinel", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Incomplete runtime"):
            fixture.prepare()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "sentinel")
        self.assertEqual({path.name for path in fixture.RUNTIME.iterdir()}, {"metadata.json"})

    def test_unknown_cleanup_project_is_refused_before_any_container_command(self):
        self.prepare()
        (fixture.RUNTIME / "metadata.json").write_text(json.dumps({"project": "unrelated-production"}), encoding="utf-8")
        with patch.object(fixture.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Invalid synthetic Compose project"):
                fixture.down()
            run.assert_not_called()
        self.assertEqual({path.name for path in fixture.RUNTIME.iterdir()}, set(fixture.GENERATED_FILES))

    def test_cleanup_removes_only_known_files_in_this_runtime(self):
        self.prepare()
        sentinel = fixture.RUNTIME / "unrelated-note.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with patch.object(fixture, "compose") as compose:
            with redirect_stdout(io.StringIO()):
                fixture.down()
            compose.assert_called_once_with("down", "--volumes", "--remove-orphans")
        self.assertEqual({path.name for path in fixture.RUNTIME.iterdir()}, {"unrelated-note.txt"})
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def symlink(self, source, target, directory=False):
        try:
            source.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("Creating symlinks requires a permission unavailable on this platform.")

    def test_symlinked_runtime_directory_is_refused(self):
        external = self.root / "external"
        external.mkdir()
        self.symlink(fixture.RUNTIME, external, directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlinked runtime directory"):
            fixture.prepare()
        self.assertEqual(list(external.iterdir()), [])

    def test_symlinked_runtime_file_is_refused_and_target_is_preserved(self):
        fixture.RUNTIME.mkdir()
        target = self.root / "outside.txt"
        target.write_text("keep", encoding="utf-8")
        self.symlink(fixture.RUNTIME / "bff.env", target)
        with self.assertRaisesRegex(RuntimeError, "symlinked runtime files"):
            fixture.prepare()
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_compose_and_ignore_contract(self):
        compose = MODULE_PATH.with_name("compose.yaml").read_text(encoding="utf-8")
        self.assertIn("quay.io/keycloak/keycloak:26.8.0", compose)
        self.assertIn('"127.0.0.1:8089:8089"', compose)
        self.assertIn("--db=dev-mem", compose)
        self.assertIn("--verbose", compose)
        self.assertIn("@sha256:27b3230fbabb8c9ff3c66c864cf09dcd8a41aca82e5100679d109ef0eeb05741", compose)
        self.assertNotIn("internal: true", compose)
        self.assertIn("driver: bridge", compose)
        self.assertNotIn("network_mode: host", compose)
        self.assertNotIn('"8089:8089"', compose)
        self.assertNotIn('"0.0.0.0:8089:8089"', compose)
        self.assertIn("read_only: true", compose)
        self.assertNotIn("localhost:8089", compose)
        ignored = MODULE_PATH.with_name(".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".runtime/", ignored)


    def test_provider_diagnostics_redact_all_runtime_secrets_and_unknown_tokens(self):
        self.prepare()
        secrets_to_hide = fixture.runtime_secret_values()
        unknown_token = fixture.secrets.token_hex(32)
        private_log = (
            "INFO: normal startup configuration\n"
            "ERROR: UserProfile configuration invalid for username: " + " ".join(secrets_to_hide) + "\n"
            "Caused by: org.keycloak.component.ComponentValidationException: "
            "Validator 'username-prohibited-characters' defined for attribute 'username' doesn't exist\n"
            "ERROR: Failed to import realm: token=" + unknown_token + "\n"
            "DEBUG: profile configuration details must stay private\n"
        )
        runs = [
            SimpleNamespace(returncode=0, stdout=json.dumps({"Running": False, "ExitCode": 1, "OOMKilled": False,
                                                          "Error": unknown_token}), stderr=""),
            SimpleNamespace(returncode=0, stdout=private_log, stderr=""),
        ]
        output = io.StringIO()
        with patch.object(fixture.subprocess, "run", side_effect=runs):
            with patch.object(fixture, "build_opener", side_effect=fixture.URLError("unreachable")):
                with redirect_stdout(output):
                    fixture.diagnostics()
        emitted = output.getvalue()
        for value in [*secrets_to_hide, unknown_token]:
            self.assertTrue(value not in emitted, "Provider diagnostics must not disclose secret material.")
        self.assertNotIn("DEBUG:", emitted)
        document = json.loads(emitted.splitlines()[0].split(" ", 1)[1])
        self.assertEqual(document["state"], {"Running": False, "ExitCode": 1, "OOMKilled": False})
        self.assertTrue(any("ComponentValidationException" in line for line in document["errorDetails"]))
        self.assertTrue(any("username-prohibited-characters" in line for line in document["errorDetails"]))
        self.assertTrue(any("[REDACTED_TOKEN]" in line for line in document["errorDetails"]))

    def test_diagnostics_missing_redaction_inputs_fail_closed(self):
        self.prepare()
        (fixture.RUNTIME / "test-credentials.json").unlink()
        private_token = fixture.secrets.token_hex(32)
        runs = [
            SimpleNamespace(returncode=0, stdout=json.dumps({"Running": private_token,
                                                          "ExitCode": private_token, "OOMKilled": private_token}), stderr=""),
            SimpleNamespace(returncode=0, stdout="ERROR: Failed to import realm " + private_token, stderr=""),
        ]
        output = io.StringIO()
        with patch.object(fixture.subprocess, "run", side_effect=runs):
            with patch.object(fixture, "build_opener", side_effect=fixture.URLError("unreachable")):
                with redirect_stdout(output):
                    fixture.diagnostics()
        emitted = output.getvalue()
        self.assertTrue(private_token not in emitted, "Missing redaction inputs must not expose provider output.")
        document = json.loads(emitted.splitlines()[0].split(" ", 1)[1])
        self.assertEqual(document["errorDetails"], ["REDACTION_INPUTS_UNAVAILABLE"])
        self.assertEqual(document["state"], {"Running": None, "ExitCode": None, "OOMKilled": None})

    def test_provider_details_are_bounded_and_configuration_payloads_are_suppressed(self):
        raw = "\n".join(f"ERROR: UserProfile invalid attribute field-{index}: " + ("x " * 1000)
                        for index in range(20))
        details = fixture.provider_error_details(raw)
        self.assertEqual(len(details), 8)
        self.assertTrue(all(len(line) <= 900 for line in details))
        payload = 'ERROR: UserProfile invalid {"credentials":[{"password":"anything"}]}'
        self.assertEqual(fixture.provider_error_details(payload),
                         ["CONFIGURATION_OR_DATABASE_PAYLOAD_REDACTED"])


    def test_public_port_diagnostics_accept_only_validated_metadata(self):
        fake_secret = fixture.secrets.token_hex(32)
        ports = {
            "8089/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8089", "Env": fake_secret}],
            "8443/tcp": None,
            fake_secret: [{"HostIp": "127.0.0.1", "HostPort": "8089"}],
            "9000/tcp": [{"HostIp": fake_secret, "HostPort": "9000"}],
            "9001/tcp": [{"HostIp": "127.0.0.1", "HostPort": fake_secret}],
        }
        result = fixture.public_port_bindings(ports)
        self.assertEqual(result, [{"containerPort": "8089/tcp", "hostIp": "127.0.0.1", "hostPort": 8089}])
        self.assertTrue(fake_secret not in json.dumps(result), "Port diagnostics must not expose unrelated metadata.")
        self.assertEqual(fixture.public_port_bindings(None), [])

if __name__ == "__main__":
    unittest.main()
