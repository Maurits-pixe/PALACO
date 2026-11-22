-- GO-20 v11: TEST-ONLY PostgreSQL contract.
-- Run only in a throwaway PostgreSQL container/database.
-- No production migration, no GRANT, no SECURITY DEFINER, no release authority.
BEGIN;
CREATE SCHEMA go20_test;
CREATE TABLE go20_test.state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    revision bigint NOT NULL CHECK (revision >= 0),
    state_sha256 text NOT NULL CHECK (state_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE go20_test.consumed (
    entry_sha256 text PRIMARY KEY CHECK (entry_sha256 ~ '^[0-9a-f]{64}$')
);
INSERT INTO go20_test.state(singleton, revision, state_sha256)
VALUES (true, 0, repeat('a', 64));

CREATE FUNCTION go20_test.try_consume(
    expected_revision bigint,
    expected_state_sha256 text,
    next_state_sha256 text,
    entry_sha256 text
) RETURNS text
LANGUAGE plpgsql
SET search_path = pg_catalog, go20_test
AS $fn$
DECLARE
    current_revision bigint;
    current_hash text;
BEGIN
    IF expected_revision IS NULL OR expected_revision < 0 OR
       expected_state_sha256 IS NULL OR expected_state_sha256 !~ '^[0-9a-f]{64}$' OR
       next_state_sha256 IS NULL OR next_state_sha256 !~ '^[0-9a-f]{64}$' OR
       entry_sha256 IS NULL OR entry_sha256 !~ '^[0-9a-f]{64}$'
    THEN
        RETURN 'INVALID_INPUT';
    END IF;

    SELECT revision, state_sha256 INTO current_revision, current_hash
      FROM go20_test.state WHERE singleton = true FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'STATE_MISSING';
    END IF;
    IF current_revision <> expected_revision OR current_hash <> expected_state_sha256 THEN
        RETURN 'STALE_STATE';
    END IF;
    IF current_revision = 9223372036854775807 THEN
        RETURN 'REVISION_EXHAUSTED';
    END IF;

    INSERT INTO go20_test.consumed(entry_sha256) VALUES (entry_sha256)
      ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        RETURN 'REPLAY';
    END IF;
    UPDATE go20_test.state
       SET revision = current_revision + 1, state_sha256 = next_state_sha256
     WHERE singleton = true;
    RETURN 'TEST_ONLY_COMMIT';
END
$fn$;
COMMIT;
