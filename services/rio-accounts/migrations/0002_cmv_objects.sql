-- Explicit opt-in for the synthetic storage API, not account activation.
CREATE TABLE IF NOT EXISTS rio_synthetic.cmv_objects (
    account_id text NOT NULL,
    owner_id text NOT NULL,
    tenant_id text NOT NULL,
    object_id bytea NOT NULL CHECK (octet_length(object_id)=32),
    payload bytea NOT NULL CHECK (octet_length(payload)<=16384),
    digest bytea NOT NULL CHECK (octet_length(digest)=32),
    created_ms bigint NOT NULL CHECK (created_ms>=0),
    expires_ms bigint NOT NULL CHECK (expires_ms>created_ms AND expires_ms<=created_ms+86400000),
    state text NOT NULL CHECK (state IN ('LIVE','DELETED','EXPIRED')),
    CHECK (state='LIVE' OR octet_length(payload)=0),
    PRIMARY KEY (account_id,object_id),
    FOREIGN KEY (account_id,owner_id,tenant_id)
        REFERENCES rio_synthetic.accounts(account_id,owner_id,tenant_id)
);
-- At most one creation and one terminal event per retained object. No payload,
-- credential, user filename or arbitrary audit text is retained here.
CREATE TABLE IF NOT EXISTS rio_synthetic.cmv_events (
    account_id text NOT NULL,
    object_id bytea NOT NULL,
    phase smallint NOT NULL CHECK (phase IN (0,1)),
    event_type text NOT NULL CHECK (event_type IN ('STORED','DELETED','EXPIRED')),
    at_ms bigint NOT NULL CHECK (at_ms>=0),
    CHECK ((phase=0 AND event_type='STORED') OR (phase=1 AND event_type IN ('DELETED','EXPIRED'))),
    PRIMARY KEY(account_id,object_id,phase),
    FOREIGN KEY(account_id,object_id) REFERENCES rio_synthetic.cmv_objects(account_id,object_id)
);
CREATE OR REPLACE TRIGGER cmv_events_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON rio_synthetic.cmv_events
FOR EACH STATEMENT EXECUTE FUNCTION rio_synthetic.reject_audit_change();
