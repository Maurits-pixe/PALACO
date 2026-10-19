"""Separate offline checker implementation, not independent human validation.

Reads only an envelope; imports no runtime fixture and opens no database.
SHA256 consistency is not authentication, signature verification or provenance.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

LIMIT = 1_048_576


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


def verify(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    require(len(raw) <= LIMIT)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                       parse_constant=reject_constant)
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
    return {"result": "VERIFIED_SYNTHETIC_ONLY", "records": len(records),
            "proof": value["proof"]["digest"], "execution": False, "authenticity": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("envelope", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.envelope), sort_keys=True))
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError):
        print('{"result":"REJECTED"}')
        raise SystemExit(1)


if __name__ == "__main__":
    main()
