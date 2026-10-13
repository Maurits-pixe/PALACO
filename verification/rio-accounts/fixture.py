#!/usr/bin/env python3
"""Prepare and verify the local synthetic Keycloak/PostgreSQL/BFF fixture."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import signal
import ssl
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, HTTPSHandler
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RUNTIME = ROOT / ".runtime"
ISSUER = "http://127.0.0.1:8089/realms/rio-synthetic"
CLIENT_ID = "rio-bff"
CALLBACK = "https://localhost:8088/auth/callback"
SUBJECTS = {
    "alpha": "11111111-1111-4111-8111-111111111111",
    "beta": "22222222-2222-4222-8222-222222222222",
}
PRIVATE_FILES = ("compose.env", "bff.env", "test-credentials.json", "metadata.json", "tls-cert.pem", "tls-key.pem")
GENERATED_FILES = (*PRIVATE_FILES, "rio-synthetic-realm.json")

class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def runtime_path(name: str) -> Path:
    path = RUNTIME / name
    if RUNTIME.is_symlink() or path.is_symlink():
        raise RuntimeError("The fixture refuses symlinked runtime files.")
    return path

def write_new(name: str, text: str, mode: int = 0o600) -> None:
    fd = os.open(runtime_path(name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
        output.write(text)
    if os.name != "nt":
        os.chmod(runtime_path(name), mode)

def user_profile() -> dict:
    # This fixture must never ask for an email/name during login.
    attributes = []
    for name in ("username", "email", "firstName", "lastName"):
        attribute = {
            "name": name,
            "permissions": {"view": ["admin", "user"], "edit": ["admin"]},
            "multivalued": False,
            "validations": {"length": {"max": 255}},
        }
        if name == "username":
            attribute["validations"] = {
                "length": {"min": 3, "max": 64},
                "username-prohibited-characters": {},
                "up-username-not-idn-homograph": {},
            }
        elif name == "email":
            attribute["validations"]["email"] = {}
        attributes.append(attribute)
    # Keycloak 26.8 represents disabled unmanaged attributes by an absent/null policy.
    # DISABLED is a UI label, not an accepted UPConfig enum value.
    return {"attributes": attributes, "groups": []}

def realm(client_secret: str, credentials: dict) -> dict:
    return {
        "id": "rio-synthetic",
        "realm": "rio-synthetic",
        "enabled": True,
        "displayName": "RIO synthetic development fixture",
        "sslRequired": "none",
        "registrationAllowed": False,
        "registrationEmailAsUsername": False,
        "loginWithEmailAllowed": False,
        "resetPasswordAllowed": False,
        "rememberMe": False,
        "verifyEmail": False,
        "editUsernameAllowed": False,
        "bruteForceProtected": True,
        "defaultSignatureAlgorithm": "RS256",
        "accessTokenLifespan": 60,
        "ssoSessionIdleTimeout": 300,
        "ssoSessionMaxLifespan": 900,
        "revokeRefreshToken": True,
        "refreshTokenMaxReuse": 0,
        "eventsEnabled": False,
        "smtpServer": {},
        "identityProviders": [],
        "components": {
            "org.keycloak.userprofile.UserProfileProvider": [
                {
                    "providerId": "declarative-user-profile",
                    "subComponents": {},
                    "config": {"kc.user.profile.config": [json.dumps(user_profile())]},
                }
            ]
        },
        "clients": [
            {
                "clientId": CLIENT_ID,
                "name": "RIO synthetic BFF",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "clientAuthenticatorType": "client-secret",
                "secret": client_secret,
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "authorizationServicesEnabled": False,
                "fullScopeAllowed": False,
                "redirectUris": [CALLBACK],
                "webOrigins": [],
                "defaultClientScopes": [],
                "optionalClientScopes": [],
                "attributes": {
                    "pkce.code.challenge.method": "S256",
                    "id.token.signed.response.alg": "RS256",
                    "oauth2.device.authorization.grant.enabled": "false",
                    "oidc.ciba.grant.enabled": "false",
                },
            }
        ],
        "users": [
            {
                "id": data["subject"],
                "username": data["username"],
                "enabled": True,
                "emailVerified": False,
                "requiredActions": [],
                "credentials": [
                    {"type": "password", "value": data["password"], "temporary": False}
                ],
            }
            for data in credentials.values()
        ],
    }

def prepare() -> None:
    if RUNTIME.is_symlink():
        raise RuntimeError("The fixture refuses a symlinked runtime directory.")
    present = [runtime_path(name).exists() for name in GENERATED_FILES]
    if all(present):
        metadata = json.loads(runtime_path("metadata.json").read_text(encoding="utf-8"))
        if metadata.get("storage") != "POSTGRES_T03":
            raise RuntimeError("Prepared runtime predates T03; stop it with fixture.py down first.")
        print("Synthetic runtime already prepared; reuse until fixture.py down.")
        return
    if any(present):
        raise RuntimeError("Incomplete runtime. Stop the fixture, then run fixture.py down.")
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        os.chmod(RUNTIME, 0o700)
    if not shutil.which("openssl"):
        raise RuntimeError("OpenSSL is required to generate the one-day loopback certificate.")
    credentials = {
        label: {
            "username": f"TST-{label}",
            "subject": subject,
            "password": secrets.token_urlsafe(24),
        }
        for label, subject in SUBJECTS.items()
    }
    admin_password = secrets.token_urlsafe(32)
    client_secret = secrets.token_hex(32)
    database_password = secrets.token_hex(32)
    database_url = f"postgresql://rio_dev:{database_password}@127.0.0.1:8090/rio_synthetic?sslmode=disable"
    restore_url = f"postgresql://rio_dev:{database_password}@127.0.0.1:8090/rio_synthetic_restore?sslmode=disable"
    project_name = "rio-accounts-synthetic-" + secrets.token_hex(4)
    metadata = {"project": project_name, "issuer": ISSUER, "clientId": CLIENT_ID, "storage": "POSTGRES_T03"}
    write_new("metadata.json", json.dumps(metadata, indent=2) + "\n")
    write_new("test-credentials.json", json.dumps(credentials, indent=2) + "\n")
    write_new(
        "compose.env",
        f"COMPOSE_PROJECT_NAME={project_name}\n"
        f"RIO_RUNTIME_DIR={RUNTIME.as_posix()}\n"
        f"RIO_KC_ADMIN_PASSWORD={admin_password}\n"
        f"RIO_PG_PASSWORD={database_password}\n",
    )
    write_new(
        "bff.env",
        "RIO_DEV_MODE=SYNTHETIC_ONLY\n"
        f"RIO_DEV_CLIENT_SECRET={client_secret}\n"
        f"RIO_DEV_TLS_CERT={runtime_path('tls-cert.pem')}\n"
        f"RIO_DEV_TLS_KEY={runtime_path('tls-key.pem')}\n"
        f"RIO_DEV_DATABASE_URL={database_url}\n"
        f"RIO_PG_TEST_URL={database_url}\n"
        f"RIO_PG_RESTORE_TEST_URL={restore_url}\n",
    )
    write_new("tls-cert.pem", "")
    write_new("tls-key.pem", "")
    certificate = subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "1", "-subj", "/CN=RIO synthetic loopback",
            "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
            "-keyout", str(runtime_path("tls-key.pem")),
            "-out", str(runtime_path("tls-cert.pem")),
        ],
        capture_output=True,
        check=False,
    )
    if certificate.returncode != 0:
        raise RuntimeError("OpenSSL could not generate the loopback certificate.")
    if os.name != "nt":
        for name in ("tls-cert.pem", "tls-key.pem"):
            os.chmod(runtime_path(name), 0o600)
    # A single file bind mount must be readable by Keycloak UID 1000.
    # Host access remains restricted by the owner-only .runtime directory.
    write_new("rio-synthetic-realm.json", json.dumps(realm(client_secret, credentials), indent=2) + "\n", 0o644)
    print("Prepared private synthetic runtime; credentials were not printed.")

def compose_command(*arguments: str) -> list[str]:
    metadata_path = runtime_path("metadata.json")
    if not metadata_path.exists():
        raise RuntimeError("No prepared fixture runtime. Run fixture.py prepare first.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"rio-accounts-synthetic-[0-9a-f]{8}", metadata.get("project", "")):
        raise RuntimeError("Invalid synthetic Compose project; refusing container changes.")
    return [
        "docker", "compose", "--env-file", str(runtime_path("compose.env")),
        "--file", str(ROOT / "compose.yaml"), "--project-name", metadata["project"], *arguments,
    ]

def compose_environment() -> dict:
    env = os.environ.copy()
    # Private dotenv values must not be overridden by inherited host settings.
    for key in ("RIO_PG_PASSWORD", "RIO_KC_ADMIN_PASSWORD", "RIO_RUNTIME_DIR", "COMPOSE_PROJECT_NAME"):
        env.pop(key, None)
    return env

def compose(*arguments: str) -> None:
    env = compose_environment()
    # Allows cleanup of a pre-T03 project without creating or opening a database.
    if arguments and arguments[0] == "down":
        env.setdefault("RIO_PG_PASSWORD", secrets.token_hex(32))
    subprocess.run(compose_command(*arguments), check=True, cwd=ROOT, env=env)

def runtime_secret_values() -> list[str]:
    """Collect every generated password/client secret before handling provider output."""
    values = set()
    for name in ("compose.env", "bff.env"):
        for line in runtime_path(name).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and ("PASSWORD" in key or "SECRET" in key or "DATABASE_URL" in key or "_TEST_URL" in key):
                values.add(value)
    credentials = json.loads(runtime_path("test-credentials.json").read_text(encoding="utf-8"))
    for user in credentials.values():
        values.add(user["password"])
    imported = json.loads(runtime_path("rio-synthetic-realm.json").read_text(encoding="utf-8"))
    for client in imported.get("clients", []):
        if client.get("secret"):
            values.add(client["secret"])
    for user in imported.get("users", []):
        for credential in user.get("credentials", []):
            if credential.get("value"):
                values.add(credential["value"])
    # Browser-stage and process-control bearer material is also private.
    def collect_strings(value):
        if isinstance(value, str):
            values.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect_strings(item)
        elif isinstance(value, list):
            for item in value:
                collect_strings(item)
    for name in ("bff-process.json", "durable-browser-state.json"):
        path = runtime_path(name)
        if path.exists():
            collect_strings(json.loads(path.read_text(encoding="utf-8")))
    return sorted((value for value in values if value), key=len, reverse=True)

def sanitize_provider_output(raw: str, secret_values: list[str]) -> str:
    """Redact runtime values and token-like strings; never return untouched log output."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
    for value in secret_values:
        text = text.replace(value, "[REDACTED]")
        text = text.replace(json.dumps(value)[1:-1], "[REDACTED]")
    text = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED_PRIVATE_KEY]", text,
    )
    # Preserve only known public diagnostic identifiers across generic token scrubbing.
    public_tokens = (
        "username-prohibited-characters", "up-username-not-idn-homograph",
        "person-name-prohibited-characters", "ComponentValidationException",
        "DeclarativeUserProfileProvider", "UnsupportedOperationException",
        "IllegalArgumentException", "PersistenceException",
        "UnmanagedAttributePolicy", "unmanagedAttributePolicy",
        "JdbcSQLIntegrityConstraintViolationException", "JdbcSQLDataException",
    )
    placeholders = {}
    for index, token in enumerate(public_tokens):
        marker = f"<public{index}>"
        if token in text:
            text = text.replace(token, marker)
            placeholders[marker] = token
    text = re.sub(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])",
                  "[REDACTED_TOKEN]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                  "[REDACTED_ADDRESS]", text)
    text = re.sub(r"(?:https?|postgresql)://[^\s\"'<>]+", "[REDACTED_URL]", text)
    for marker, token in placeholders.items():
        text = text.replace(marker, token)
    return "".join(character for character in text
                   if character in "\n\t" or ord(character) >= 32)

