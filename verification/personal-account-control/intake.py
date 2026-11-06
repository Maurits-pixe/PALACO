"""HTTP-shaped, in-process SYNTHETIC adapter. No server, OIDC or real attestation.

Only a trusted fixture may seed the opaque session registry. Client JSON cannot
select the actor, server clock, environment or session authentication strength.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from threading import RLock
import hashlib
import hmac
import json
import re
import secrets
import sqlite3

from model import Denied

ORIGIN = 'https://localhost:8088'
COOKIE = '__Host-pac_fixture'
MAX_BODY = 4096
CHECKS = frozenset(('purpose', 'scope', 'privacy', 'risk', 'escalation',
                   'recovery', 'clinical_boundary', 'human_owner', 'consent_basis'))


@dataclass(frozen=True)
class FixtureSession:
    actor: str
    workspace: str
    until: int
    csrf: str
    strong: bool


class BadRequest(ValueError):
    pass


class FixtureSessions:
    """Local fixture credential store; not wired to any real identity provider."""
    def __init__(self):
        self.entries = {}
        self.lock = RLock()

    def seed(self, actor, until, *, workspace='synthetic', strong=True):
        token, csrf = secrets.token_hex(32), secrets.token_hex(32)
        with self.lock:
            self.entries[hashlib.sha256(token.encode()).hexdigest()] = FixtureSession(
                actor, workspace, until, csrf, strong)
        return token, csrf

    def revoke(self, token):
        with self.lock:
            self.entries.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def resolve(self, token, now):
        with self.lock:
            entry = self.entries.get(hashlib.sha256(token.encode()).hexdigest())
            return entry if entry and entry.until > now and entry.strong else None


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise BadRequest('duplicate key')
        obj[key] = value
    return obj


class Intake:
    def __init__(self, model, sessions, clock):
        self.model, self.sessions, self.clock = model, sessions, clock

    def handle(self, method, path, headers, body):
        """headers: list of pairs, preserving duplicates for rejection.

        A future HTTP server must enforce TLS, framing, header/body limits and
        validate session/CSRF state per request; this function opens no socket.
        """
        response_headers = {'Cache-Control': 'no-store', 'Content-Type': 'application/json'}
        def respond(status, code):
            return status, response_headers, {'code': code, 'mode': 'SYNTHETIC_ONLY',
                                             'account1': 'HOLD'}
        if path not in {'/staging/reviews', '/staging/activations'}:
            return respond(404, 'NOT_FOUND')
        if method != 'POST':
            return respond(405, 'METHOD_NOT_ALLOWED')
        if type(body) is not bytes or len(body) > MAX_BODY:
            return respond(413, 'BODY_LIMIT')
        try:
            if type(headers) is not list or len(headers) > 20:
                raise BadRequest('headers')
            normalized = {}
            for name, value in headers:
                if type(name) is not str or type(value) is not str or len(value) > 512:
                    raise BadRequest('header type')
                name = name.lower()
                if name in normalized:
                    raise BadRequest('duplicate header')
                normalized[name] = value
            if normalized.get('content-type') != 'application/json':
                return respond(415, 'CONTENT_TYPE_REQUIRED')
            if normalized.get('origin') != ORIGIN:
                return respond(403, 'REQUEST_DENIED')
            cookie = normalized.get('cookie', '')
            match = re.fullmatch(re.escape(COOKIE) + r'=([0-9a-f]{64})', cookie)
            now = self.clock()  # trusted dependency, never body/header time
            session = self.sessions.resolve(match[1], now) if match else None
            if session is None:
                return respond(401, 'SESSION_REQUIRED')
            if not hmac.compare_digest(session.csrf, normalized.get('x-csrf-token', '')):
                return respond(403, 'REQUEST_DENIED')
            @contextmanager
            def commit_guard():
                # Revocation and final validation/commit share this local lock.
                with self.sessions.lock:
                    current = self.clock()
                    if (type(current) is not int or current < now
                        or self.sessions.resolve(match[1], current) != session):
                        raise Denied('SESSION_INVALID_AT_COMMIT')
                    yield current
            data = json.loads(body.decode('utf-8'), object_pairs_hook=unique_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(BadRequest('constant')))
            base = {'account', 'revision', 'workspace', 'scope', 'policy'}
            fields = {'valid_until', 'checklist'} if path.endswith('reviews') else {'until', 'key'}
            if type(data) is not dict or set(data) != base | fields:
                raise BadRequest('fields')
            if (type(data['account']) is not str
                or not re.fullmatch(r'TST-[a-zA-Z0-9-]{1,48}', data['account'])
                or type(data['revision']) is not int or data['revision'] < 1
                or data['workspace'] != session.workspace or data['workspace'] != 'synthetic'
                or data['scope'] != 'synthetic:read' or type(data['policy']) is not str
                or not 1 <= len(data['policy']) <= 64):
                raise BadRequest('binding')
            binding = {k: data[k] for k in ('revision', 'workspace', 'scope', 'policy')}
            expiry = data['valid_until'] if path.endswith('reviews') else data['until']
            if type(expiry) is not int or not now < expiry <= now + 300:
                raise BadRequest('expiry')
            if path.endswith('reviews'):
                checks = data['checklist']
                if type(checks) is not dict or set(checks) != CHECKS or any(v is not True for v in checks.values()):
                    raise BadRequest('checklist')
                digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.model.review(data['account'], now, checks, actor=session.actor,
                    valid_until=expiry, evidence_ref='EVD-SYNTHETIC-' + digest,
                    expected_binding=binding, commit_guard=commit_guard)
                return respond(200, 'REVIEW_RECORDED')
            if type(data['key']) is not str or not re.fullmatch(r'[A-Za-z0-9-]{8,64}', data['key']):
                raise BadRequest('key')
            self.model.activate(data['account'], data['revision'], now, expiry,
                data['key'], actor=session.actor, environment='staging', expected_binding=binding, commit_guard=commit_guard)
            return respond(200, 'SYNTHETIC_ACTIVATION_RECORDED')
        except Denied:
            return respond(403, 'GATE_DENIED')
        except sqlite3.Error:
            return respond(503, 'STORAGE_UNAVAILABLE')
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return respond(400, 'INVALID_REQUEST')
