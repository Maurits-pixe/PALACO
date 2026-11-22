-- GO-20 v15: transaction failure injection / audit atomicity assertions.
-- Execute ONLY after GO-20 v14 fixture in throwaway PostgreSQL CI.
DO $$
DECLARE
    before_records bigint;
    before_audit bigint;
    after_records bigint;
    after_audit bigint;
BEGIN
    SELECT count(*) INTO before_records FROM go20_test.tenant_evidence;
    SELECT count(*) INTO before_audit FROM go20_test.audit_events;

    -- Both the new record and its AFTER INSERT audit event must roll back.
    BEGIN
        INSERT INTO go20_test.tenant_evidence
            (tenant_role, entry_sha256) VALUES ('go20_alpha', repeat('e', 64));
        IF (SELECT count(*) FROM go20_test.audit_events) <> before_audit + 1 THEN
            RAISE EXCEPTION 'audit event was not written before fault injection';
        END IF;
        RAISE EXCEPTION 'GO-20 synthetic fault after audited insertion';
    EXCEPTION WHEN raise_exception THEN
        NULL;
    END;

    SELECT count(*) INTO after_records FROM go20_test.tenant_evidence;
    SELECT count(*) INTO after_audit FROM go20_test.audit_events;
    IF before_records <> after_records OR before_audit <> after_audit THEN
        RAISE EXCEPTION 'audit and data were not both rolled back';
    END IF;

    -- Invalid record must fail and must not emit an audit event.
    BEGIN
        INSERT INTO go20_test.tenant_evidence
            (tenant_role, entry_sha256) VALUES ('go20_beta', 'invalid');
        RAISE EXCEPTION 'invalid record unexpectedly accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
    IF (SELECT count(*) FROM go20_test.audit_events) <> before_audit THEN
        RAISE EXCEPTION 'invalid record leaked an audit event';
    END IF;

    -- Audit table writes must be rejected; surrounding transaction survives.
    BEGIN
        DELETE FROM go20_test.audit_events;
        RAISE EXCEPTION 'audit delete unexpectedly accepted';
    EXCEPTION WHEN raise_exception THEN
        NULL;
    END;
    IF (SELECT count(*) FROM go20_test.audit_events) <> before_audit THEN
        RAISE EXCEPTION 'audit delete bypassed append-only trigger';
    END IF;
END $$;
