-- GO-20 v37: DISPOSABLE CI PostgreSQL ONLY. No production migration.
-- Identity, payload and independently pinned evidence digests are mandatory.
BEGIN;
CREATE SCHEMA go20_v37;
CREATE TABLE go20_v37.claims (
  request_id text PRIMARY KEY CHECK (length(request_id) BETWEEN 1 AND 128),
  manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  pin_sha256 text NOT NULL CHECK (pin_sha256 ~ '^[0-9a-f]{64}$'),
  segments_sha256 text NOT NULL CHECK (segments_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT unique_restore_material UNIQUE (
    manifest_sha256, pin_sha256, segments_sha256
  )
);
CREATE FUNCTION go20_v37.try_claim(
  v_request_id text, v_manifest text, v_pin text, v_segments text
) RETURNS text LANGUAGE plpgsql
SET search_path = pg_catalog, go20_v37
AS $fn$
DECLARE
  inserted integer;
  by_id record;
  by_material record;
BEGIN
  IF v_request_id IS NULL OR length(v_request_id) NOT BETWEEN 1 AND 128 OR
     v_manifest IS NULL OR v_manifest !~ '^[0-9a-f]{64}$' OR
     v_pin IS NULL OR v_pin !~ '^[0-9a-f]{64}$' OR
     v_segments IS NULL OR v_segments !~ '^[0-9a-f]{64}$'
  THEN RETURN 'INVALID_INPUT'; END IF;

  INSERT INTO go20_v37.claims(request_id, manifest_sha256, pin_sha256, segments_sha256)
    VALUES (v_request_id, v_manifest, v_pin, v_segments)
    ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  IF inserted = 1 THEN RETURN 'TEST_ONLY_COMMIT'; END IF;

  SELECT manifest_sha256, pin_sha256, segments_sha256 INTO by_id
    FROM go20_v37.claims WHERE request_id = v_request_id;
  IF FOUND THEN
    IF by_id.manifest_sha256 = v_manifest AND
       by_id.pin_sha256 = v_pin AND
       by_id.segments_sha256 = v_segments
    THEN RETURN 'REPLAY'; END IF;
    RETURN 'CONFLICT';
  END IF;

  SELECT request_id INTO by_material
    FROM go20_v37.claims WHERE manifest_sha256 = v_manifest AND
    pin_sha256 = v_pin AND segments_sha256 = v_segments;
  IF FOUND THEN RETURN 'REPLAY'; END IF;
  -- If another transaction is still committing, do not claim success.
  RETURN 'UNRESOLVED_CONCURRENCY';
END
$fn$;
COMMIT;
