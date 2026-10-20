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
    guarantee or sandbox is claimed. Rust does not launch this reader.
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


BRIDGE_HEADER = "BRIGADE_UNVERIFIED_SNAPSHOT_V1"
BRIDGE_LIMIT = 140_000
HOST_CONFIG_LIMIT = 16_384
HOST_SCHEMA = "BRIGADE_READER_HOST_V1"


def _encode_bridge(snapshot, revision, mode, now):
    """Versioned UTF-8 lines, never signed evidence or proof of reader execution."""
    if not _reference(revision) or type(mode) is not str or mode not in MODES:
        raise Rejected("INVALID")
    snapshot = _validate(snapshot, revision, mode, now)
    fields = [
        BRIDGE_HEADER, mode, revision, str(snapshot["issued_at"]),
        str(snapshot["expires_at"]), str(len(snapshot["records"])),
    ]
    for record in snapshot["records"]:
        fields.extend(record[key] for key in ("tenant", "actor", "device", "key_ref"))
        fields.extend(str(record[key]) for key in ("epoch", "valid_from", "expires_at"))
        fields.append("1" if record["revoked"] else "0")
    raw = ("\n".join(fields) + "\n").encode("utf-8")
    if len(raw) > BRIDGE_LIMIT:
        raise Rejected("INVALID")
    return raw


def read_bridge(path, expected_sha256, expected_revision, mode, timeout_seconds=2.0):
    """Read/pin a fresh snapshot and export explicit unverified Rust bridge bytes.

    Raises Rejected with a sanitized category on any read or export failure.
    The original file SHA-256 does not authenticate these transformed bytes.
    Transport must remain host-controlled; no trust marker is encoded.
    """
    result = read_register(path, expected_sha256, expected_revision, mode, timeout_seconds)
    if result["status"] != "PINNED_UNVERIFIED":
        raise Rejected(result["status"])
    try:
        return _encode_bridge(result["snapshot"], expected_revision, mode, int(time.time()))
    except Rejected:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
        raise Rejected("INVALID") from error


def _host_config(raw, expected_mode):
    """Parse host-owned bytes, not a configuration supplied by the register."""
    if type(raw) is not bytes or len(raw) > HOST_CONFIG_LIMIT:
        raise Rejected("INVALID")
    if type(expected_mode) is not str or expected_mode not in MODES:
        raise Rejected("INVALID")
    config = _decode(raw)
    if not _keys(config, "schema role party mode source timeout_seconds"):
        raise Rejected("INVALID")
    if (
        config["schema"] != HOST_SCHEMA or config["role"] != "BG05"
        or config["party"] != "Sender" or config["mode"] != expected_mode
        or not _keys(config["source"], "path sha256 revision")
    ):
        raise Rejected("INVALID")
    source = config["source"]
    path, digest, revision = source["path"], source["sha256"], source["revision"]
    timeout = config["timeout_seconds"]
    if (
        type(path) is not str or not 0 < len(path) <= 4096
        or any(unicodedata.category(char) == "Cc" for char in path)
        or not Path(path).is_absolute() or path.startswith("//") or ".." in Path(path).parts
        or type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not _reference(revision)
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout) or not 0 < timeout <= 5
    ):
        raise Rejected("INVALID")
    return config


def read_configured(raw_config, expected_mode):
    """Host-owned config bytes -> read result. No enrollment or config persistence.

    The caller must independently select mode and protect the config input channel.
    Schema validation is not review, operator authentication or rollback fencing.
    Unknown fields (including credentials/authority flags) are rejected.
    """
    try:
        config = _host_config(raw_config, expected_mode)
        source = config["source"]
        return read_register(
            source["path"], source["sha256"], source["revision"],
            expected_mode, config["timeout_seconds"],
        )
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return _result("INVALID")


def main(arguments):
    """CLI accepts bounded configuration on stdin, never secrets on argv.

    Default configured check emits only sanitized status. Explicit bridge export
    emits unverified context bytes on stdout; route only through a private pipe.
    stdin acquisition is not covered by the register worker's timeout.
    """
    if arguments == ["--worker"]:
        try:
            request_bytes = sys.stdin.buffer.read(HOST_CONFIG_LIMIT + 1)
            if len(request_bytes) > HOST_CONFIG_LIMIT:
                raise Rejected("INVALID")
            output = _worker(_decode(request_bytes))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            output = _result("INVALID")
        sys.stdout.write(json.dumps(output, ensure_ascii=True, separators=(",", ":")))
        return 0
    if (
        len(arguments) != 2 or arguments[0] not in {"--host-check", "--host-bridge"}
        or arguments[1] not in MODES
    ):
        print(json.dumps(_result("INVALID"), sort_keys=True))
        return 2
    result = read_configured(
        sys.stdin.buffer.read(HOST_CONFIG_LIMIT + 1), arguments[1],
    )
    if arguments[0] == "--host-bridge":
        if result["status"] == "PINNED_UNVERIFIED":
            try:
                raw = _encode_bridge(
                    result["snapshot"], result["snapshot"]["revision"],
                    arguments[1], int(time.time()),
                )
                sys.stdout.buffer.write(raw)
                return 0
            except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
                result = _result("STALE")
        # A failed export must never mix JSON diagnostics with bridge stdout.
        print(json.dumps(_result(result["status"]), sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(_result(result["status"]), sort_keys=True))
    return 0 if result["status"] == "PINNED_UNVERIFIED" else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, OverflowError):
        # Broken pipes and other I/O failures expose no paths or source values.
        sys.exit(2)
