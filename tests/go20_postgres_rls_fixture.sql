-- GO-20 v12 — disposable PostgreSQL role and row isolation fixture.
-- Only executed in GitHub Actions' synthetic go20test database.
BEGIN;
-- PostgreSQL grants EXECUTE to PUBLIC on new functions by default; explicitly
-- deny all untrusted callers (the fixture owner remains the only executor).
REVOKE ALL ON FUNCTION go20_test.try_consume(bigint,text,text,text) FROM PUBLIC;
REVOKE ALL ON SCHEMA go20_test FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA go20_test FROM PUBLIC;

CREATE ROLE go20_alpha NOLOGIN;
CREATE ROLE go20_beta NOLOGIN;

CREATE TABLE go20_test.tenant_evidence (
    tenant_role name NOT NULL,
    entry_sha256 text NOT NULL CHECK (entry_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (tenant_role, entry_sha256)
);
INSERT INTO go20_test.tenant_evidence (tenant_role, entry_sha256)
VALUES
    ('go20_alpha', repeat('a',64)),
    ('go20_beta', repeat('b',64));

ALTER TABLE go20_test.tenant_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE go20_test.tenant_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY go20_tenant_read
    ON go20_test.tenant_evidence
    FOR SELECT TO go20_alpha, go20_beta
    USING (tenant_role = CURRENT_USER);

GRANT USAGE ON SCHEMA go20_test TO go20_alpha, go20_beta;
GRANT SELECT ON go20_test.tenant_evidence TO go20_alpha, go20_beta;
COMMIT;

DO $$
BEGIN
    IF has_function_privilege('go20_alpha',
       'go20_test.try_consume(bigint,text,text,text)', 'EXECUTE') OR
       has_function_privilege('go20_beta',
       'go20_test.try_consume(bigint,text,text,text)', 'EXECUTE') THEN
        RAISE EXCEPTION 'untrusted role has EXECUTE on replay function';
    END IF;
    IF has_table_privilege('go20_alpha', 'go20_test.state', 'SELECT') OR
       has_table_privilege('go20_beta', 'go20_test.consumed', 'SELECT') THEN
        RAISE EXCEPTION 'untrusted role can read internal replay state';
    END IF;
    IF has_table_privilege('go20_alpha', 'go20_test.tenant_evidence', 'INSERT') OR
       has_table_privilege('go20_beta', 'go20_test.tenant_evidence', 'UPDATE') THEN
        RAISE EXCEPTION 'untrusted role can write tenant evidence';
    END IF;
    IF NOT (SELECT relrowsecurity AND relforcerowsecurity
            FROM pg_class WHERE oid = 'go20_test.tenant_evidence'::regclass) THEN
        RAISE EXCEPTION 'RLS or FORCE RLS is disabled';
    END IF;
END $$;
