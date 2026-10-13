#!/usr/bin/env python3
"""Prepare and run the isolated synthetic Keycloak/BFF fixture."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler

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
    project_name = "rio-accounts-synthetic-" + secrets.token_hex(4)
    metadata = {"project": project_name, "issuer": ISSUER, "clientId": CLIENT_ID}
    write_new("metadata.json", json.dumps(metadata, indent=2) + "\n")
    write_new("test-credentials.json", json.dumps(credentials, indent=2) + "\n")
    write_new(
        "compose.env",
        f"COMPOSE_PROJECT_NAME={project_name}\n"
        f"RIO_RUNTIME_DIR={RUNTIME.as_posix()}\n"
        f"RIO_KC_ADMIN_PASSWORD={admin_password}\n",
    )
    write_new(
        "bff.env",
        "RIO_DEV_MODE=SYNTHETIC_ONLY\n"
        f"RIO_DEV_CLIENT_SECRET={client_secret}\n"
        f"RIO_DEV_TLS_CERT={runtime_path('tls-cert.pem')}\n"
        f"RIO_DEV_TLS_KEY={runtime_path('tls-key.pem')}\n",
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

def compose(*arguments: str) -> None:
    metadata_path = runtime_path("metadata.json")
    if not metadata_path.exists():
        raise RuntimeError("No prepared fixture runtime. Run fixture.py prepare first.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"rio-accounts-synthetic-[0-9a-f]{8}", metadata.get("project", "")):
        raise RuntimeError("Invalid synthetic Compose project; refusing container changes.")
    subprocess.run(
        [
            "docker", "compose",
            "--env-file", str(runtime_path("compose.env")),
            "--file", str(ROOT / "compose.yaml"),
            "--project-name", metadata["project"],
            *arguments,
        ],
        check=True,
        cwd=ROOT,
    )

def runtime_secret_values() -> list[str]:
    """Collect every generated password/client secret before handling provider output."""
    values = set()
    for name in ("compose.env", "bff.env"):
        for line in runtime_path(name).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and ("PASSWORD" in key or "SECRET" in key):
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
    text = re.sub(r"https?://[^\s\"'<>]+", "[REDACTED_URL]", text)
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

def run_bff() -> None:
    env = os.environ.copy()
    env.update(read_bff_environment())
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
    if runtime_path("metadata.json").exists():
        compose("down", "--volumes", "--remove-orphans")
    # Remove only our known generated files. Never recurse over an arbitrary path.
    for name in GENERATED_FILES:
        path = runtime_path(name)
        if path.exists():
            path.unlink()
    print("Synthetic containers/network and generated credentials removed.")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "up", "run-bff", "down", "diagnostics"))
    arguments = parser.parse_args()
    try:
        if arguments.command == "prepare":
            prepare()
        elif arguments.command == "up":
            prepare()
            compose("up", "-d")
            wait_for_discovery()
        elif arguments.command == "run-bff":
            run_bff()
        elif arguments.command == "diagnostics":
            diagnostics()
        else:
            down()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"Fixture failed: {error}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
