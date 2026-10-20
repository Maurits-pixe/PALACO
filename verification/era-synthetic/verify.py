"""Separate offline checker implementation, not independent human validation.

Reads only envelopes and optional receipts; imports no runtime fixture or database.
SHA256 consistency is not authentication, signature verification or provenance.
"""
import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path

LIMIT = 1_048_576
_UNSET = object()


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


def sha(value):
    return hashlib.sha256(encode(value)).hexdigest()


def identical(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(identical(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(identical(a, b) for a, b in zip(actual, expected))
    return actual == expected


def require(condition):
    if not condition:
        raise ValueError("invalid synthetic envelope")


def keys(value, names):
    require(type(value) is dict and value.keys() == set(names))


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError("non-JSON number")


def _load_envelope(path, *, limit=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= limit)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
    finally:
        os.close(fd)
    require(len(raw) <= limit)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


def _verify_envelope(value, *, expected_source_commit=_UNSET, expected_proof=_UNSET):
    keys(value, ["schema", "source", "flags", "records", "proof"])
    require(identical(value["schema"], "ERA_SYNTHETIC_V1"))
    keys(value["source"], ["repository", "commit"])
    require(identical(value["source"]["repository"], "https://github.com/Maurits-pixe/PALACO"))
    commit = value["source"]["commit"]
    require(type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit) is not None)
    require(identical(value["flags"], {"synthetic_only": True, "execution": False, "release": False}))
    records = value["records"]
    require(type(records) is list and 5 <= len(records) <= 1000)
    body = {k: value[k] for k in ("schema", "source", "flags", "records")}
    require(identical(value["proof"], {"algorithm": "SHA256", "digest": sha(body), "authenticity": False}))
    previous = sha({k: value[k] for k in ("schema", "source", "flags")})
    position = 0
    seen = set()
    revoked = False

    def consume(kind, data):
        nonlocal position, previous
        require(position < len(records))
        expected = {"seq": position + 1, "kind": kind, "data": data, "prev": previous}
        expected["hash"] = sha(expected)
        require(identical(records[position], expected))
        previous = expected["hash"]
        position += 1
        return previous

    while position < len(records):
        record = records[position]
        keys(record, ["seq", "kind", "data", "prev", "hash"])
        if record["kind"] == "revocation":
            require(not revoked)
            consume("revocation", {"authority": "synthetic-recorder", "execution": False})
            revoked = True
            continue
        require(not revoked)
        keys(record["data"], ["request_key", "identity"])
        key = record["data"]["request_key"]
        require(type(key) is str and re.fullmatch(r"[a-z0-9-]{1,48}", key) is not None and key not in seen)
        seen.add(key)
        # Reconstruct the only accepted decision from fixed evidence and identity,
        # rather than trusting the producer's reported decision or request hash.
        request = {
            "request_key": key, "identity": "synthetic-alice", "world": "WORLD-SYNTHETIC-1",
            "action": "record-fixture", "authority": "synthetic-recorder",
            "evidence": "fixture-observation-ok", "decision": "ALLOW_SYNTHETIC",
            "payload": {"fixture": "hello-era", "version": 1},
        }
        identity = consume("identity", {"request_key": key, "identity": "synthetic-alice"})
        evidence = consume("evidence", {"identity": identity, "evidence": "fixture-observation-ok"})
        decision = consume("decision", {"evidence": evidence, "decision": "ALLOW_SYNTHETIC"})
        authority = consume("authorization", {"decision": decision, "authority": "synthetic-recorder",
                                             "execution": False})
        consume("commit", {"authorization": authority, "request": request,
                           "request_hash": sha(request), "execution": False})
    require(bool(seen))
    require(expected_source_commit is _UNSET or expected_source_commit == commit)
    require(expected_proof is _UNSET or expected_proof == value["proof"]["digest"])
    return {"result": "VERIFIED_SYNTHETIC_ONLY", "records": len(records),
            "source_commit": commit, "proof": value["proof"]["digest"],
            "source_anchor_supplied": expected_source_commit is not _UNSET,
            "source_anchor_matched": True if expected_source_commit is not _UNSET else None,
            "proof_anchor_supplied": expected_proof is not _UNSET,
            "proof_anchor_matched": True if expected_proof is not _UNSET else None,
            "execution": False, "authenticity": False}


def verify(path, *, expected_source_commit=_UNSET, expected_proof=_UNSET,
           previous_envelope=_UNSET, expected_previous_proof=_UNSET, review_summary=False,
           receipt=_UNSET):
    require(type(review_summary) is bool)
    check_receipt = receipt is not _UNSET
    require(not (review_summary or check_receipt) or
            (expected_source_commit is not _UNSET and expected_proof is not _UNSET))
    if check_receipt:
        require(receipt is not None)
        try:
            receipt_path = Path(receipt)
        except TypeError as error:
            raise ValueError("invalid receipt path") from error
    continuity = previous_envelope is not _UNSET
    require(continuity == (expected_previous_proof is not _UNSET))
    require(not continuity or previous_envelope is not None)
    for anchor, length in ((expected_source_commit, 40), (expected_proof, 64),
                          (expected_previous_proof, 64)):
        if anchor is not _UNSET:
            require(type(anchor) is str and re.fullmatch(r"[0-9a-f]{%d}" % length, anchor) is not None)
    current_path = Path(path)
    require(not check_receipt or receipt_path != current_path)
    current = _load_envelope(current_path)
    result = _verify_envelope(current, expected_source_commit=expected_source_commit,
                             expected_proof=expected_proof)
    if continuity:
        previous_path = Path(previous_envelope)
        require(not check_receipt or receipt_path != previous_path)
        if previous_path == current_path:
            previous = current
        else:
            previous = _load_envelope(previous_path)
            _verify_envelope(previous)
        require(previous["proof"]["digest"] == expected_previous_proof)
        require(all(identical(current[k], previous[k]) for k in ("schema", "source", "flags")))
        count = len(previous["records"])
        require(len(current["records"]) >= count)
        require(identical(current["records"][:count], previous["records"]))
        added = len(current["records"]) - count
        result.update(previous_proof=previous["proof"]["digest"], previous_records=count,
                     added_records=added, continuity="EXTENDED" if added else "UNCHANGED",
                     previous_proof_anchor_supplied=True, previous_proof_anchor_matched=True)
    if review_summary:
        records = current["records"]
        require(records[-1]["kind"] == "revocation")
        result["review_summary"] = {
            "schema": "ERA_SYNTHETIC_REVIEW_V1",
            "source_commit": result["source_commit"], "proof": result["proof"],
            "committed_requests": sum(record["kind"] == "commit" for record in records),
            "records": len(records), "revocation_sequence": records[-1]["seq"],
            "synthetic_only": True, "execution": False, "authenticity": False,
            "release_authorized": False, "release_status": "HOLD",
            "decision_boundary": "ADVISORY — HUMAN DECISION REQUIRED",
            "open_gates": ["canonical_contract_conformance", "independent_external_verification",
                          "operational_authorization", "human_release_decision"],
        }
    if check_receipt:
        supplied = _load_envelope(receipt_path, limit=4096)
        matched = None
        for record in current["records"]:
            if record["kind"] != "commit":
                continue
            expected = {"commit": record["hash"], "request_hash": record["data"]["request_hash"],
                        "historical_record_only": True, "execution": False}
            if identical(supplied, expected):
                matched = record
                break
        require(matched is not None)
        result["receipt_verification"] = {
            "result": "VERIFIED_HISTORICAL_RECEIPT",
            "request_key": matched["data"]["request"]["request_key"],
            "commit_sequence": matched["seq"], "commit": matched["hash"],
            "request_hash": matched["data"]["request_hash"],
            "historical_record_only": True, "execution": False, "authenticity": False,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("envelope", type=Path)
    parser.add_argument("--expected-source-commit", help="caller-supplied lowercase 40-hex revision")
    parser.add_argument("--expected-proof", help="caller-supplied lowercase 64-hex digest")
    parser.add_argument("--previous-envelope", type=Path, help="externally retained previous envelope")
    parser.add_argument("--expected-previous-proof", help="caller-held trusted previous 64-hex digest")
    parser.add_argument("--review-summary", action="store_true",
                        help="local advisory summary; requires both current anchors and terminal revocation")
    parser.add_argument("--receipt", type=Path,
                        help="retained historical producer receipt; requires both current anchors")
    args = parser.parse_args()
    anchors = {}
    if args.expected_source_commit is not None:
        anchors["expected_source_commit"] = args.expected_source_commit
    if args.expected_proof is not None:
        anchors["expected_proof"] = args.expected_proof
    if args.previous_envelope is not None:
        anchors["previous_envelope"] = args.previous_envelope
    if args.expected_previous_proof is not None:
        anchors["expected_previous_proof"] = args.expected_previous_proof
    if args.receipt is not None:
        anchors["receipt"] = args.receipt
    try:
        print(json.dumps(verify(args.envelope, review_summary=args.review_summary, **anchors), sort_keys=True))
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError):
        print('{"result":"REJECTED"}')
        raise SystemExit(1)


if __name__ == "__main__":
    main()
