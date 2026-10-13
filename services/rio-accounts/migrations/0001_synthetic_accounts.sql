-- T03 SYNTHETIC_ONLY. This schema cannot activate a personal account or contact route.
-- Applied transactionally by PgStore with a fixed advisory migration lock.
CREATE SCHEMA IF NOT EXISTS rio_synthetic;

CREATE TABLE IF NOT EXISTS rio_synthetic.store_guard (
    id smallint PRIMARY KEY CHECK (id = 1),
    schema_version integer NOT NULL CHECK (schema_version = 1),
    last_ms bigint NOT NULL CHECK (last_ms >= 0),
    recovery_generation bigint NOT NULL DEFAULT 0 CHECK (recovery_generation >= 0),
    audit_full boolean NOT NULL DEFAULT false,
    audit_suppressed bigint NOT NULL DEFAULT 0 CHECK (audit_suppressed >= 0),
    mode text NOT NULL DEFAULT 'SYNTHETIC_ONLY' CHECK (mode = 'SYNTHETIC_ONLY'),
    account_active boolean NOT NULL DEFAULT false CHECK (account_active = false)
);
INSERT INTO rio_synthetic.store_guard (id, schema_version, last_ms)
VALUES (1, 1, floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS rio_synthetic.accounts (
    account_id text PRIMARY KEY CHECK (account_id IN ('TST-alpha', 'TST-beta')),
    owner_id text NOT NULL,
    tenant_id text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'SYNTHETIC_ENABLED'
        CHECK (status IN ('SYNTHETIC_ENABLED', 'SYNTHETIC_DISABLED')),
    version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    CHECK (owner_id = CASE account_id WHEN 'TST-alpha' THEN 'owner-TST-alpha' ELSE 'owner-TST-beta' END),
    CHECK (tenant_id = CASE account_id WHEN 'TST-alpha' THEN 'tenant-TST-alpha' ELSE 'tenant-TST-beta' END),
    UNIQUE (account_id, owner_id, tenant_id)
);
INSERT INTO rio_synthetic.accounts (account_id, owner_id, tenant_id)
VALUES ('TST-alpha', 'owner-TST-alpha', 'tenant-TST-alpha'),
       ('TST-beta', 'owner-TST-beta', 'tenant-TST-beta')
ON CONFLICT (account_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS rio_synthetic.auth_bindings (
    account_id text PRIMARY KEY REFERENCES rio_synthetic.accounts(account_id),
    issuer text NOT NULL CHECK (issuer = 'http://127.0.0.1:8089/realms/rio-synthetic'),
    subject text NOT NULL,
    CHECK (subject = CASE account_id
        WHEN 'TST-alpha' THEN '11111111-1111-4111-8111-111111111111'
        ELSE '22222222-2222-4222-8222-222222222222' END),
    UNIQUE (issuer, subject)
);
INSERT INTO rio_synthetic.auth_bindings (account_id, issuer, subject)
VALUES ('TST-alpha', 'http://127.0.0.1:8089/realms/rio-synthetic', '11111111-1111-4111-8111-111111111111'),
       ('TST-beta', 'http://127.0.0.1:8089/realms/rio-synthetic', '22222222-2222-4222-8222-222222222222')
ON CONFLICT (account_id) DO NOTHING;

-- Nonce and PKCE are intentionally absent: their bounded process memory is lost on restart.
CREATE TABLE IF NOT EXISTS rio_synthetic.auth_transactions (
    transaction_hash bytea PRIMARY KEY CHECK (octet_length(transaction_hash) = 32),
    state_hash bytea NOT NULL CHECK (octet_length(state_hash) = 32),
    predecessor_hash bytea CHECK (predecessor_hash IS NULL OR octet_length(predecessor_hash) = 32),
    alpha_version bigint NOT NULL CHECK (alpha_version >= 0),
    beta_version bigint NOT NULL CHECK (beta_version >= 0),
    created_ms bigint NOT NULL CHECK (created_ms >= 0),
    expires_ms bigint NOT NULL CHECK (expires_ms = created_ms + 300000)
);

CREATE TABLE IF NOT EXISTS rio_synthetic.sessions (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    family_hash bytea NOT NULL CHECK (octet_length(family_hash) = 32),
    rotated boolean NOT NULL DEFAULT false,
    account_id text NOT NULL,
    owner_id text NOT NULL,
    tenant_id text NOT NULL,
    version bigint NOT NULL CHECK (version >= 0),
    csrf text NOT NULL CHECK (csrf ~ '^[A-Za-z0-9_-]{43}$'),
    created_ms bigint NOT NULL CHECK (created_ms >= 0),
    touched_ms bigint NOT NULL CHECK (touched_ms >= created_ms),
    idle_expires_ms bigint NOT NULL,
    absolute_expires_ms bigint NOT NULL,
    CHECK (absolute_expires_ms = created_ms + 60000),
    CHECK (idle_expires_ms <= absolute_expires_ms AND idle_expires_ms = LEAST(touched_ms + 30000, absolute_expires_ms)),
    FOREIGN KEY (account_id, owner_id, tenant_id)
        REFERENCES rio_synthetic.accounts (account_id, owner_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS rio_synthetic_session_actor ON rio_synthetic.sessions(account_id);

-- These two registries remain disabled. No candidate contact data or issued personal code exists here.
CREATE TABLE IF NOT EXISTS rio_synthetic.enrollment_requests (
    account_id text PRIMARY KEY REFERENCES rio_synthetic.accounts(account_id),
    request_id text NOT NULL UNIQUE CHECK (request_id = CASE account_id
        WHEN 'TST-alpha' THEN 'TST-ENROLL-alpha' ELSE 'TST-ENROLL-beta' END),
    status text NOT NULL DEFAULT 'DISABLED_SYNTHETIC' CHECK (status = 'DISABLED_SYNTHETIC'),
    mode text NOT NULL DEFAULT 'SYNTHETIC_ONLY' CHECK (mode = 'SYNTHETIC_ONLY')
);
INSERT INTO rio_synthetic.enrollment_requests(account_id, request_id)
VALUES ('TST-alpha', 'TST-ENROLL-alpha'), ('TST-beta', 'TST-ENROLL-beta')
ON CONFLICT (account_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS rio_synthetic.provisional_id_bindings (
    account_id text PRIMARY KEY REFERENCES rio_synthetic.accounts(account_id),
    provisional_ref text NOT NULL UNIQUE CHECK (provisional_ref = CASE account_id
        WHEN 'TST-alpha' THEN 'TST-PROVISIONAL-alpha' ELSE 'TST-PROVISIONAL-beta' END),
    status text NOT NULL DEFAULT 'DISABLED_SYNTHETIC' CHECK (status = 'DISABLED_SYNTHETIC'),
    version bigint NOT NULL DEFAULT 1 CHECK (version = 1)
);
INSERT INTO rio_synthetic.provisional_id_bindings(account_id, provisional_ref)
VALUES ('TST-alpha', 'TST-PROVISIONAL-alpha'), ('TST-beta', 'TST-PROVISIONAL-beta')
ON CONFLICT (account_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS rio_synthetic.consent_receipts (
    account_id text PRIMARY KEY,
    owner_id text NOT NULL,
    tenant_id text NOT NULL,
    scope text NOT NULL DEFAULT 'RIO_SYNTHETIC_SESSION_TEST_V1'
        CHECK (scope = 'RIO_SYNTHETIC_SESSION_TEST_V1'),
    version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    granted boolean NOT NULL DEFAULT false,
    expires_ms bigint,
    CHECK ((granted AND expires_ms IS NOT NULL) OR (NOT granted AND expires_ms IS NULL)),
    FOREIGN KEY (account_id, owner_id, tenant_id)
        REFERENCES rio_synthetic.accounts(account_id, owner_id, tenant_id)
);
INSERT INTO rio_synthetic.consent_receipts(account_id, owner_id, tenant_id)
SELECT account_id, owner_id, tenant_id FROM rio_synthetic.accounts
ON CONFLICT (account_id) DO NOTHING;

-- Minimal attributable event types, without token hashes, CSRF, addresses or payload text.
CREATE TABLE IF NOT EXISTS rio_synthetic.audit_events (
    id bigserial PRIMARY KEY,
    account_id text REFERENCES rio_synthetic.accounts(account_id),
    event_type text NOT NULL CHECK (event_type IN
        ('SESSION_CREATED','SESSION_LOGOUT','ACTOR_REVOKED','CONSENT_RECORDED','CONSENT_REVOKED','RECOVERY_FENCE')),
    at_ms bigint NOT NULL CHECK (at_ms >= 0),
    mode text NOT NULL DEFAULT 'SYNTHETIC_ONLY' CHECK (mode = 'SYNTHETIC_ONLY')
);
CREATE TABLE IF NOT EXISTS rio_synthetic.outbox (
    audit_id bigint PRIMARY KEY REFERENCES rio_synthetic.audit_events(id),
    status text NOT NULL DEFAULT 'DISABLED_SYNTHETIC' CHECK (status = 'DISABLED_SYNTHETIC'),
    external_side_effect boolean NOT NULL DEFAULT false CHECK (external_side_effect = false)
);
CREATE OR REPLACE FUNCTION rio_synthetic.reject_audit_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'Synthetic audit records are append-only';
END $$;
DROP TRIGGER IF EXISTS rio_synthetic_audit_immutable ON rio_synthetic.audit_events;
CREATE TRIGGER rio_synthetic_audit_immutable BEFORE UPDATE OR DELETE ON rio_synthetic.audit_events
FOR EACH ROW EXECUTE FUNCTION rio_synthetic.reject_audit_change();
