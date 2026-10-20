"""Offline pinned BG05 register ingestion; no issuer trust or contact authority.

Python 3.11+, POSIX local files only. The fixed worker is a separate process,
not an OS security sandbox. Its deadline uses subprocess timeout/kill/reap.
Host configuration must independently supply the digest, revision and mode.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import unicodedata

LIMIT = 65_536
SCHEMA = "BRIGADE_STAGING_REGISTRY_V1"
MODES = {"Synthetic", "LocalObservation"}


class Rejected(ValueError):
    """Sanitized input rejection."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("INVALID")
        result[key] = value
    return result


def _decode(raw):
    def invalid_constant(_):
        raise Rejected("INVALID")
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_pairs,
        parse_constant=invalid_constant,
    )


def _keys(value, expected):
    return type(value) is dict and value.keys() == set(expected.split())


def _reference(value):
    return (
        type(value) is str and bool(value.strip())
        and len(value.encode("utf-8")) <= 256
        and not any(unicodedata.category(char) == "Cc" for char in value)
    )


def _uint(value):
    return type(value) is int and 0 <= value <= 2**64 - 1


def _validate(snapshot, revision, mode, now):
    if not _keys(snapshot, "schema revision mode issued_at expires_at records"):
        raise Rejected("INVALID")
    if snapshot["schema"] != SCHEMA or snapshot["mode"] != mode:
        raise Rejected("INVALID")
    if snapshot["revision"] != revision:
        raise Rejected("REVISION_MISMATCH")
    start, end = snapshot["issued_at"], snapshot["expires_at"]
    if not _uint(start) or not _uint(end) or not 0 < end - start <= 60:
        raise Rejected("INVALID")
    if not start <= now < end:
        raise Rejected("STALE")
    records = snapshot["records"]
    if type(records) is not list or len(records) > 128:
        raise Rejected("INVALID")
    seen = set()
    for record in records:
        if not _keys(record, "tenant actor device key_ref epoch valid_from expires_at revoked"):
            raise Rejected("INVALID")
        if not all(_reference(record[key]) for key in ("tenant", "actor", "device", "key_ref")):
            raise Rejected("INVALID")
        if not all(_uint(record[key]) for key in ("epoch", "valid_from", "expires_at")):
            raise Rejected("INVALID")
        if type(record["revoked"]) is not bool or record["valid_from"] >= record["expires_at"]:
            raise Rejected("INVALID")
        identity = tuple(record[key] for key in ("tenant", "actor", "device", "epoch"))
        if identity in seen:
            raise Rejected("INVALID")
        seen.add(identity)
    return snapshot


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_pinned(path, digest):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise Rejected("UNAVAILABLE")
    file_path = Path(path)
    if not file_path.is_absolute() or ".." in file_path.parts or path.startswith("//"):
        raise Rejected("INVALID")
    # Observed symlinks are refused. Private, stable parent directories remain
    # a host responsibility; this is not a mount or directory-race sandbox.
    for component in (*reversed(file_path.parents), file_path):
        if stat.S_ISLNK(component.lstat().st_mode):
            raise Rejected("UNAVAILABLE")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(file_path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
            raise Rejected("INVALID")
        chunks = []
        size = 0
        while size <= LIMIT:
            chunk = os.read(fd, min(8192, LIMIT + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b"".join(chunks)
        if len(raw) > LIMIT or _stamp(before) != _stamp(os.fstat(fd)):
            raise Rejected("CHANGED")
        if _stamp(before) != _stamp(file_path.lstat()):
            raise Rejected("CHANGED")
    finally:
        os.close(fd)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise Rejected("INTEGRITY_MISMATCH")
    return raw


def _result(reason, snapshot=None):
    result = {
        "status": reason, "disposition": "HOLD", "operativeAuthority": "NONE",
        "canOpenContact": False, "runtimeConnected": False,
        "externalSideEffect": False, "authenticated": False,
    }
    if snapshot is not None:
        result["snapshot"] = snapshot
    return result


def _worker(request):
    try:
        raw = _read_pinned(request["path"], request["sha256"])
        snapshot = _validate(
            _decode(raw), request["revision"], request["mode"], int(time.time()),
        )
        return _result("PINNED_UNVERIFIED", snapshot)
    except Rejected as error:
        return _result(str(error))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return _result("UNAVAILABLE")


def read_register(path, expected_sha256, expected_revision, mode, timeout_seconds=2.0):
    """Return a pinned, unverified snapshot or sanitized HOLD.

    Pin exact UTF-8 file bytes in independent host configuration, never from
    the register itself. No output is persisted. Each invocation starts a fresh
    fixed Python worker; startup, read, hash and parse share a 0 < deadline <= 5s.
    Process creation/kill/reaping still depend on OS scheduling; no hard-real-time
    guarantee or sandbox is claimed. No automatic Rust bridge is implemented.
    """
    if (
        type(path) is not str or not 0 < len(path) <= 4096 or "\0" in path
        or type(expected_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or not _reference(expected_revision)
        or type(mode) is not str or mode not in MODES
        or type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 5
    ):
        return _result("INVALID")
    request = {
        "path": path, "sha256": expected_sha256,
        "revision": expected_revision, "mode": mode,
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).absolute()), "--worker"],
            input=json.dumps(request).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout_seconds, check=False,
            close_fds=True, cwd="/",
        )
        if completed.returncode != 0 or len(completed.stdout) > LIMIT * 4:
            return _result("UNAVAILABLE")
        result = _decode(completed.stdout)
        if result.get("status") != "PINNED_UNVERIFIED":
            reason = result.get("status")
            return _result(reason if reason in {
                "INVALID", "UNAVAILABLE", "CHANGED", "INTEGRITY_MISMATCH",
                "REVISION_MISMATCH", "STALE",
            } else "UNAVAILABLE")
        # Recheck freshness after process/IPC latency; never trust a stale result.
        snapshot = _validate(
            result["snapshot"], expected_revision, mode, int(time.time()),
        )
        return _result("PINNED_UNVERIFIED", snapshot)
    except subprocess.TimeoutExpired:
        # subprocess.run kills and reaps its direct child before raising.
        return _result("TIMEOUT")
    except Rejected as error:
        return _result(str(error))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        return _result("UNAVAILABLE")


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        print(json.dumps(_result("INVALID"), sort_keys=True))
        sys.exit(2)
    try:
        request_bytes = sys.stdin.buffer.read(16_385)
        if len(request_bytes) > 16_384:
            raise Rejected("INVALID")
        output = _worker(_decode(request_bytes))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        output = _result("INVALID")
    sys.stdout.write(json.dumps(output, ensure_ascii=True, separators=(",", ":")))
