"""Exercise evidence rejection against disposable copies of one real run."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

root = Path(__file__).resolve().parents[1]
repo = root.parents[2]
summary = json.loads(Path(sys.argv[1]).read_text())
runs = repo / "evidence/hara/b-d013/runs"
original = runs / summary["runId"]
results = []

def probe(name, expected, edit):
    run_id = str(uuid.uuid4())
    target = runs / run_id
    shutil.copytree(original, target)
    try:
        candidate = copy.deepcopy(summary)
        candidate["runId"] = run_id
        manifest = json.loads((target / "result.json").read_text())
        manifest["runId"] = run_id
        edit(target, candidate, manifest)
        (target / "result.json").write_text(json.dumps(manifest))
        with tempfile.TemporaryDirectory(prefix="hara-check-") as temp:
            input_path = Path(temp) / "summary.json"
            input_path.write_text(json.dumps(candidate))
            output = Path(temp) / "output.json"
            with output.open("w") as stream:
                child = subprocess.run(
                    ["node", str(root / "tools/check-evidence.mjs"), str(input_path)],
                    stdout=stream, stderr=stream, check=False,
                )
            observed = json.loads(output.read_text())
        assert child.returncode == (0 if expected == "PASS" else 1), (name, observed)
        assert (observed.get("verification") if expected == "PASS" else observed.get("code")) == expected, (name, observed)
        results.append({"name": name, "expected": expected, "result": "PASS"})
    finally:
        shutil.rmtree(target)

probe("valid complete copy", "PASS", lambda *_: None)
probe("changed TAP bytes", "ARTIFACT_HASH_MISMATCH", lambda path, *_: (path / "tests.tap").write_text("tampered"))
def wrong_counts(path, candidate, manifest):
    candidate["counts"]["tests"] = manifest["counts"]["tests"] = 21
probe("forged count in both summaries", "COUNT_MISMATCH", wrong_counts)
probe("incomplete source inventory", "SOURCE_HASH_MISMATCH", lambda path, candidate, manifest: manifest["sourceHashes"].pop(next(iter(manifest["sourceHashes"]))))
def missing_trace(path, candidate, manifest):
    (path / "B12.json").unlink()
    manifest["artifacts"].pop("B12.json")
probe("trace removed from files and manifest", "REQUIRED_ARTIFACT_MISSING", missing_trace)
def symlink(path, *_):
    (path / "tests.tap").unlink()
    (path / "tests.tap").symlink_to(original / "tests.tap")
probe("symlink artifact", "EVIDENCE_SYMLINK", symlink)
probe("run path traversal", "INVALID_RUN_ID", lambda path, candidate, manifest: candidate.update(runId="../../outside"))
print(json.dumps({"tests": len(results), "pass": len(results), "fail": 0, "probes": results}))
