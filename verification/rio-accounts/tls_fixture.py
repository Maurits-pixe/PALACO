#!/usr/bin/env python3
"""Owned Linux-CI TLS storage/router proof; requires the local synthetic IdP fixture.

Never launches the browser service, changes its runtime profile, or enrolls accounts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RUNTIME = ROOT / ".tls-runtime"
COMPOSE = ROOT / "tls-compose.yaml"
MANIFEST = REPO / "services/rio-accounts/Cargo.toml"
TEST = "storage::tests::postgres_tls_store_contract"
TESTS = (
    (TEST, "test.log"),
    ("tls_service_tests::postgres_tls_service_contract", "service-test.log"),
)
LIMIT = 1_048_576
PROJECT = re.compile(r"rio-accounts-tls-[0-9a-f]{16}")
FILES = (
    ".owner.json", "compose.env", "password",
    "ca.key", "ca.pem", "ca.der", "other-ca.key", "other-ca.pem", "other-ca.der",
    "server.key", "server.csr", "server.pem", "server-extensions.cnf",
    "openssl.cnf", "pg_hba.conf", "plain-pg_hba.conf", "commands.log", "test.log",
    "service-test.log", "inventory.log",
)
TLS_ENV = ("RIO_PG_TLS_PASSWORD", "RIO_PG_TLS_CA_DER", "RIO_PG_TLS_OTHER_CA_DER")
FAILURES = frozenset({
    "PREPARATION_FAILED", "START_FAILED", "READINESS_FAILED",
    "RUST_TEST_FAILED", "CLEANUP_FAILED", "CANCELLED", "UNEXPECTED_FAILURE",
})
READY_SCRIPT = (
    'PGPASSWORD="$(cat /run/rio-proof/password)"; export PGPASSWORD; '
    'exec psql --no-password --host=/var/run/postgresql --username=rio_dev '
    '--dbname=rio_synthetic_tls --tuples-only --no-align --command="SELECT 1"'
)


class FixtureFailure(Exception):
    """A fixed public failure category, never a subprocess exception or private value."""
    def __init__(self, code: str):
        self.code = code if code in FAILURES else "UNEXPECTED_FAILURE"
        super().__init__(self.code)


@dataclass
class Owner:
    directory: Path
    project: str
    token: str
    identity: tuple[int, int]
    files: dict[str, tuple[int, int]] = field(default_factory=dict)
    marker_ready: bool = False
    namespace_attempted: bool = False


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _marker(owner: Owner) -> bytes:
    return (json.dumps({
        "schemaVersion": "RIO_TLS_FIXTURE_OWNER_V1",
        "project": owner.project,
        "ownerToken": owner.token,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _directory(owner: Owner) -> None:
    if owner.directory != RUNTIME or owner.directory.parent.resolve() != ROOT.resolve():
        raise FixtureFailure("CLEANUP_FAILED")
    metadata = owner.directory.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _identity(metadata) != owner.identity
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
        or not PROJECT.fullmatch(owner.project)
        or not re.fullmatch(r"[0-9a-f]{64}", owner.token)
    ):
        raise FixtureFailure("CLEANUP_FAILED")


def _open_owned(owner: Owner, name: str, flags: int) -> int:
    _directory(owner)
    if name not in FILES or name not in owner.files:
        raise FixtureFailure("CLEANUP_FAILED")
    descriptor = os.open(owner.directory / name, flags | os.O_NOFOLLOW)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or _identity(metadata) != owner.files[name]
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        os.close(descriptor)
        raise FixtureFailure("CLEANUP_FAILED")
    return descriptor


def _write_new(owner: Owner, name: str, content: bytes) -> None:
    _directory(owner)
    if name not in FILES or name in owner.files:
        raise FixtureFailure("PREPARATION_FAILED")
    descriptor = os.open(
        owner.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    metadata = os.fstat(descriptor)
    owner.files[name] = _identity(metadata)
    with os.fdopen(descriptor, "wb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(content)


def _read_owned(owner: Owner, name: str, limit: int = LIMIT) -> bytes:
    descriptor = _open_owned(owner, name, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as source:
        if os.fstat(source.fileno()).st_size > limit:
            raise FixtureFailure("UNEXPECTED_FAILURE")
        value = source.read(limit + 1)
    if len(value) > limit:
        raise FixtureFailure("UNEXPECTED_FAILURE")
    return value


def _owned(owner: Owner) -> None:
    _directory(owner)
    if owner.marker_ready and _read_owned(owner, ".owner.json", 2048) != _marker(owner):
        raise FixtureFailure("CLEANUP_FAILED")


def _environment() -> dict[str, str]:
    values = os.environ.copy()
    for name in tuple(values):
        if (
            name.startswith(("RIO_PG_", "RIO_DEV_", "PG", "COMPOSE_"))
            or name in {
                "RIO_TLS_RUNTIME_DIR", "OPENSSL_CONF", "DOCKER_HOST", "DOCKER_CONTEXT",
                "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
            }
        ):
            values.pop(name, None)
    return values


def _run_private(
    owner: Owner, arguments: list[str], *, log: str = "commands.log",
    timeout: int = 30, environment: dict[str, str] | None = None,
) -> int:
    _owned(owner)
    descriptor = _open_owned(owner, log, os.O_WRONLY | os.O_APPEND)
    with os.fdopen(descriptor, "ab") as output:
        if os.fstat(output.fileno()).st_size > LIMIT:
            raise FixtureFailure("UNEXPECTED_FAILURE")
        completed = subprocess.run(
            arguments, cwd=REPO, env=environment if environment is not None else _environment(),
            stdout=output, stderr=subprocess.STDOUT, check=False, timeout=timeout,
        )
        if os.fstat(output.fileno()).st_size > LIMIT:
            raise FixtureFailure("UNEXPECTED_FAILURE")
    return completed.returncode


def _compose(owner: Owner, *arguments: str) -> list[str]:
    _owned(owner)
    return [
        "docker", "--host", "unix:///var/run/docker.sock", "compose", "--project-name", owner.project,
        "--env-file", str(owner.directory / "compose.env"),
        "--file", str(COMPOSE), *arguments,
    ]


def _prepare(owner: Owner) -> None:
    runtime_path = str(owner.directory.resolve())
    if any(ord(char) <= 32 or char in "'\"\\$#=" for char in runtime_path):
        raise FixtureFailure("PREPARATION_FAILED")
    _write_new(owner, ".owner.json", _marker(owner))
    owner.marker_ready = True
    contents = {
        "compose.env": ("RIO_TLS_RUNTIME_DIR=" + runtime_path + "\n").encode("utf-8"),
        "password": (secrets.token_hex(32) + "\n").encode("ascii"),
        "openssl.cnf": (
            "[req]\nprompt=no\ndistinguished_name=dn\n"
            "[dn]\nCN=RIO synthetic TLS proof\n"
        ).encode("ascii"),
        "server-extensions.cnf": (
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectAltName=DNS:localhost\n"
        ).encode("ascii"),
        "pg_hba.conf": (
            "local all all scram-sha-256\n"
            "hostnossl all all 0.0.0.0/0 reject\n"
            "hostnossl all all ::/0 reject\n"
            "hostssl all all 0.0.0.0/0 scram-sha-256\n"
            "hostssl all all ::/0 scram-sha-256\n"
        ).encode("ascii"),
        "plain-pg_hba.conf": (
            "local all all scram-sha-256\n"
            "host all all 0.0.0.0/0 scram-sha-256\n"
            "host all all ::/0 scram-sha-256\n"
        ).encode("ascii"),
    }
    for name in FILES:
        if name != ".owner.json":
            _write_new(owner, name, contents.get(name, b""))
    for prefix, label in (("ca", "RIO synthetic TLS proof CA A"), ("other-ca", "RIO synthetic TLS proof CA B")):
        key = str(owner.directory / (prefix + ".key"))
        certificate = str(owner.directory / (prefix + ".pem"))
        command = [
            "openssl", "req", "-config", str(owner.directory / "openssl.cnf"),
            "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-days", "1", "-subj", "/CN=" + label,
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", key, "-out", certificate,
        ]
        if _run_private(owner, command) != 0:
            raise FixtureFailure("PREPARATION_FAILED")
        if _run_private(owner, [
            "openssl", "x509", "-in", certificate, "-outform", "DER",
            "-out", str(owner.directory / (prefix + ".der")),
        ]) != 0:
            raise FixtureFailure("PREPARATION_FAILED")
    if _run_private(owner, [
        "openssl", "req", "-config", str(owner.directory / "openssl.cnf"),
        "-new", "-newkey", "rsa:2048", "-nodes",
        "-subj", "/CN=localhost", "-keyout", str(owner.directory / "server.key"),
        "-out", str(owner.directory / "server.csr"),
    ]) != 0:
        raise FixtureFailure("PREPARATION_FAILED")
    if _run_private(owner, [
        "openssl", "x509", "-req", "-in", str(owner.directory / "server.csr"),
        "-CA", str(owner.directory / "ca.pem"), "-CAkey", str(owner.directory / "ca.key"),
        "-set_serial", "1", "-days", "1", "-sha256",
        "-extfile", str(owner.directory / "server-extensions.cnf"),
        "-out", str(owner.directory / "server.pem"),
    ]) != 0:
        raise FixtureFailure("PREPARATION_FAILED")


def _wait_ready(owner: Owner) -> None:
    pending = {"postgres_tls", "postgres_plain"}
    deadline = time.monotonic() + 60
    while pending and time.monotonic() < deadline:
        for service in sorted(pending):
            result = _run_private(
                owner, _compose(owner, "exec", "-T", service, "sh", "-ceu", READY_SCRIPT),
                timeout=10,
            )
            if result == 0:
                pending.remove(service)
        if pending:
            time.sleep(0.5)
    if pending:
        raise FixtureFailure("READINESS_FAILED")


def _run_rust_test(owner: Owner, test: str, log: str) -> None:
    if (test, log) not in TESTS or _read_owned(owner, log):
        raise FixtureFailure("RUST_TEST_FAILED")
    environment = _environment()
    password = _read_owned(owner, "password", 128).decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", password):
        raise FixtureFailure("RUST_TEST_FAILED")
    environment.update({
        "CARGO_TERM_COLOR": "never",
        "RIO_PG_TLS_PASSWORD": password,
        "RIO_PG_TLS_CA_DER": str(owner.directory / "ca.der"),
        "RIO_PG_TLS_OTHER_CA_DER": str(owner.directory / "other-ca.der"),
    })
    result = _run_private(owner, [
        "cargo", "test", "--manifest-path", str(MANIFEST), "--locked", test,
        "--", "--ignored", "--exact", "--color=never",
    ], log=log, timeout=180, environment=environment)
    output = _read_owned(owner, log).decode("utf-8", errors="replace")
    passed = re.search(
        r"^test " + re.escape(test) + r" \.\.\. ok\r?$", output, re.MULTILINE
    )
    one_case = re.search(
        r"^test result: ok\. 1 passed; 0 failed; 0 ignored;", output, re.MULTILINE
    )
    if result != 0 or passed is None or one_case is None:
        raise FixtureFailure("RUST_TEST_FAILED")


def _namespace_empty(owner: Owner) -> bool:
    _owned(owner)
    label = "label=com.docker.compose.project=" + owner.project
    for operation in (
        ["ps", "--all", "--quiet"],
        ["network", "ls", "--quiet"],
        ["volume", "ls", "--quiet"],
    ):
        if _run_private(owner, [
            "docker", "--host", "unix:///var/run/docker.sock", *operation, "--filter", label,
        ], log="inventory.log", timeout=30) != 0:
            return False
    return _read_owned(owner, "inventory.log").strip() == b""


def _cleanup(owner: Owner) -> tuple[bool, bool]:
    namespace_closed = not owner.namespace_attempted
    private_files_removed = False
    try:
        _owned(owner)
        if owner.namespace_attempted:
            try:
                namespace_closed = (
                    _run_private(
                        owner, _compose(owner, "down", "--volumes", "--remove-orphans"), timeout=90
                    ) == 0
                    and _namespace_empty(owner)
                )
            except (Exception, KeyboardInterrupt):
                namespace_closed = False
        # No recursive deletion and no paths or file list supplied by metadata.
        _owned(owner)
        for name, expected in tuple(owner.files.items()):
            metadata = (owner.directory / name).lstat()
            if not stat.S_ISREG(metadata.st_mode) or _identity(metadata) != expected:
                raise FixtureFailure("CLEANUP_FAILED")
        for name in owner.files:
            if name != ".owner.json":
                (owner.directory / name).unlink()
        if ".owner.json" in owner.files:
            (owner.directory / ".owner.json").unlink()
        owner.directory.rmdir()
        private_files_removed = True
    except (Exception, KeyboardInterrupt):
        pass
    return namespace_closed, private_files_removed


def check() -> dict:
    owner = None
    phase = "PREPARATION_FAILED"
    test_results = [{"name": test, "passed": False} for test, _log in TESTS]
    error = None
    namespace_closed = True
    private_files_removed = True
    try:
        # POSIX ownership is enforceable here. This fixture makes no Windows ACL claim.
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise FixtureFailure("PREPARATION_FAILED")
        RUNTIME.mkdir(mode=0o700)
        owner = Owner(
            RUNTIME, "rio-accounts-tls-" + secrets.token_hex(8),
            secrets.token_hex(32), _identity(RUNTIME.lstat()),
        )
        os.chmod(RUNTIME, 0o700)
        _prepare(owner)
        phase = "START_FAILED"
        owner.namespace_attempted = True
        if _run_private(owner, _compose(owner, "up", "--detach"), timeout=120) != 0:
            raise FixtureFailure("START_FAILED")
        phase = "READINESS_FAILED"
        _wait_ready(owner)
        phase = "RUST_TEST_FAILED"
        for result, (test, log) in zip(test_results, TESTS, strict=True):
            _run_rust_test(owner, test, log)
            result["passed"] = True
    except FixtureFailure as failure:
        error = failure.code
    except KeyboardInterrupt:
        error = "CANCELLED"
    except Exception:
        error = phase
    finally:
        if owner is not None:
            namespace_closed, private_files_removed = _cleanup(owner)
    if not namespace_closed or not private_files_removed:
        error = "CLEANUP_FAILED"
    return {
        "schemaVersion": "RIO_TLS_FIXTURE_EVIDENCE_V2",
        "scope": "LOCAL_SYNTHETIC_TLS_TEST",
        "status": "PASS" if all(result["passed"] for result in test_results) and error is None else "FAIL",
        "error": error,
        "createdOwnedFixture": owner is not None,
        "rustTest": TEST,
        "rustTestPassed": test_results[0]["passed"],
        "rustTests": test_results,
        "rustTestsPassed": all(result["passed"] for result in test_results),
        "cleanup": {
            "namespaceClosed": namespace_closed, "privateFilesRemoved": private_files_removed,
        },
        "boundary": {
            "account1": "HOLD", "personalAccounts": False, "contact": False,
            "operativeAuthority": "NONE", "deployment": "HOLD", "humanAcceptance": "HOLD",
        },
    }


def _cancel(_signum, _frame) -> None:
    raise KeyboardInterrupt


def main() -> int:
    if sys.argv[1:] != ["check"]:
        print("RIO_TLS_FIXTURE_REJECTED")
        return 2
    previous = signal.signal(signal.SIGTERM, _cancel)
    try:
        result = check()
    finally:
        signal.signal(signal.SIGTERM, previous)
    for test in result["rustTests"]:
        if test["passed"]:
            print("RIO_TLS_RUST_TEST " + test["name"] + " PASS")
    print("RIO_TLS_FIXTURE_SUMMARY " + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
