-- GO-20 v14: disposable audit fixture. Never deploy to PALACO MONO.
-- Must follow v11, v12 and v13 fixtures in a disposable CI database.
BEGIN;

CREATE TABLE go20_test.audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation text NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    actor_role name NOT NULL,
    tenant_role name NOT NULL,
    entry_sha256 text NOT NULL CHECK (entry_sha256 ~ '^[0-9a-f]{64}$')
);

REVOKE ALL ON go20_test.audit_events FROM PUBLIC;
REVOKE ALL ON go20_test.audit_events FROM go20_alpha, go20_beta;
REVOKE ALL ON SEQUENCE go20_test.audit_events_id_seq FROM PUBLIC;

CREATE FUNCTION go20_test.audit_tenant_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, go20_test
AS $fn$
BEGIN
    INSERT INTO go20_test.audit_events (
        operation, actor_role, tenant_role, entry_sha256
    ) VALUES (
        TG_OP,
        CURRENT_USER,
        CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_role ELSE NEW.tenant_role END,
        CASE WHEN TG_OP = 'DELETE' THEN OLD.entry_sha256 ELSE NEW.entry_sha256 END
    );
    RETURN NULL;
END
$fn$;
REVOKE ALL ON FUNCTION go20_test.audit_tenant_change() FROM PUBLIC;

CREATE TRIGGER go20_audit_tenant_change
AFTER INSERT OR UPDATE OR DELETE ON go20_test.tenant_evidence
FOR EACH ROW EXECUTE FUNCTION go20_test.audit_tenant_change();

-- Even the fixture owner cannot alter or erase evidence via ordinary DML.
CREATE FUNCTION go20_test.reject_audit_modification()
RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, go20_test
AS $fn$
BEGIN
    RAISE EXCEPTION 'audit events are append-only in test fixture';
END
$fn$;
REVOKE ALL ON FUNCTION go20_test.reject_audit_modification() FROM PUBLIC;
CREATE TRIGGER go20_audit_immutable
BEFORE UPDATE OR DELETE ON go20_test.audit_events
FOR EACH ROW EXECUTE FUNCTION go20_test.reject_audit_modification();

COMMIT;

DO $$
BEGIN
    IF has_table_privilege('go20_alpha', 'go20_test.audit_events', 'SELECT')
       OR has_table_privilege('go20_beta', 'go20_test.audit_events', 'INSERT')
       OR has_table_privilege('go20_alpha', 'go20_test.audit_events', 'DELETE')
    THEN
        RAISE EXCEPTION 'untrusted tenant has access to audit events';
    END IF;
END $$;
