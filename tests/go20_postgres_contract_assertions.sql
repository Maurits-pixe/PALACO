-- Run after go20_postgres_contract.sql in a disposable PostgreSQL database.
-- Any violated invariant causes psql ON_ERROR_STOP to fail.
DO $$
DECLARE
    outcome text;
    revision_seen bigint;
BEGIN
    outcome := go20_test.try_consume(0, repeat('a',64), repeat('b',64), repeat('1',64));
    IF outcome <> 'TEST_ONLY_COMMIT' THEN
        RAISE EXCEPTION 'initial commit failed: %', outcome;
    END IF;
    outcome := go20_test.try_consume(0, repeat('a',64), repeat('c',64), repeat('2',64));
    IF outcome <> 'STALE_STATE' THEN
        RAISE EXCEPTION 'stale revision accepted: %', outcome;
    END IF;
    outcome := go20_test.try_consume(1, repeat('b',64), repeat('c',64), repeat('1',64));
    IF outcome <> 'REPLAY' THEN
        RAISE EXCEPTION 'replay accepted: %', outcome;
    END IF;
    outcome := go20_test.try_consume(1, repeat('a',64), repeat('c',64), repeat('2',64));
    IF outcome <> 'STALE_STATE' THEN
        RAISE EXCEPTION 'state hash conflict accepted: %', outcome;
    END IF;
    outcome := go20_test.try_consume(1, repeat('b',64), repeat('c',64), 'invalid');
    IF outcome <> 'INVALID_INPUT' THEN
        RAISE EXCEPTION 'invalid digest accepted: %', outcome;
    END IF;
    SELECT revision INTO revision_seen FROM go20_test.state;
    IF revision_seen <> 1 THEN
        RAISE EXCEPTION 'failed attempts changed revision: %', revision_seen;
    END IF;
END $$;

-- Deliberate failure after both writes: exception subtransaction rolls back.
DO $$
DECLARE outcome text;
BEGIN
    BEGIN
        outcome := go20_test.try_consume(1, repeat('b',64), repeat('c',64), repeat('3',64));
        IF outcome <> 'TEST_ONLY_COMMIT' THEN
            RAISE EXCEPTION 'unexpected outcome: %', outcome;
        END IF;
        RAISE EXCEPTION 'injected failure after all writes';
    EXCEPTION WHEN raise_exception THEN
        NULL;
    END;
    IF (SELECT revision FROM go20_test.state) <> 1 THEN
        RAISE EXCEPTION 'revision changed despite rollback';
    END IF;
    IF EXISTS (SELECT 1 FROM go20_test.consumed WHERE entry_sha256 = repeat('3',64)) THEN
        RAISE EXCEPTION 'receipt survived injected rollback';
    END IF;
END $$;

-- The transaction that was rolled back may be retried once.
DO $$
BEGIN
    IF go20_test.try_consume(1, repeat('b',64), repeat('c',64), repeat('3',64))
       <> 'TEST_ONLY_COMMIT' THEN
        RAISE EXCEPTION 'rollback retry failed';
    END IF;
    IF (SELECT revision FROM go20_test.state) <> 2 THEN
        RAISE EXCEPTION 'recovery revision mismatch';
    END IF;
    IF (SELECT count(*) FROM go20_test.consumed) <> 2 THEN
        RAISE EXCEPTION 'recovery receipt count mismatch';
    END IF;
END $$;
