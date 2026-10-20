"""Synthetic fixtures only; no real keys, identities, domains or enrollment."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import register_reader as reader


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "registry.json"
        self.now = int(time.time())
        self.snapshot = {
            "schema": reader.SCHEMA, "revision": "fixture-r1", "mode": "Synthetic",
            "issued_at": self.now - 1, "expires_at": self.now + 59,
            "records": [{
                "tenant": "fixture-tenant", "actor": "fixture-actor",
                "device": "fixture-device", "key_ref": "fixture-public-reference",
                "epoch": 1, "valid_from": self.now - 10,
                "expires_at": self.now + 100, "revoked": False,
            }],
        }

    def write(self, value=None, raw=None):
        raw = raw if raw is not None else json.dumps(value or self.snapshot).encode()
        self.path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def read(self, digest):
        return reader.read_register(str(self.path), digest, "fixture-r1", "Synthetic")

    def closed(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertEqual(result["disposition"], "HOLD")
        self.assertEqual(result["operativeAuthority"], "NONE")
        for field in ("authenticated", "canOpenContact", "runtimeConnected", "externalSideEffect"):
            self.assertIs(result[field], False)
        if status != "PINNED_UNVERIFIED":
            self.assertNotIn("snapshot", result)
        self.assertNotIn(str(self.path), json.dumps(result))

    def test_active_and_revoked_exact_bytes_remain_unverified(self):
        for revoked in (False, True):
            self.snapshot["records"][0]["revoked"] = revoked
            result = self.read(self.write())
            self.closed(result, "PINNED_UNVERIFIED")
            self.assertEqual(result["snapshot"], self.snapshot)

    def test_same_revision_substitution_and_whitespace_change_break_pin(self):
        digest = self.write()
        self.snapshot["records"][0]["revoked"] = True
        self.write()
        self.closed(self.read(digest), "INTEGRITY_MISMATCH")
        digest = self.write()
        with self.path.open("ab") as stream:
            stream.write(b"\n")
        self.closed(self.read(digest), "INTEGRITY_MISMATCH")

    def test_missing_directory_symlink_and_fifo_are_closed(self):
        self.closed(self.read("0" * 64), "UNAVAILABLE")
        self.path.mkdir()
        self.closed(self.read("0" * 64), "INVALID")
        self.path.rmdir()
        source = Path(self.temp.name) / "target.json"
        source.write_text("{}")
        self.path.symlink_to(source)
        self.closed(self.read("0" * 64), "UNAVAILABLE")
        self.path.unlink()
        os.mkfifo(self.path)
        self.closed(self.read("0" * 64), "INVALID")

    def test_unreadable_open_error_is_sanitized(self):
        digest = self.write()
        request = {
            "path": str(self.path), "sha256": digest,
            "revision": "fixture-r1", "mode": "Synthetic",
        }
        # Deterministic under privileged CI too; no reliance on chmod as root.
        with patch.object(reader.os, "open", side_effect=PermissionError("private details")):
            self.closed(reader._worker(request), "UNAVAILABLE")

    def test_replacement_during_read_is_detected(self):
        digest = self.write()
        original = reader.os.read
        replaced = False

        def replace(fd, count):
            nonlocal replaced
            raw = original(fd, count)
            if not replaced:
                replacement = Path(self.temp.name) / "replacement.json"
                replacement.write_bytes(self.path.read_bytes())
                replacement.replace(self.path)
                replaced = True
            return raw

        with patch.object(reader.os, "read", side_effect=replace):
            with self.assertRaisesRegex(reader.Rejected, "CHANGED"):
                reader._read_pinned(str(self.path), digest)

    def test_stale_future_revision_and_mode_are_rejected(self):
        for start, end in [(self.now - 60, self.now), (self.now + 60, self.now + 120)]:
            self.snapshot["issued_at"], self.snapshot["expires_at"] = start, end
            self.closed(self.read(self.write()), "STALE")
        self.snapshot["issued_at"], self.snapshot["expires_at"] = self.now - 1, self.now + 59
        self.snapshot["revision"] = "other"
        self.closed(self.read(self.write()), "REVISION_MISMATCH")
        self.snapshot["revision"] = "fixture-r1"
        self.snapshot["mode"] = "LocalObservation"
        self.closed(self.read(self.write()), "INVALID")

    def test_schema_types_unknown_fields_and_duplicates_are_rejected(self):
        mutations = [
            lambda s: s.update(extra=True),
            lambda s: s.update(issued_at=True),
            lambda s: s.update(expires_at=s["issued_at"] + 61),
            lambda s: s["records"][0].update(epoch=True),
            lambda s: s["records"][0].update(epoch=2**64),
            lambda s: s["records"][0].update(revoked="false"),
            lambda s: s["records"][0].update(key_ref="x" * 257),
            lambda s: s["records"][0].update(actor="bad\nreference"),
            lambda s: s["records"][0].update(valid_from=s["records"][0]["expires_at"]),
            lambda s: s["records"].append(copy.deepcopy(s["records"][0])),
            lambda s: s.update(records=[s["records"][0]] * 129),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = copy.deepcopy(self.snapshot)
                mutate(value)
                self.closed(self.read(self.write(value)), "INVALID")

    def test_malformed_duplicate_keys_utf8_and_oversize(self):
        for raw in [b'{"schema":1,"schema":2}', b'{"x":NaN}', b"\xff", b"[" * 2000]:
            result = self.read(self.write(raw=raw))
            self.assertIn(result["status"], {"INVALID", "UNAVAILABLE"})
            self.assertNotIn("snapshot", result)
        self.closed(self.read(self.write(raw=b"x" * (reader.LIMIT + 1))), "INVALID")

    def test_invalid_host_configuration_never_starts_worker(self):
        cases = [
            (str(self.path), "bad", "r", "Synthetic", 1),
            (str(self.path), "0" * 64, "", "Synthetic", 1),
            (str(self.path), "0" * 64, "r", "other", 1),
            (str(self.path), "0" * 64, "r", "Synthetic", float("nan")),
            (str(self.path), "0" * 64, "r", "Synthetic", 0),
            (str(self.path), "0" * 64, "r", "Synthetic", 6),
        ]
        with patch.object(reader.subprocess, "run") as run:
            for args in cases:
                self.closed(reader.read_register(*args), "INVALID")
            run.assert_not_called()

    def test_deadline_kills_and_reaps_real_blocked_worker(self):
        digest = self.write()
        original = subprocess.run
        original_popen = subprocess.Popen
        children = []

        def blocked_run(command, **kwargs):
            return original([sys.executable, "-I", "-c", "import time; time.sleep(60)"], **kwargs)

        def capture_child(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child

        start = time.monotonic()
        with patch.object(reader.subprocess, "run", side_effect=blocked_run):
            with patch.object(subprocess, "Popen", side_effect=capture_child):
                result = reader.read_register(str(self.path), digest, "fixture-r1", "Synthetic", 0.1)
        self.closed(result, "TIMEOUT")
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_freshness_is_rechecked_after_ipc(self):
        digest = self.write()
        # Worker uses its own real clock; only the parent's final sample advances.
        with patch.object(reader.time, "time", return_value=self.now + 59):
            self.closed(self.read(digest), "STALE")

    def test_bridge_contract_vector_and_rejection(self):
        snapshot = {
            "schema": reader.SCHEMA, "revision": "r1", "mode": "Synthetic",
            "issued_at": 100, "expires_at": 150,
            "records": [{
                "tenant": "tenant", "actor": "actor", "device": "device",
                "key_ref": "key", "epoch": 1, "valid_from": 90,
                "expires_at": 200, "revoked": False,
            }],
        }
        expected = (
            b"BRIGADE_UNVERIFIED_SNAPSHOT_V1\nSynthetic\nr1\n100\n150\n1\n"
            b"tenant\nactor\ndevice\nkey\n1\n90\n200\n0\n"
        )
        self.assertEqual(reader._encode_bridge(snapshot, "r1", "Synthetic", 120), expected)
        for now in [99, 150]:
            with self.assertRaises(reader.Rejected):
                reader._encode_bridge(snapshot, "r1", "Synthetic", now)
        for field, value in [("revision", "wrong"), ("mode", "LocalObservation")]:
            changed = dict(snapshot, **{field: value})
            with self.assertRaises(reader.Rejected):
                reader._encode_bridge(changed, "r1", "Synthetic", 120)

    def test_bridge_only_exports_successful_fresh_pinned_read(self):
        digest = self.write()
        raw = reader.read_bridge(str(self.path), digest, "fixture-r1", "Synthetic")
        self.assertTrue(raw.startswith((reader.BRIDGE_HEADER + "\nSynthetic\n").encode()))
        self.assertLessEqual(len(raw), reader.BRIDGE_LIMIT)
        with self.assertRaisesRegex(reader.Rejected, "INTEGRITY_MISMATCH"):
            reader.read_bridge(str(self.path), "0" * 64, "fixture-r1", "Synthetic")


if __name__ == "__main__":
    unittest.main()
