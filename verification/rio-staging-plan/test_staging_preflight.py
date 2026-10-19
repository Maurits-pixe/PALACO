"""Adversarial checks for the offline staging proposal, never deployment approval."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request

import staging_preflight as preflight


CANARY = "PRIVATE_CANARY_DO_NOT_PRINT_94237"
NULL_FIELDS = (
    "bffOrigin", "idpIssuer", "callbackUrl", "discoveryUrl",
    "authorizationUrl", "tokenUrl", "jwksUrl", "idpImage", "databaseImage",
)


def plan() -> dict:
    value = copy.deepcopy(preflight.FIXED)
    value.update({
        "source": {"repository": "Maurits-pixe/PALACO", "commit": "1" * 40},
        "endpoints": {
            "bffOrigin": "https://bff.example.invalid",
            "idpIssuer": "https://idp.example.invalid/realms/rio-synthetic-staging",
            "callbackUrl": "https://bff.example.invalid/auth/callback",
            "discoveryUrl": "https://idp.example.invalid/realms/rio-synthetic-staging/.well-known/openid-configuration",
            "authorizationUrl": "https://idp.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/auth",
            "tokenUrl": "https://idp.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/token",
            "jwksUrl": "https://idp.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/certs",
        },
        # These are deliberately invented digests: format is checked, images are not verified.
        "artifacts": {
            "idpImage": "quay.io/keycloak/keycloak:26.8.0@sha256:" + "2" * 64,
            "databaseImage": "postgres:18.6-bookworm@sha256:" + "3" * 64,
        },
    })
    return value


def encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def change(value: dict, path: tuple[str, ...], replacement: object) -> None:
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement


class StagingPreflightTests(unittest.TestCase):
    def assert_closed(self, result: dict) -> None:
        self.assertEqual(set(result), {"schemaVersion", "result", "errors", "missing", "checks", "boundary"})
        self.assertEqual(result["schemaVersion"], "RIO_STAGING_PREFLIGHT_RESULT_V1")
        self.assertEqual(result["checks"], {
            "networkProbesPerformed": False, "dnsVerified": False, "tlsVerified": False,
            "providerMetadataVerified": False, "sourceVerified": False,
            "artifactDigestsVerified": False,
        })
        self.assertEqual(result["boundary"], {
            "launchSupported": False, "deployAllowed": False, "account1": "HOLD",
            "humanAcceptance": "HOLD", "personalAccounts": False,
            "publicRegistration": False, "contact": False,
            "operativeAuthority": "NONE", "deployment": "HOLD",
        })
        self.assertTrue(all(type(value) is bool for value in result["checks"].values()))
        for key in ("launchSupported", "deployAllowed", "personalAccounts", "publicRegistration", "contact"):
            self.assertIs(result["boundary"][key], False)

    def assert_rejected(self, result: dict, category: str) -> None:
        self.assertEqual(result["result"], "REJECTED")
        self.assertIn(category, result["errors"])
        self.assert_closed(result)

    def test_consistent_proposal_does_not_verify_source_artifacts_or_authority(self):
        result = preflight.assess_bytes(encode(plan()))
        self.assertEqual(result["result"], "CONFIGURATION_CONSISTENT")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["missing"], [])
        self.assert_closed(result)
        rendered = json.dumps(result)
        self.assertNotIn("example.invalid", rendered)
        self.assertNotIn("1" * 40, rendered)
        self.assertNotIn("2" * 64, rendered)

    def test_nine_null_template_fields_are_incomplete_and_closed(self):
        value = plan()
        for key in value["endpoints"]:
            value["endpoints"][key] = None
        for key in value["artifacts"]:
            value["artifacts"][key] = None
        result = preflight.assess_bytes(encode(value))
        self.assertEqual(result["result"], "INCOMPLETE")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["missing"], sorted(NULL_FIELDS))
        self.assert_closed(result)

    def test_missing_field_never_hides_invalid_sibling_or_forged_boundary(self):
        mutations = [
            (("endpoints", "callbackUrl"), "https://other.example.invalid/wrong", "ENDPOINTS"),
            (("artifacts", "idpImage"), "latest", "ARTIFACTS"),
            (("source", "commit"), CANARY, "SOURCE"),
            (("boundary", "personalAccounts"), True, "CLOSED_BOUNDARY"),
            (("oidc", "registration"), True, "POLICY"),
        ]
        for path, replacement, category in mutations:
            with self.subTest(path=path):
                value = plan()
                value["endpoints"]["bffOrigin"] = None
                change(value, path, replacement)
                result = preflight.assess_bytes(encode(value))
                self.assert_rejected(result, category)
                self.assertIn("bffOrigin", result["missing"])

    def test_json_parser_rejects_nested_duplicates_and_nonfinite_literals(self):
        original = encode(plan())
        bad = [
            original[:-1] + b',"mode":"PLAN_ONLY"}',
            original.replace(b'"registration":false', b'"registration":false,"registration":false', 1),
            original.replace(b'"commit":"' + b"1" * 40 + b'"',
                             b'"commit":"' + b"1" * 40 + b'","commit":"' + CANARY.encode() + b'"', 1),
            original.replace(b'"personalData":false', b'"personalData":NaN', 1),
            original.replace(b'"personalData":false', b'"personalData":Infinity', 1),
            original.replace(b'"personalData":false', b'"personalData":-Infinity', 1),
        ]
        for index, raw in enumerate(bad):
            with self.subTest(case=index):
                self.assertNotEqual(raw, original)
                result = preflight.assess_bytes(raw)
                self.assert_rejected(result, "INPUT")
                self.assertNotIn(CANARY, json.dumps(result))
        # Exponential overflow is still unusable as any accepted typed policy field.
        overflow = original.replace(b'"personalData":false', b'"personalData":1e400', 1)
        self.assert_rejected(preflight.assess_bytes(overflow), "POLICY")

    def test_invalid_utf8_empty_bom_trailing_data_and_wrong_raw_type_are_closed(self):
        original = encode(plan())
        bad = [b"", b"\xff", b"\xef\xbb\xbf" + original, original + b"{}", b"{", original.decode(), bytearray(original)]
        for index, raw in enumerate(bad):
            with self.subTest(case=index):
                self.assert_rejected(preflight.assess_bytes(raw), "INPUT")

    def test_limit_applies_to_exact_utf8_bytes_including_trailing_padding(self):
        original = encode(plan())
        self.assertLess(len(original), preflight.LIMIT)
        at_limit = original + b" " * (preflight.LIMIT - len(original))
        self.assertEqual(len(at_limit), 16_384)
        result = preflight.assess_bytes(at_limit)
        self.assertEqual(result["result"], "CONFIGURATION_CONSISTENT")
        self.assert_closed(result)
        self.assert_rejected(preflight.assess_bytes(at_limit + b" "), "INPUT")
        oversized_unicode = encode({"secret": "\u00e9" * 16_384})
        self.assert_rejected(preflight.assess_bytes(oversized_unicode), "INPUT")

    def test_schema_is_exact_and_top_level_shape_is_not_coerced(self):
        for value in (None, [], "", 0, False, {"schemaVersion": "RIO_STAGING_PLAN_V1"}):
            with self.subTest(shape=type(value).__name__):
                self.assert_rejected(preflight.assess_bytes(encode(value)), "SCHEMA")
        for key in plan():
            with self.subTest(missing=key):
                value = plan()
                del value[key]
                self.assert_rejected(preflight.assess_bytes(encode(value)), "SCHEMA")
        value = plan()
        value["clientSecret"] = CANARY
        self.assert_rejected(preflight.assess_bytes(encode(value)), "SCHEMA")

    def test_policy_types_and_scopes_cannot_broaden_the_fixed_slice(self):
        cases = [
            (("schemaVersion",), "RIO_STAGING_PLAN_V2"),
            (("mode",), "PRODUCTION"),
            (("oidc", "clientType"), "PUBLIC"),
            (("oidc", "flow"), "password"),
            (("oidc", "pkce"), "plain"),
            (("oidc", "scope"), ["openid", "email"]),
            (("oidc", "registration"), True),
            (("oidc", "registration"), 0),
            (("oidc", "directAccessGrants"), "false"),
            (("oidc", "serviceAccounts"), True),
            (("data", "actors"), ["TST-alpha", CANARY]),
            (("data", "personalData"), 0),
            (("data", "smtp"), True),
            (("transport", "browserTls"), "ALLOW_UNTRUSTED_CERT"),
            (("transport", "providerTls"), False),
            (("transport", "databaseTls"), "DISABLED"),
            (("transport", "forwardedHeaders"), "TRUST_ANY"),
            (("transport", "secretPolicy"), "INLINE_VALUES"),
        ]
        for path, replacement in cases:
            with self.subTest(path=path, replacement_type=type(replacement).__name__):
                value = plan()
                change(value, path, replacement)
                self.assert_rejected(preflight.assess_bytes(encode(value)), "POLICY")

    def test_every_boundary_field_is_immutable_and_exactly_typed(self):
        for key, replacement in (
            ("account1", "OPEN"), ("personalAccounts", True), ("personalAccounts", 0),
            ("contact", "false"), ("operativeAuthority", "ISSUER"), ("deployment", "READY"),
        ):
            with self.subTest(key=key, replacement_type=type(replacement).__name__):
                value = plan()
                value["boundary"][key] = replacement
                self.assert_rejected(preflight.assess_bytes(encode(value)), "CLOSED_BOUNDARY")

    def test_origin_rejects_ambiguous_unsafe_and_noncanonical_urls(self):
        values = [
            "http://bff.example.invalid", "//bff.example.invalid",
            "https://user:password@bff.example.invalid",
            "https://bff.example.invalid?secret=" + CANARY, "https://bff.example.invalid#",
            "https://bff.example.invalid/", "https://bff.example.invalid/private",
            "https://bff%2eexample.invalid", "https://bff.example.invalid\\private",
            "https://bff.example.invalid:443", "https://bff.example.invalid:8088",
            "HTTPS://bff.example.invalid", "https://BFF.example.invalid",
            "https://bff.example.invalid.", " https://bff.example.invalid",
            "https://bff.example.invalid ", "https://bff.\texample.invalid",
            "https://bff.\nexample.invalid", "https://bff.\x00example.invalid",
            "https://bff.\u00e9xample.invalid", "https://127.0.0.1", "https://192.168.1.1",
            "https://[::1]", "https://localhost", "https://bff.localhost", "https://bff.local",
            "https://*.example.invalid", "https://-bff.example.invalid",
            "https://bff-.example.invalid", "https://bff_example.invalid",
            "https://" + "a" * 64 + ".example.invalid",
            "https://" + ".".join(["a" * 63] * 4) + ".invalid",
            0, False, [], {},
        ]
        for index, endpoint in enumerate(values):
            with self.subTest(case=index):
                value = plan()
                value["endpoints"]["bffOrigin"] = endpoint
                self.assert_rejected(preflight.assess_bytes(encode(value)), "ENDPOINTS")

    def test_endpoint_paths_realms_and_scheme_are_exact(self):
        cases = [
            ("idpIssuer", "https://idp.example.invalid/realms/production"),
            ("idpIssuer", "https://idp.example.invalid/realms/rio-synthetic-staging/"),
            ("callbackUrl", "https://bff.example.invalid/auth/callback/"),
            ("callbackUrl", "https://bff.example.invalid/./auth/callback"),
            ("callbackUrl", "https://bff.example.invalid/auth/callback?next=" + CANARY),
            ("discoveryUrl", "https://idp.example.invalid/.well-known/openid-configuration"),
            ("authorizationUrl", "http://idp.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/auth"),
            ("tokenUrl", "https://idp.example.invalid/realms/other/protocol/openid-connect/token"),
            ("jwksUrl", "https://idp.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/userinfo"),
        ]
        for key, endpoint in cases:
            with self.subTest(key=key):
                value = plan()
                value["endpoints"][key] = endpoint
                self.assert_rejected(preflight.assess_bytes(encode(value)), "ENDPOINTS")

    def test_callback_is_bound_to_the_selected_bff_host(self):
        value = plan()
        value["endpoints"]["callbackUrl"] = "https://other.example.invalid/auth/callback"
        self.assert_rejected(preflight.assess_bytes(encode(value)), "CALLBACK_BINDING")

    def test_bff_and_provider_cookie_hosts_must_be_distinct(self):
        value = plan()
        for key in ("idpIssuer", "discoveryUrl", "authorizationUrl", "tokenUrl", "jwksUrl"):
            value["endpoints"][key] = value["endpoints"][key].replace("idp.example.invalid", "bff.example.invalid")
        self.assert_rejected(preflight.assess_bytes(encode(value)), "COOKIE_HOST_ISOLATION")

    def test_each_provider_endpoint_is_bound_to_the_selected_issuer_host(self):
        for key in ("discoveryUrl", "authorizationUrl", "tokenUrl", "jwksUrl"):
            with self.subTest(key=key):
                value = plan()
                value["endpoints"][key] = value["endpoints"][key].replace("idp.example.invalid", "other.example.invalid")
                self.assert_rejected(preflight.assess_bytes(encode(value)), "PROVIDER_BINDING")

    def test_source_reference_is_required_but_never_reported_as_verified(self):
        for repository, commit in (
            ("Maurits-pixe/PALACO-Citadel", "1" * 40),
            ("Maurits-pixe/PALACO", "1" * 39),
            ("Maurits-pixe/PALACO", "A" * 40),
            ("Maurits-pixe/PALACO", "1" * 40 + "\n"),
            ("Maurits-pixe/PALACO", None),
            ("Maurits-pixe/PALACO", 1),
        ):
            with self.subTest(repository=repository, commit_type=type(commit).__name__):
                value = plan()
                value["source"] = {"repository": repository, "commit": commit}
                self.assert_rejected(preflight.assess_bytes(encode(value)), "SOURCE")
        value = plan()
        value["source"]["clientSecret"] = CANARY
        self.assert_rejected(preflight.assess_bytes(encode(value)), "SOURCE")

    def test_artifact_format_rejects_mutable_or_foreign_refs_without_attesting_images(self):
        cases = [
            ("idpImage", "quay.io/keycloak/keycloak:latest"),
            ("idpImage", "quay.io/keycloak/keycloak:26.8.0"),
            ("idpImage", "other.example.invalid/keycloak:26.8.0@sha256:" + "2" * 64),
            ("idpImage", "quay.io/keycloak/keycloak:26.8.0@sha256:" + "A" * 64),
            ("idpImage", "quay.io/keycloak/keycloak:26.8.0@sha256:" + "2" * 63),
            ("databaseImage", "postgres:latest@sha256:" + "3" * 64),
            ("databaseImage", "postgres:18.6-alpine@sha256:" + "3" * 64),
            ("databaseImage", False),
        ]
        for key, reference in cases:
            with self.subTest(key=key):
                value = plan()
                value["artifacts"][key] = reference
                self.assert_rejected(preflight.assess_bytes(encode(value)), "ARTIFACTS")
        value = plan()
        value["artifacts"]["databaseImage"] = None
        result = preflight.assess_bytes(encode(value))
        self.assertEqual(result["result"], "INCOMPLETE")
        self.assertEqual(result["missing"], ["databaseImage"])
        self.assert_closed(result)

    def test_secret_canaries_never_escape_valid_or_rejected_summaries(self):
        cases = [
            (("clientSecret",), CANARY),
            (("source", "commit"), CANARY),
            (("data", "password"), CANARY),
            (("oidc", "secret"), CANARY),
            (("transport", "tlsKey"), "-----BEGIN PRIVATE KEY-----" + CANARY),
            (("endpoints", "tokenUrl"), "https://user:" + CANARY + "@idp.example.invalid/token"),
            (("artifacts", "idpImage"), CANARY),
        ]
        for path, secret in cases:
            with self.subTest(path=path):
                value = plan()
                change(value, path, secret)
                result = preflight.assess_bytes(encode(value))
                self.assertEqual(result["result"], "REJECTED")
                self.assert_closed(result)
                self.assertNotIn(CANARY, json.dumps(result))

    def test_assessment_file_read_and_main_perform_no_network_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_bytes(encode(plan()))
            with (
                mock.patch.object(socket, "socket", side_effect=AssertionError("network must remain unused")) as sockets,
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network must remain unused")) as connections,
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS must remain unused")) as dns,
                mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("HTTP must remain unused")) as http,
                mock.patch.dict(os.environ, {"RIO_DEV_CLIENT_SECRET": CANARY, "HTTP_PROXY": "http://" + CANARY}),
            ):
                self.assertEqual(preflight.assess_bytes(encode(plan()))["result"], "CONFIGURATION_CONSISTENT")
                self.assertEqual(preflight.read_plan(str(path))["result"], "CONFIGURATION_CONSISTENT")
                output = io.StringIO()
                with mock.patch.object(sys, "argv", ["staging_preflight.py", str(path)]), mock.patch("sys.stdout", output):
                    self.assertEqual(preflight.main(), 0)
                self.assertNotIn(CANARY, output.getvalue())
                self.assert_closed(json.loads(output.getvalue()))
                for operation in (sockets, connections, dns, http):
                    operation.assert_not_called()

    def test_regular_file_reads_and_all_read_errors_use_fixed_input_category(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "plan.json"
            regular.write_bytes(encode(plan()))
            self.assertEqual(preflight.read_plan(str(regular))["result"], "CONFIGURATION_CONSISTENT")
            oversized = root / "oversized.json"
            oversized.write_bytes(b" " * (preflight.LIMIT + 1))
            invalid = root / "invalid.json"
            invalid.write_bytes(b"\xff")
            for path in (root, root / CANARY, oversized, invalid):
                with self.subTest(kind=path.name):
                    result = preflight.read_plan(str(path))
                    self.assert_rejected(result, "INPUT")
                    self.assertNotIn(CANARY, json.dumps(result))
                    self.assertNotIn(str(root), json.dumps(result))

    def test_unc_extended_unc_nul_and_nonstring_paths_are_rejected_before_io(self):
        paths = (
            r"\\server\share\PRIVATE_CANARY_DO_NOT_PRINT_94237.json",
            r"\\?\UNC\server\share\PRIVATE_CANARY_DO_NOT_PRINT_94237.json",
            "//server/share/" + CANARY,
            "local\x00" + CANARY,
            None, b"local.json", Path("local.json"),
        )
        with (
            mock.patch.object(preflight.os, "lstat", side_effect=AssertionError("precheck must precede filesystem I/O")) as lstat,
            mock.patch.object(preflight.os, "open", side_effect=AssertionError("precheck must precede filesystem I/O")) as opened,
            mock.patch.object(preflight.os.path, "islink", side_effect=AssertionError("precheck must precede filesystem I/O")) as islink,
        ):
            for index, path in enumerate(paths):
                with self.subTest(case=index):
                    result = preflight.read_plan(path)
                    self.assert_rejected(result, "INPUT")
                    self.assertNotIn(CANARY, json.dumps(result))
            for operation in (lstat, opened, islink):
                operation.assert_not_called()

    def test_symlink_file_is_rejected_including_initial_check_race(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "plan.json"
            target.write_bytes(encode(plan()))
            link = root / "link.json"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("This host cannot create symlinks; Linux CI exercises the no-follow case.")
            self.assert_rejected(preflight.read_plan(str(link)), "INPUT")
            if hasattr(os, "O_NOFOLLOW"):
                with mock.patch.object(preflight.os.path, "islink", return_value=False):
                    self.assert_rejected(preflight.read_plan(str(link)), "INPUT")

    def test_actual_cli_exit_codes_and_private_paths_never_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "consistent.json"
            good.write_bytes(encode(plan()))
            incomplete = plan()
            incomplete["endpoints"]["bffOrigin"] = None
            pending = root / "incomplete.json"
            pending.write_bytes(encode(incomplete))
            rejected = plan()
            rejected["clientSecret"] = CANARY
            bad = root / (CANARY + ".json")
            bad.write_bytes(encode(rejected))
            missing = root / (CANARY + "-missing.json")
            for path, status, code in (
                (good, "CONFIGURATION_CONSISTENT", 0),
                (pending, "INCOMPLETE", 2),
                (bad, "REJECTED", 3),
                (missing, "REJECTED", 3),
            ):
                with self.subTest(status=status, expected_code=code):
                    completed = subprocess.run(
                        [sys.executable, str(Path(preflight.__file__).resolve()), str(path)],
                        capture_output=True, text=True, check=False, timeout=10,
                    )
                    self.assertEqual(completed.returncode, code)
                    self.assertEqual(completed.stderr, "")
                    self.assertNotIn(CANARY, completed.stdout + completed.stderr)
                    self.assertNotIn(str(root), completed.stdout + completed.stderr)
                    result = json.loads(completed.stdout)
                    self.assertEqual(result["result"], status)
                    self.assert_closed(result)

    def test_cli_wrong_argument_count_uses_fixed_errors_without_printing_arguments(self):
        for arguments in ([], [CANARY, CANARY]):
            with self.subTest(argument_count=len(arguments)):
                completed = subprocess.run(
                    [sys.executable, str(Path(preflight.__file__).resolve()), *arguments],
                    capture_output=True, text=True, check=False, timeout=10,
                )
                self.assertEqual(completed.returncode, 3)
                self.assertEqual(completed.stderr, "")
                self.assertNotIn(CANARY, completed.stdout)
                self.assert_rejected(json.loads(completed.stdout), "INPUT")


if __name__ == "__main__":
    unittest.main()