def provider_error_details(sanitized: str) -> list[str]:
    """Expose bounded startup error explanations, excluding configuration/data dumps."""
    details = []
    error_level = re.compile(r"(?:^ERROR:|\bERROR\s+\[|^\s*Caused by:)", re.IGNORECASE)
    known_reason = re.compile(
        r"failed to (?:start|import|read|create|initialize|connect)|"
        r"user.?profile|validator|attribute|unknown option|"
        r"componentvalidationexception|illegalargumentexception|"
        r"persistenceexception|jdbcsql|database|permission denied|"
        r"cannot deserialize|unrecognized field|out.?of.?memory",
        re.IGNORECASE,
    )
    for line in sanitized.splitlines():
        if not error_level.search(line) or not known_reason.search(line):
            continue
        # Values/configuration bodies remain private even after redaction.
        if re.search(r'"(?:secret|password|credentials)"\s*:|PRIVATE KEY|INSERT INTO|SELECT .+ FROM',
                     line, re.IGNORECASE):
            detail = "CONFIGURATION_OR_DATABASE_PAYLOAD_REDACTED"
        else:
            detail = re.sub(r"\s+", " ", line).strip()[:900]
        if detail not in details:
            details.append(detail)
        if len(details) == 8:
            break
    return details

def public_port_bindings(raw: object) -> list[dict]:
    """Keep only validated public port/address metadata; never Docker environment."""
    bindings = []
    if not isinstance(raw, dict):
        return bindings
    for container_port, values in raw.items():
        if not isinstance(container_port, str) or not re.fullmatch(r"[0-9]{1,5}/(?:tcp|udp)", container_port):
            continue
        if not 1 <= int(container_port.split("/", 1)[0]) <= 65535:
            continue
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            host_ip, host_port = value.get("HostIp"), value.get("HostPort")
            if not isinstance(host_ip, str) or not isinstance(host_port, str):
                continue
            if not re.fullmatch(r"[0-9]{1,5}", host_port):
                continue
            try:
                host_ip = str(ipaddress.ip_address(host_ip))
            except ValueError:
                continue
            if 1 <= int(host_port) <= 65535:
                bindings.append({"containerPort": container_port, "hostIp": host_ip,
                                 "hostPort": int(host_port)})
    return bindings[:8]

