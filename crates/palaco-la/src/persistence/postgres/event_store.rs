use chrono::{DateTime, Utc};
use ed25519_dalek::Signature;
use sqlx::{postgres::PgPool, Row};
use uuid::Uuid;

use crate::event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
use crate::event_store::{EventStore, EventStoreError};
use crate::verification::{CanonicalBytes, Sha256Digest};

/// PostgreSQL implementation of the constitutional append-only event boundary.
///
/// Each aggregate owns one mutable head row solely for concurrency control and
/// reconstruction acceleration. The event history itself is never updated or
/// deleted.
pub struct PgEventStore {
    pool: PgPool,
}

impl PgEventStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    pub async fn migrate(&self) -> Result<(), EventStoreError> {
        sqlx::migrate!("./migrations")
            .run(&self.pool)
            .await
            .map_err(|error| EventStoreError::Persistence(error.to_string()))
    }
}

impl EventStore for PgEventStore {
    async fn append(
        &self,
        aggregate_id: AggregateId,
        expected_next: Sequence,
        expected_previous_hash: Option<Sha256Digest>,
        event: EventEnvelope,
    ) -> Result<(), EventStoreError> {
        if event.aggregate_id != aggregate_id {
            return Err(EventStoreError::Persistence(
                "event aggregate_id does not match append aggregate_id".to_owned(),
            ));
        }

        let calculated_hash = Sha256Digest::calculate(&event.payload);
        if calculated_hash != event.payload_hash {
            return Err(EventStoreError::Persistence(
                "event payload_hash does not match exact payload bytes".to_owned(),
            ));
        }

        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?;

        sqlx::query(
            "INSERT INTO la.aggregate_heads (aggregate_id, aggregate_type, current_sequence, current_event_hash)
             VALUES ($1, $2, 0, NULL)
             ON CONFLICT (aggregate_id) DO NOTHING",
        )
        .bind(aggregate_id.value())
        .bind(&event.aggregate_type)
        .execute(&mut *transaction)
        .await
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;

        let head = sqlx::query(
            "SELECT aggregate_type, current_sequence, current_event_hash
             FROM la.aggregate_heads
             WHERE aggregate_id = $1
             FOR UPDATE",
        )
        .bind(aggregate_id.value())
        .fetch_one(&mut *transaction)
        .await
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;

        let aggregate_type: String = head
            .try_get("aggregate_type")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
        if aggregate_type != event.aggregate_type {
            return Err(EventStoreError::Persistence(
                "aggregate_type cannot change for an existing aggregate".to_owned(),
            ));
        }

        let current_sequence: i64 = head
            .try_get("current_sequence")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
        let current_hash: Option<Vec<u8>> = head
            .try_get("current_event_hash")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
        let actual_next = Sequence((current_sequence as u64) + 1);

        if expected_next != actual_next || event.sequence != expected_next {
            return Err(EventStoreError::SequenceConflict {
                expected: expected_next,
                actual: actual_next,
            });
        }

        let actual_previous_hash = current_hash
            .as_deref()
            .map(digest_from_bytes)
            .transpose()
            .map_err(EventStoreError::Persistence)?;
        if actual_previous_hash != expected_previous_hash
            || event.previous_event_hash != expected_previous_hash
        {
            return Err(EventStoreError::PredecessorConflict);
        }

        sqlx::query(
            "INSERT INTO la.events (
                event_id, event_type, aggregate_id, aggregate_type, sequence,
                occurred_at, recorded_at, actor_id, authority_reference,
                correlation_id, causation_id, payload, payload_hash,
                previous_event_hash, schema_version, provenance, signature
             ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17
             )",
        )
        .bind(event.event_id.value())
        .bind(&event.event_type)
        .bind(event.aggregate_id.value())
        .bind(&event.aggregate_type)
        .bind(event.sequence.value() as i64)
        .bind(event.occurred_at)
        .bind(event.recorded_at)
        .bind(event.actor_id)
        .bind(event.authority_reference)
        .bind(event.correlation_id)
        .bind(event.causation_id.map(EventId::value))
        .bind(event.payload.as_slice())
        .bind(event.payload_hash.as_bytes().as_slice())
        .bind(event.previous_event_hash.map(|digest| digest.as_bytes().to_vec()))
        .bind(event.schema_version.0 as i16)
        .bind(event.provenance)
        .bind(event.signature.to_bytes().as_slice())
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            if error
                .as_database_error()
                .and_then(|database| database.code())
                .as_deref()
                == Some("23505")
            {
                EventStoreError::DuplicateEvent
            } else {
                EventStoreError::Persistence(error.to_string())
            }
        })?;

        sqlx::query(
            "UPDATE la.aggregate_heads
             SET current_sequence = $2, current_event_hash = $3
             WHERE aggregate_id = $1",
        )
        .bind(aggregate_id.value())
        .bind(event.sequence.value() as i64)
        .bind(event.payload_hash.as_bytes().as_slice())
        .execute(&mut *transaction)
        .await
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;

        transaction
            .commit()
            .await
            .map_err(|error| EventStoreError::Persistence(error.to_string()))
    }

    async fn load(&self, aggregate_id: AggregateId) -> Result<Vec<EventEnvelope>, EventStoreError> {
        load_events(&self.pool, aggregate_id, None).await
    }

    async fn load_after(
        &self,
        aggregate_id: AggregateId,
        sequence: Sequence,
    ) -> Result<Vec<EventEnvelope>, EventStoreError> {
        load_events(&self.pool, aggregate_id, Some(sequence)).await
    }

    async fn current_head(&self, aggregate_id: AggregateId) -> Result<Option<EventEnvelope>, EventStoreError> {
        let row = sqlx::query(
            "SELECT event_id, event_type, aggregate_id, aggregate_type, sequence,
                    occurred_at, recorded_at, actor_id, authority_reference,
                    correlation_id, causation_id, payload, payload_hash,
                    previous_event_hash, schema_version, provenance, signature
             FROM la.events
             WHERE aggregate_id = $1
             ORDER BY sequence DESC
             LIMIT 1",
        )
        .bind(aggregate_id.value())
        .fetch_optional(&self.pool)
        .await
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;

        row.map(event_from_row).transpose()
    }
}

