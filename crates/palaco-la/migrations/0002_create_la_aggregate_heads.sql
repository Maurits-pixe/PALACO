CREATE TABLE IF NOT EXISTS la.aggregate_heads (
    aggregate_id UUID PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    current_sequence BIGINT NOT NULL CHECK (current_sequence >= 0),
    current_event_hash BYTEA CHECK (
        current_event_hash IS NULL OR octet_length(current_event_hash) = 32
    )
);

CREATE OR REPLACE FUNCTION la.reject_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'la.events is append-only: % is forbidden', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS la_events_no_mutation ON la.events;

CREATE TRIGGER la_events_no_mutation
BEFORE UPDATE OR DELETE ON la.events
FOR EACH ROW
EXECUTE FUNCTION la.reject_event_mutation();