def diagnostics() -> None:
    """Print fixed diagnostic categories only; never raw provider logs/configuration."""
    metadata = json.loads(runtime_path("metadata.json").read_text(encoding="utf-8"))
    project = metadata.get("project", "")
    if not re.fullmatch(r"rio-accounts-synthetic-[0-9a-f]{8}", project):
        raise RuntimeError("Invalid diagnostic project.")
    container = project + "-keycloak-1"
    status = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .State}}\n{{json .NetworkSettings.Ports}}"],
        capture_output=True, text=True, check=False,
    )
    state = {}
    port_bindings = []
    if status.returncode == 0:
        try:
            public_lines = status.stdout.splitlines()
            raw = json.loads(public_lines[0])
            if len(public_lines) > 1:
                port_bindings = public_port_bindings(json.loads(public_lines[1]))
            state = {
                "Running": raw.get("Running") if type(raw.get("Running")) is bool else None,
                "ExitCode": raw.get("ExitCode") if type(raw.get("ExitCode")) is int and 0 <= raw["ExitCode"] <= 255 else None,
                "OOMKilled": raw.get("OOMKilled") if type(raw.get("OOMKilled")) is bool else None,
            }
        except (ValueError, IndexError, TypeError, AttributeError):
            state = {"unavailable": True}
    logs = subprocess.run(
        ["docker", "logs", "--tail", "100", container],
        capture_output=True, text=True, check=False,
    )
    try:
        sanitized = sanitize_provider_output(logs.stdout + logs.stderr, runtime_secret_values())
        error_details = provider_error_details(sanitized)
    except (OSError, ValueError, KeyError, TypeError):
        # Fail closed: incomplete redaction inputs never expose provider messages.
        sanitized = ""
        error_details = ["REDACTION_INPUTS_UNAVAILABLE"]
    data = sanitized.lower()
    categories = {
        "server_listening": "listening on" in data,
        "startup_failed": "failed to start" in data or "error running" in data,
        "unknown_option": "unknown option" in data,
        "database_error": "database" in data and "error" in data,
        "permission_denied": "permission denied" in data,
        "profile_error": "profile" in data and ("error" in data or "invalid" in data),
        "realm_import_error": "import" in data and "error" in data,
        "out_of_memory": "outofmemory" in data or "out of memory" in data,
        "has_error": "error" in data,
    }
    print("RIO_PROVIDER_DIAGNOSTIC " + json.dumps(
        {"state": state, "portBindings": port_bindings,
         "categories": categories, "errorDetails": error_details},
        separators=(",", ":")))
    # A reached HTTP response is public status metadata, never its response content.
    try:
        opener = build_opener(ProxyHandler({}), NoRedirects())
        with opener.open(ISSUER + "/.well-known/openid-configuration", timeout=2) as response:
            print("RIO_DISCOVERY_STATUS " + str(response.status))
    except Exception:
        print("RIO_DISCOVERY_STATUS UNREACHABLE")

