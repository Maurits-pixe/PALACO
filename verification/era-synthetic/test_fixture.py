"""Sixteen proposed local WF scenarios, not official contract scenario mappings."""
import copy
import hashlib
import json
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import fixture

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
WORK = HERE / ".runtime"

# These controls exist only in the test process, never in the fixture CLI or request.
WORKER = """
import sys
sys.path.insert(0, sys.argv[1])
import fixture
store = fixture.Store(sys.argv[2], sys.argv[3])
mode = sys.argv[4]
print("READY", flush=True)
sys.stdin.readline()
def checkpoint(stage):
    if stage == mode:
        print(stage, flush=True)
        sys.stdin.readline()
        raise RuntimeError("crash barrier must terminate with the worker")
try:
    if mode == "revoke":
        store.revoke()
        print("REVOKED", flush=True)
    else:
        result = store.submit(fixture.request(), _checkpoint=checkpoint)
        print("COMMITTED", result["commit"], flush=True)
except ValueError:
    print("DENIED", flush=True)
finally:
    store.close()
"""


class SyntheticScenarios(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.db = self.path / "state.sqlite"
        self.store = fixture.Store(self.db, SOURCE)
        self.addCleanup(lambda: self.store.close())

    def restart(self):
        self.store.close()
        self.store = fixture.Store(self.db, SOURCE)

    def export(self):
        return self.store.export()

    def checker(self, envelope, accepted=True, raw=None):
        path = self.path / "input.envelope.json"
        path.write_bytes(raw if raw is not None else fixture.canonical(envelope))
        path.chmod(0o444)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            result = subprocess.run([sys.executable, str(HERE / "verify.py"), str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0 if accepted else 1, result.stdout + result.stderr)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual(json.loads(result.stdout)["result"],
                             "VERIFIED_SYNTHETIC_ONLY" if accepted else "REJECTED")
            return json.loads(result.stdout)
        finally:
            path.chmod(0o644)

    def denied(self, field, value):
        candidate = fixture.request()
        candidate[field] = value
        with self.assertRaises(ValueError):
            self.store.submit(candidate)
        self.assertEqual(self.export()["records"], [])

    def worker(self, mode):
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", WORKER, str(HERE), str(self.db), SOURCE, mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: self.cleanup_child(child))
        self.assertEqual(self.line(child), "READY")
        return child

    @staticmethod
    def cleanup_child(child):
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)

    def line(self, child):
        ready, _, _ = select.select([child.stdout], [], [], 10)
        self.assertTrue(ready, "child did not reach checkpoint")
        return child.stdout.readline().strip()

    @staticmethod
    def start(child):
        child.stdin.write("GO\n")
        child.stdin.flush()

    def finish(self, child):
        stdout, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 0, stderr)
        return stdout.strip()

    @staticmethod
    def reseal(value):
        previous = fixture.digest({k: value[k] for k in ("schema", "source", "flags")})
        for index, record in enumerate(value["records"], 1):
            record["seq"] = index
            record["prev"] = previous
            record["hash"] = fixture.digest({k: record[k] for k in ("seq", "kind", "data", "prev")})
            previous = record["hash"]
        value["proof"]["digest"] = fixture.digest({k: value[k] for k in ("schema", "source", "flags", "records")})
        return value

    def wf_t01_happy_path(self):
        """T01 fixed identity -> evidence -> decision -> authorization -> commit -> proof."""
        receipt = self.store.submit(fixture.request())
        envelope = self.export()
        self.assertEqual([r["kind"] for r in envelope["records"]],
                         ["identity", "evidence", "decision", "authorization", "commit"])
        self.assertEqual(receipt["commit"], envelope["records"][-1]["hash"])
        self.assertFalse(receipt["execution"])
        self.assertEqual(self.checker(envelope)["proof"], envelope["proof"]["digest"])
        with sqlite3.connect(self.db) as other:
            self.assertEqual(other.execute("SELECT count(*) FROM requests").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("PRAGMA synchronous").fetchone()[0], 2)
        self.assertEqual(self.store.db.execute("PRAGMA busy_timeout").fetchone()[0], 2000)

    def wf_t02_denied_identity(self):
        self.denied("identity", "arbitrary-person")

    def wf_t03_denied_evidence(self):
        for value in ("", "unverified", True, {"observation": "fixture-observation-ok"}):
            self.denied("evidence", value)

    def wf_t04_denied_decision(self):
        for value in ("DENY", "EXECUTE", True):
            self.denied("decision", value)

    def wf_t05_denied_authority(self):
        self.denied("authority", "production-admin")

    def wf_t06_denied_world_action_payload(self):
        self.denied("world", "production")
        self.denied("action", "send-payment")
        self.denied("payload", {"fixture": "hello-era", "version": True})
        self.denied("payload", {"fixture": "other", "version": 1})
        self.denied("fault", "before_commit")

    def wf_t07_changed_retry_conflict(self):
        first = self.store.submit(fixture.request())
        for field in ("payload", "identity", "authority", "action", "world", "evidence", "decision"):
            changed = fixture.request()
            changed[field] = "changed"
            with self.assertRaisesRegex(ValueError, "key conflict"):
                self.store.submit(changed)
        self.assertEqual(self.store.submit(fixture.request()), first)
        self.assertEqual(len(self.export()["records"]), 5)

    def wf_t08_historical_replay_after_revoke(self):
        first = self.store.submit(fixture.request())
        self.store.revoke()
        snapshot = self.export()
        self.restart()
        self.assertEqual(self.store.submit(fixture.request()), first)
        self.assertTrue(first["historical_record_only"])
        self.assertFalse(first["execution"])
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.store.submit(fixture.request("new-key"))
        changed = fixture.request()
        changed["world"] = "production"
        with self.assertRaisesRegex(ValueError, "key conflict"):
            self.store.submit(changed)
        self.assertEqual(self.export(), snapshot)
        self.checker(snapshot)

    def wf_t09_persisted_ordering_restart(self):
        self.store.submit(fixture.request("first"))
        self.restart()
        self.store.submit(fixture.request("second"))
        self.store.revoke()
        self.restart()
        self.store.revoke()
        records = self.export()["records"]
        self.assertEqual([r["seq"] for r in records], list(range(1, 12)))
        self.assertEqual(records[-1]["kind"], "revocation")
        with self.assertRaises(ValueError):
            self.store.submit(fixture.request("third"))
        self.checker(self.export())
        with self.assertRaisesRegex(ValueError, "source binding"):
            fixture.Store(self.db, "0" * 40)

    def wf_t10_duplicate_process_concurrency(self):
        first, second = self.worker("commit"), self.worker("commit")
        self.start(first)
        self.start(second)
        left, right = self.finish(first), self.finish(second)
        self.assertTrue(left.startswith("COMMITTED "))
        self.assertEqual(left, right)
        self.restart()
        self.assertEqual(len(self.export()["records"]), 5)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM requests").fetchone()[0], 1)
        self.checker(self.export())

    def wf_t11_commit_revoke_serialization(self):
        commit, revoke = self.worker("commit"), self.worker("revoke")
        self.start(commit)
        self.start(revoke)
        result, revoked = self.finish(commit), self.finish(revoke)
        self.assertEqual(revoked, "REVOKED")
        self.restart()
        records = self.export()["records"]
        if result.startswith("COMMITTED "):
            self.assertEqual([r["kind"] for r in records],
                             ["identity", "evidence", "decision", "authorization", "commit", "revocation"])
            self.assertIn(self.store.submit(fixture.request())["commit"], result)
            self.checker(self.export())
        else:
            self.assertEqual(result, "DENIED")
            self.assertEqual([r["kind"] for r in records], ["revocation"])
            with self.assertRaises(ValueError):
                self.store.submit(fixture.request())
            # A revoked-only log has no committed proof and is intentionally rejected.
            self.checker(self.export(), accepted=False)
        with self.assertRaises(ValueError):
            self.store.submit(fixture.request("later"))

    def wf_t12_precommit_process_death(self):
        child = self.worker("before_commit")
        self.start(child)
        self.assertEqual(self.line(child), "before_commit")
        # Another connection cannot see any partial chain or idempotency row.
        self.assertEqual(self.export()["records"], [])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM requests").fetchone()[0], 0)
        started = time.monotonic()
        with self.assertRaises(sqlite3.OperationalError):
            self.store.revoke()
        self.assertLess(time.monotonic() - started, 5)
        child.kill()
        child.communicate(timeout=10)
        self.assertLess(child.returncode, 0)
        self.restart()
        self.assertEqual(self.export()["records"], [])
        self.store.submit(fixture.request())
        self.checker(self.export())

    def wf_t13_postcommit_process_death(self):
        child = self.worker("after_commit")
        self.start(child)
        self.assertEqual(self.line(child), "after_commit")
        snapshot = self.export()
        self.assertEqual(len(snapshot["records"]), 5)
        child.kill()
        child.communicate(timeout=10)
        self.assertLess(child.returncode, 0)
        self.restart()
        receipt = self.store.submit(fixture.request())
        self.assertEqual(receipt["commit"], snapshot["records"][-1]["hash"])
        self.assertEqual(self.export(), snapshot)
        self.checker(snapshot)

    def wf_t14_tamper_strict_json_types(self):
        self.store.submit(fixture.request())
        good = self.export()
        mutations = [
            lambda v: v.update(schema="UNKNOWN"),
            lambda v: v.update(extra=False),
            lambda v: v["flags"].update(execution=0),
            lambda v: v["flags"].update(synthetic_only=1),
            lambda v: v["source"].update(commit="fake"),
            lambda v: v["proof"].update(authenticity=0),
            lambda v: v["records"][0].update(seq=True),
            lambda v: v["records"][0].update(hash="0" * 64),
            lambda v: v["records"][0].update(data=[]),
            lambda v: v["records"].append(None),
            lambda v: v.update(records=True),
            lambda v: v.update(proof=[]),
        ]
        for mutate in mutations:
            candidate = copy.deepcopy(good)
            mutate(candidate)
            self.checker(candidate, accepted=False)
        for raw in (b'{"schema":1,"schema":2}', b'NaN', b'[]', b'null', b'{',
                    b'{"x":Infinity}', b"\xff", b" " * (1_048_576 + 1)):
            self.checker(None, accepted=False, raw=raw)
        raw = fixture.canonical(good).replace(
            b'"version":1', b'"version":1,"version":1')
        self.checker(None, accepted=False, raw=raw)
        # A fully rehashed boolean sequence must fail on type, not just checksum.
        candidate = copy.deepcopy(good)
        candidate["records"][0]["seq"] = True
        record = candidate["records"][0]
        record["hash"] = fixture.digest({k: record[k] for k in ("seq", "kind", "data", "prev")})
        candidate["proof"]["digest"] = fixture.digest(
            {k: candidate[k] for k in ("schema", "source", "flags", "records")})
        self.checker(candidate, accepted=False)
        for field, value in (("execution", 0), ("synthetic_only", 1), ("release", 0)):
            candidate = copy.deepcopy(good)
            candidate["flags"][field] = value
            self.checker(self.reseal(candidate), accepted=False)
        for candidate in ({**good, "records": [{}] * 1001}, {**good, "records": []}):
            candidate["proof"] = {**good["proof"], "digest": fixture.digest(
                {k: candidate[k] for k in ("schema", "source", "flags", "records")})}
            self.checker(candidate, accepted=False)
        self.checker(good)

    def wf_t15_missing_link_decision_rejection(self):
        self.store.submit(fixture.request())
        good = self.export()
        candidates = []
        for index in range(5):
            missing = copy.deepcopy(good)
            del missing["records"][index]
            candidates.append(self.reseal(missing))
        for index, field, value in (
            (1, "identity", "0" * 64),
            (2, "decision", "EXECUTE"),
            (3, "authority", "production-admin"),
            (3, "execution", True),
            (4, "request_hash", "0" * 64),
        ):
            candidate = copy.deepcopy(good)
            candidate["records"][index]["data"][field] = value
            candidates.append(self.reseal(candidate))
        for field, value in (("world", "production"), ("action", "send"),
                             ("payload", {"fixture": "hello-era", "version": True})):
            candidate = copy.deepcopy(good)
            candidate["records"][4]["data"]["request"][field] = value
            candidates.append(self.reseal(candidate))
        candidate = copy.deepcopy(good)
        candidate["records"][0], candidate["records"][1] = candidate["records"][1], candidate["records"][0]
        candidates.append(self.reseal(candidate))
        self.store.revoke()
        revoked = self.export()
        candidate = copy.deepcopy(revoked)
        candidate["records"].extend(copy.deepcopy(good["records"]))
        candidates.append(self.reseal(candidate))
        for candidate in candidates:
            self.checker(candidate, accepted=False)

    def wf_t16_cli_demo_and_separate_readonly_checker(self):
        db, output = self.path / "demo.sqlite", self.path / "demo.envelope.json"
        result = subprocess.run(
            [sys.executable, str(HERE / "fixture.py"), "demo", "--db", str(db),
             "--envelope", str(output), "--source-commit", SOURCE],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["records"], 6)
        envelope = json.loads(output.read_text())
        self.assertEqual(envelope["source"]["commit"], SOURCE)
        db.unlink()
        self.checker(envelope)
        # Checker implementation has no runtime import and receives no database.
        checker_source = (HERE / "verify.py").read_text()
        self.assertNotIn("import fixture", checker_source)
        self.assertNotIn("import sqlite3", checker_source)


def load_tests(loader, tests, pattern):
    names = sorted(name for name in dir(SyntheticScenarios) if name.startswith("wf_t"))
    assert len(names) == 16
    return unittest.TestSuite(SyntheticScenarios(name) for name in names)


if __name__ == "__main__":
    unittest.main()
