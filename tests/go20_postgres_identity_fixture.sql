-- GO-20 v13: synthetic session-principal binding only in disposable CI.
-- No Supabase auth/JWT integration and no production DDL.
BEGIN;
CREATE TABLE go20_test.principal_binding (
    principal_role name PRIMARY KEY,
    tenant_role name NOT NULL,
    identity_label text NOT NULL
);
INSERT INTO go20_test.principal_binding(principal_role, tenant_role, identity_label)
VALUES ('go20_alpha', 'go20_alpha', 'synthetic-alpha'),
       ('go20_beta', 'go20_beta', 'synthetic-beta');

ALTER TABLE go20_test.principal_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE go20_test.principal_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY go20_principal_read ON go20_test.principal_binding
FOR SELECT TO go20_alpha, go20_beta
USING (principal_role = CURRENT_USER AND tenant_role = CURRENT_USER);

GRANT SELECT ON go20_test.principal_binding TO go20_alpha, go20_beta;

-- Identity is the authenticated PostgreSQL role, not a session variable supplied
-- by a client. These test roles have no LOGIN and no role membership between them.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_auth_members m
        JOIN pg_roles member_role ON member_role.oid = m.member
        JOIN pg_roles target_role ON target_role.oid = m.roleid
        WHERE member_role.rolname IN ('go20_alpha','go20_beta')
          AND target_role.rolname IN ('go20_alpha','go20_beta')
    ) THEN
        RAISE EXCEPTION 'synthetic tenant roles must have no cross-role grants';
    END IF;
    IF has_table_privilege('go20_alpha', 'go20_test.principal_binding', 'INSERT')
       OR has_table_privilege('go20_beta', 'go20_test.principal_binding', 'UPDATE')
    THEN
        RAISE EXCEPTION 'principal binding must be read only';
    END IF;
END $$;
COMMIT;