def wait_for_discovery(timeout: float = 180) -> None:
    opener = build_opener(ProxyHandler({}), NoRedirects())
    deadline = time.monotonic() + timeout
    url = ISSUER + "/.well-known/openid-configuration"
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=2) as response:
                document = json.load(response)
            if document.get("issuer") == ISSUER:
                print("Synthetic Keycloak discovery is ready.")
                return
        except (URLError, TimeoutError, OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Synthetic Keycloak discovery did not become ready.")

def read_bff_environment() -> dict:
    values = {}
    for line in runtime_path("bff.env").read_text(encoding="utf-8").splitlines():
        if line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


# Fixed local database operations. Values never become process command arguments.
PG_PREFIX = 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec '
DB_NAME = "rio_synthetic"
RESTORE_DB_NAME = "rio_synthetic_restore"
OPTIONAL_RUNTIME_FILES = ("bff-process.json", "bff.log", "db-backup.dump",
                          "durable-browser-state.json")
MAX_BACKUP_BYTES = 16 * 1024 * 1024

def private_compose(*arguments: str, stdin=None, stdout=None, timeout: float = 30):
    return subprocess.run(
        compose_command(*arguments), stdin=stdin,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, cwd=ROOT, env=compose_environment(), timeout=timeout,
    )

def wait_for_database(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = private_compose(
                "exec", "-T", "postgres", "sh", "-ec", PG_PREFIX +
                "psql -X -w -h 127.0.0.1 -U rio_dev -d rio_synthetic -At -c 'SELECT 1'",
                timeout=min(2, max(0.1, deadline - time.monotonic())),
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and result.stdout.strip() == b"1":
            print("Synthetic PostgreSQL authenticated readiness is ready.")
            return
        time.sleep(0.25)
    raise RuntimeError("Synthetic PostgreSQL authenticated readiness failed.")

def stop_database() -> None:
    compose("stop", "--timeout", "5", "postgres")

def start_database() -> None:
    compose("start", "postgres")
    wait_for_database(timeout=10)

def backup_database() -> None:
    path = runtime_path("db-backup.dump")
    if path.exists():
        raise RuntimeError("A private database backup already exists; refusing overwrite.")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as archive:
            result = private_compose(
                "exec", "-T", "postgres", "sh", "-ec", PG_PREFIX +
                "pg_dump -w -h 127.0.0.1 -U rio_dev -d rio_synthetic "
                "--format=custom --schema=rio_synthetic --no-owner --no-acl",
                stdout=archive, timeout=30,
            )
        if result.returncode != 0 or not 1 <= path.stat().st_size <= MAX_BACKUP_BYTES:
            raise RuntimeError("Synthetic database backup failed.")
    except Exception:
        if path.exists():
            path.unlink()
        raise
    print("RIO_DATABASE_BACKUP_CREATED")

def restore_database() -> None:
    # The source database is never dropped or replaced.
    path = runtime_path("db-backup.dump")
    if not path.is_file() or not 1 <= path.stat().st_size <= MAX_BACKUP_BYTES:
        raise RuntimeError("No bounded private synthetic database backup is available.")
    commands = (
        "dropdb -w -h 127.0.0.1 -U rio_dev --if-exists --force rio_synthetic_restore",
        "createdb -w -h 127.0.0.1 -U rio_dev -T template0 rio_synthetic_restore",
    )
    for command in commands:
        result = private_compose("exec", "-T", "postgres", "sh", "-ec",
                                 PG_PREFIX + command, timeout=15)
        if result.returncode != 0:
            raise RuntimeError("Isolated synthetic restore database creation failed.")
    with path.open("rb") as archive:
        result = private_compose(
            "exec", "-T", "postgres", "sh", "-ec", PG_PREFIX +
            "pg_restore -w -h 127.0.0.1 -U rio_dev -d rio_synthetic_restore "
            "--exit-on-error --no-owner --no-acl",
            stdin=archive, timeout=30,
        )
    if result.returncode != 0:
        raise RuntimeError("Isolated synthetic database restore failed.")
    # Verify the native clone is live before the Rust restore guard fences it.
    # The restored database is never opened by a BFF listener.
    run_database_test("postgres_verify_restored_snapshot")
    print("RIO_DATABASE_RESTORE_PROOF_PASSED")

def database_environment() -> dict:
    values = read_bff_environment()
    for key, database in (("RIO_DEV_DATABASE_URL", DB_NAME), ("RIO_PG_TEST_URL", DB_NAME),
                          ("RIO_PG_RESTORE_TEST_URL", RESTORE_DB_NAME)):
        try:
            parsed = urlsplit(values[key])
            valid = (parsed.scheme == "postgresql" and parsed.hostname == "127.0.0.1"
                     and parsed.port == 8090 and parsed.username == "rio_dev"
                     and re.fullmatch(r"[0-9a-f]{64}", parsed.password or "") is not None
                     and parsed.path == "/" + database and parsed.query == "sslmode=disable"
                     and not parsed.fragment)
        except (KeyError, ValueError):
            valid = False
        if not valid:
            raise RuntimeError("Invalid fixed local synthetic database configuration.")
    if (values["RIO_DEV_DATABASE_URL"] != values["RIO_PG_TEST_URL"]
            or values["RIO_PG_RESTORE_TEST_URL"] != values["RIO_DEV_DATABASE_URL"].replace(
                "/rio_synthetic?", "/rio_synthetic_restore?")):
        raise RuntimeError("Synthetic database test URLs differ from the fixed serving credentials.")
    return values

def bff_binary() -> Path:
    binary = REPO / "services" / "rio-accounts" / "target" / "debug" / "rio-accounts-dev"
    if os.name == "nt":
        binary = binary.with_suffix(".exe")
    if not binary.is_file():
        raise RuntimeError("Build services/rio-accounts before starting the synthetic BFF.")
    return binary

def process_identity(pid: int) -> dict | None:
    if sys.platform != "linux":
        raise RuntimeError("Managed BFF restart requires Linux CI; use foreground run-bff elsewhere.")
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat_text.rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {
            "startTicks": fields[19],
            "binary": os.readlink(f"/proc/{pid}/exe"),
            "environment": Path(f"/proc/{pid}/environ").read_bytes(),
        }
    except FileNotFoundError:
        return None

def owned_bff() -> tuple[int, dict] | None:
    path = runtime_path("bff-process.json")
    if not path.exists():
        return None
    metadata = json.loads(path.read_text(encoding="utf-8"))
    pid, token = metadata.get("pid"), metadata.get("processToken", "")
    if type(pid) is not int or pid <= 1 or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise RuntimeError("Invalid BFF process ownership metadata.")
    identity = process_identity(pid)
    if identity is None:
        path.unlink()
        return None
    marker = ("RIO_FIXTURE_PROCESS_TOKEN=" + token).encode("ascii")
    if (identity["binary"] != str(bff_binary().resolve())
            or identity["startTicks"] != metadata.get("startTicks")
            or marker not in identity["environment"].split(b"\0")):
        raise RuntimeError("BFF process ownership mismatch; refusing process control.")
    return pid, metadata

def wait_for_bff(pid: int, timeout: float = 30) -> None:
    context = ssl.create_default_context(cafile=str(runtime_path("tls-cert.pem")))
    opener = build_opener(ProxyHandler({}), NoRedirects(), HTTPSHandler(context=context))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process_identity(pid) is None:
            raise RuntimeError("Synthetic BFF exited before becoming ready.")
        try:
            with opener.open("https://localhost:8088/healthz", timeout=1) as response:
                payload = json.load(response)
            if payload.get("status") == "ok" and payload.get("mode") == "SYNTHETIC_ONLY":
                current = owned_bff()
                if current is None or current[0] != pid:
                    raise RuntimeError("Synthetic BFF generation changed during startup.")
                print("Synthetic HTTPS BFF is ready.")
                return
        except (URLError, OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Synthetic HTTPS BFF readiness failed.")

def start_bff() -> None:
    if sys.platform != "linux":
        raise RuntimeError("Managed BFF restart requires Linux CI; use foreground run-bff elsewhere.")
    if owned_bff() is not None:
        raise RuntimeError("An owned BFF process is already running.")
    env = os.environ.copy()
    env.update(database_environment())
    token = secrets.token_hex(32)
    env["RIO_FIXTURE_PROCESS_TOKEN"] = token
    log_path = runtime_path("bff.log")
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as private_log:
        process = subprocess.Popen(
            [str(bff_binary())], cwd=REPO, env=env, stdout=private_log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    deadline = time.monotonic() + 2
    identity = process_identity(process.pid)
    while identity is not None and identity["binary"] != str(bff_binary().resolve()) and time.monotonic() < deadline:
        time.sleep(0.02)
        identity = process_identity(process.pid)
    if identity is None or identity["binary"] != str(bff_binary().resolve()):
        process.terminate()
        process.wait(timeout=5)
        raise RuntimeError("Synthetic BFF did not start.")
    write_new("bff-process.json", json.dumps({
        "pid": process.pid, "processToken": token, "startTicks": identity["startTicks"],
    }) + "\n")
    try:
        wait_for_bff(process.pid)
    except Exception:
        stop_bff()
        raise

def stop_bff() -> None:
    owned = owned_bff()
    if owned is None:
        print("Synthetic BFF is already stopped.")
        return
    pid, metadata = owned
    # A pidfd targets this exact process instance even if the numeric PID is reused.
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        if process_identity(pid) is None:
            runtime_path("bff-process.json").unlink(missing_ok=True)
            return
        raise RuntimeError("Synthetic BFF process ownership could not be established.")
    try:
        current = owned_bff()
        if current is None:
            return
        if current != owned:
            raise RuntimeError("Synthetic BFF process ownership changed; refusing signals.")
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process_identity(pid) is None:
                runtime_path("bff-process.json").unlink(missing_ok=True)
                print("Synthetic BFF stopped.")
                return
            time.sleep(0.1)
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if process_identity(pid) is None:
                runtime_path("bff-process.json").unlink(missing_ok=True)
                print("Synthetic BFF stopped.")
                return
            time.sleep(0.05)
        raise RuntimeError("Synthetic BFF did not stop; refusing restart.")
    finally:
        os.close(descriptor)

def restart_bff() -> None:
    previous = owned_bff()
    if previous is None:
        raise RuntimeError("No owned live BFF generation is available to restart.")
    stop_bff()
    start_bff()
    current = owned_bff()
    if current is None or current == previous:
        raise RuntimeError("Synthetic BFF restart did not change its owned generation.")
    print('RIO_BFF_RESTART_VERIFIED {"generationChanged":true,"databasePreserved":true}')

def database_diagnostics() -> None:
    metadata = json.loads(runtime_path("metadata.json").read_text(encoding="utf-8"))
    project = metadata.get("project", "")
    if not re.fullmatch(r"rio-accounts-synthetic-[0-9a-f]{8}", project):
        raise RuntimeError("Invalid diagnostic project.")
    result = subprocess.run(
        ["docker", "inspect", project + "-postgres-1", "--format",
         "{{json .State}}\n{{json .NetworkSettings.Ports}}"],
        capture_output=True, text=True, check=False,
    )
    state, bindings = {}, []
    if result.returncode == 0:
        try:
            lines = result.stdout.splitlines()
            raw = json.loads(lines[0])
            state = {
                "Running": raw.get("Running") if type(raw.get("Running")) is bool else None,
                "ExitCode": raw.get("ExitCode") if type(raw.get("ExitCode")) is int and 0 <= raw["ExitCode"] <= 255 else None,
                "OOMKilled": raw.get("OOMKilled") if type(raw.get("OOMKilled")) is bool else None,
            }
            bindings = public_port_bindings(json.loads(lines[1]))
        except (ValueError, IndexError, TypeError, AttributeError):
            state = {"unavailable": True}
    logs = subprocess.run(
        ["docker", "logs", project + "-postgres-1"], capture_output=True, text=True, check=False,
    )
    private_output = logs.stdout + "\n" + logs.stderr if logs.returncode == 0 else ""
    # Fixed reason booleans only; no database log text is ever exported.
    indicators = {
        "serverReady": r"database system is ready to accept connections",
        "passwordAuthenticationFailed": r"password authentication failed",
        "initializationFailed": r"initdb: error|database is uninitialized",
        "permissionDenied": r"permission denied|could not change permissions",
        "diskSpaceFailure": r"no space left on device",
        "incompatibleDataDirectory": r"incompatible with server|old databases detected|18\+",
        "fatalError": r"(?:^|\n).*FATAL:",
    }
    reasons = {key: bool(re.search(pattern, private_output, re.IGNORECASE))
               for key, pattern in indicators.items()}
    print("RIO_DATABASE_DIAGNOSTIC " + json.dumps(
        {"state": state, "portBindings": bindings, "startupIndicators": reasons}, separators=(",", ":")))

DATABASE_TEST_FILTERS = {
    "postgres_storage_contract",
    "postgres_consent_http_contract",
    "postgres_prepare_restore_proof",
    "postgres_verify_restored_snapshot",
}

DATABASE_CASE_TAGS = frozenset((
    "CASE T03_SETUP", "CASE T03_ATOMIC_FLOW", "CASE T03_DURABILITY",
    "CASE T03_TENANT", "CASE T03_CONSENT", "CASE T03_LOGOUT_ALL",
    "CASE T03_ROTATE_FIRST", "CASE T03_REVOKE_FIRST", "CASE T03_RACE",
    "CASE T03_FAMILY", "CASE T03_EXPIRY", "CASE T03_SCHEMA", "CASE T03_CLOCK",
    "CASE T03_BACKUP_PREPARE", "CASE T03_RESTORE_BEFORE", "CASE T03_RESTORE_FENCE",
    "CASE T04_SETUP", "CASE T04_OWN_RECEIPT", "CASE T04_CSRF", "CASE T04_CAS",
    "CASE T04_REVOKE", "CASE T04_EXPIRY", "CASE T04_UNAVAILABLE", "CASE T04_RECOVERY",
    "CASE T03_DURABILITY_ALPHA_LOGIN", "CASE T03_DURABILITY_BETA_LOGIN",
    "CASE T03_DURABILITY_BEFORELOAD", "CASE T03_DURABILITY_RECONNECT",
    "CASE T03_DURABILITY_AFTERLOAD", "CASE T03_LOGIN_BEGIN",
    "CASE T03_LOGIN_CONSUME", "CASE T03_LOGIN_REPLACE",
    "CASE T03_SQL_TYPE", "CASE T03_SQL_CLOSED", "CASE T03_SQL_CONSTRAINT",
    "CASE T03_SQL_DATABASE", "CASE T03_SQL_OTHER",

))

def database_case_tags(captured: str) -> list[str]:
    found = []
    for line in captured.splitlines():
        if line in DATABASE_CASE_TAGS and line not in found:
            found.append(line)
    return found

def database_failure_location(captured: str) -> dict | None:
    # Rust 1.90's default panic header; only this fixed repository source is allowed.
    header = re.compile(
        r"thread '[^'\r\n]{1,200}' panicked at "
        r"(?:services/rio-accounts/)?src/storage\.rs:"
        r"([1-9][0-9]{0,5}):([1-9][0-9]{0,5}):"
    )
    for line in captured.splitlines():
        if len(line) > 512:
            continue
        match = header.fullmatch(line)
        if match:
            return {"path": "services/rio-accounts/src/storage.rs",
                    "line": int(match[1]), "column": int(match[2])}
    return None

def run_database_test(test_filter: str) -> None:
    if test_filter not in DATABASE_TEST_FILTERS:
        raise RuntimeError("Unknown synthetic database test filter.")
    env = os.environ.copy()
    env.update(database_environment())
    result = subprocess.run(
        ["cargo", "test", "--manifest-path", str(REPO / "services/rio-accounts/Cargo.toml"),
         "--locked", test_filter, "--", "--ignored", "--test-threads=1"],
        cwd=REPO, env=env, capture_output=True, text=True, check=False, timeout=180,
    )
    # Fixed summaries only: never emit assertion messages, URLs or test inputs.
    summaries = []
    passed = 0
    failed = 0
    grammar = (r"test result: (ok|FAILED)\. ([0-9]+) passed; ([0-9]+) failed; "
               r"[0-9]+ ignored; [0-9]+ measured; [0-9]+ filtered out; "
               r"finished in [0-9]+\.[0-9]+s")
    for line in result.stdout.splitlines():
        match = re.fullmatch(grammar, line)
        if match:
            summaries.append(line)
            passed += int(match[2])
            failed += int(match[3])
    success = result.returncode == 0 and passed == 1 and failed == 0
    print("RIO_DATABASE_TEST_SUMMARY " + json.dumps(
        {"test": test_filter, "success": success, "summaries": summaries,
         "cases": database_case_tags(result.stdout + "\n" + result.stderr),
         "failureLocation": database_failure_location(result.stdout + "\n" + result.stderr) if not success else None},
        separators=(",", ":")))
    if not success:
        raise RuntimeError("Synthetic database proof test failed or did not run exactly once.")

def run_storage_tests() -> None:
    run_database_test("postgres_storage_contract")

def run_consent_http_tests() -> None:
    run_database_test("postgres_consent_http_contract")

def prepare_restore_proof() -> None:
    if owned_bff() is not None:
        raise RuntimeError("Stop the owned BFF before preparing the native restore proof.")
    run_database_test("postgres_prepare_restore_proof")

def run_bff() -> None:
    env = os.environ.copy()
    env.update(database_environment())
    binary = REPO / "services" / "rio-accounts" / "target" / "debug" / "rio-accounts-dev"
    if os.name == "nt":
        binary = binary.with_suffix(".exe")
    if not binary.is_file():
        raise RuntimeError("Build services/rio-accounts first with cargo build --manifest-path services/rio-accounts/Cargo.toml.")
    os.chdir(REPO)
    if os.name != "nt":
        # Keep the CI background PID as the BFF process so termination reaches it.
        os.execve(str(binary), [str(binary)], env)
    subprocess.run([str(binary)], check=True, cwd=REPO, env=env)

def down() -> None:
    stop_bff()
    if runtime_path("metadata.json").exists():
        compose("down", "--volumes", "--remove-orphans")
    # Remove only our known generated files. Never recurse over an arbitrary path.
    for name in (*GENERATED_FILES, *OPTIONAL_RUNTIME_FILES):
        path = runtime_path(name)
        if path.exists():
            path.unlink()
    print("Synthetic containers/network and generated credentials removed.")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "up", "run-bff", "down", "diagnostics", "db-diagnostics",
                                                "start-bff", "stop-bff", "restart-bff", "run-consent-http-tests",
                                                "stop-db", "start-db", "backup-db", "restore-db",
                                                "run-storage-tests", "prepare-restore-proof"))
    arguments = parser.parse_args()
    try:
        if arguments.command == "prepare":
            prepare()
        elif arguments.command == "up":
            prepare()
            compose("up", "-d")
            wait_for_discovery()
            wait_for_database()
        elif arguments.command == "run-bff":
            run_bff()
        elif arguments.command == "diagnostics":
            diagnostics()
        elif arguments.command == "db-diagnostics":
            database_diagnostics()
        elif arguments.command == "start-bff":
            start_bff()
        elif arguments.command == "stop-bff":
            stop_bff()
        elif arguments.command == "restart-bff":
            restart_bff()
        elif arguments.command == "stop-db":
            stop_database()
        elif arguments.command == "start-db":
            start_database()
        elif arguments.command == "backup-db":
            backup_database()
        elif arguments.command == "restore-db":
            restore_database()
        elif arguments.command == "run-storage-tests":
            run_storage_tests()
        elif arguments.command == "run-consent-http-tests":
            run_consent_http_tests()
        elif arguments.command == "prepare-restore-proof":
            prepare_restore_proof()
        else:
            down()
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        print(f"Fixture failed: {error}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