async fn load_events(
    pool: &PgPool,
    aggregate_id: AggregateId,
    after: Option<Sequence>,
) -> Result<Vec<EventEnvelope>, EventStoreError> {
    let rows = match after {
        Some(sequence) => {
            sqlx::query(
                "SELECT event_id, event_type, aggregate_id, aggregate_type, sequence,
                        occurred_at, recorded_at, actor_id, authority_reference,
                        correlation_id, causation_id, payload, payload_hash,
                        previous_event_hash, schema_version, provenance, signature
                 FROM la.events
                 WHERE aggregate_id = $1 AND sequence > $2
                 ORDER BY sequence ASC",
            )
            .bind(aggregate_id.value())
            .bind(sequence.value() as i64)
            .fetch_all(pool)
            .await
        }
        None => {
            sqlx::query(
                "SELECT event_id, event_type, aggregate_id, aggregate_type, sequence,
                        occurred_at, recorded_at, actor_id, authority_reference,
                        correlation_id, causation_id, payload, payload_hash,
                        previous_event_hash, schema_version, provenance, signature
                 FROM la.events
                 WHERE aggregate_id = $1
                 ORDER BY sequence ASC",
            )
            .bind(aggregate_id.value())
            .fetch_all(pool)
            .await
        }
    }
    .map_err(|error| EventStoreError::Persistence(error.to_string()))?;

    rows.into_iter().map(event_from_row).collect()
}

fn event_from_row(row: sqlx::postgres::PgRow) -> Result<EventEnvelope, EventStoreError> {
    let signature_bytes: Vec<u8> = row
        .try_get("signature")
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
    let signature_array: [u8; 64] = signature_bytes
        .as_slice()
        .try_into()
        .map_err(|_| EventStoreError::Persistence("invalid Ed25519 signature length".to_owned()))?;

    let payload: Vec<u8> = row
        .try_get("payload")
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
    let payload_hash_bytes: Vec<u8> = row
        .try_get("payload_hash")
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
    let payload_hash = digest_from_bytes(&payload_hash_bytes).map_err(EventStoreError::Persistence)?;

    let previous_hash_bytes: Option<Vec<u8>> = row
        .try_get("previous_event_hash")
        .map_err(|error| EventStoreError::Persistence(error.to_string()))?;
    let previous_event_hash = previous_hash_bytes
        .as_deref()
        .map(digest_from_bytes)
        .transpose()
        .map_err(EventStoreError::Persistence)?;

    let event = EventEnvelope {
        event_id: EventId::new(
            row.try_get::<Uuid, _>("event_id")
                .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        ),
        event_type: row
            .try_get("event_type")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        aggregate_id: AggregateId::new(
            row.try_get::<Uuid, _>("aggregate_id")
                .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        ),
        aggregate_type: row
            .try_get("aggregate_type")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        sequence: Sequence(
            row.try_get::<i64, _>("sequence")
                .map_err(|error| EventStoreError::Persistence(error.to_string()))?
                as u64,
        ),
        occurred_at: row
            .try_get::<DateTime<Utc>, _>("occurred_at")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        recorded_at: row
            .try_get::<DateTime<Utc>, _>("recorded_at")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        actor_id: row
            .try_get("actor_id")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        authority_reference: row
            .try_get("authority_reference")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        correlation_id: row
            .try_get("correlation_id")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        causation_id: row
            .try_get::<Option<Uuid>, _>("causation_id")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?
            .map(EventId::new),
        payload: CanonicalBytes::new(payload),
        payload_hash,
        previous_event_hash,
        schema_version: SchemaVersion(
            row.try_get::<i16, _>("schema_version")
                .map_err(|error| EventStoreError::Persistence(error.to_string()))?
                as u16,
        ),
        provenance: row
            .try_get("provenance")
            .map_err(|error| EventStoreError::Persistence(error.to_string()))?,
        signature: Signature::from_bytes(&signature_array),
    };

    let calculated_hash = Sha256Digest::calculate(&event.payload);
    if calculated_hash != event.payload_hash {
        return Err(EventStoreError::Persistence(
            "persisted payload_hash does not match exact payload bytes".to_owned(),
        ));
    }

    Ok(event)
}

fn digest_from_bytes(bytes: &[u8]) -> Result<Sha256Digest, String> {
    let array: [u8; 32] = bytes
        .try_into()
        .map_err(|_| "invalid SHA-256 digest length".to_owned())?;
    Ok(Sha256Digest::from_bytes(array))
}
