CREATE SCHEMA IF NOT EXISTS la;

CREATE TABLE IF NOT EXISTS la.events (
    event_id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    aggregate_type TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    actor_id UUID NOT NULL,
    authority_reference UUID,
    correlation_id UUID,
    causation_id UUID,
    payload JSONB NOT NULL,
    payload_hash BYTEA NOT NULL CHECK (octet_length(payload_hash) = 32),
    previous_event_hash BYTEA CHECK (previous_event_hash IS NULL OR octet_length(previous_event_hash) = 32),
    schema_version SMALLINT NOT NULL,
    provenance UUID NOT NULL,
    signature BYTEA NOT NULL,
    UNIQUE (aggregate_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_la_events_aggregate_sequence
    ON la.events (aggregate_id, sequence);

CREATE INDEX IF NOT EXISTS idx_la_events_correlation
    ON la.events (correlation_id)
    WHERE correlation_id IS NOT NULL;
