use chrono::{DateTime, Utc};
use ed25519_dalek::Signature;
use uuid::Uuid;

use crate::verification::{CanonicalBytes, Sha256Digest};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct EventId(pub Uuid);

impl EventId {
    pub fn new(value: Uuid) -> Self {
        Self(value)
    }

    pub fn value(self) -> Uuid {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AggregateId(pub Uuid);

impl AggregateId {
    pub fn new(value: Uuid) -> Self {
        Self(value)
    }

    pub fn value(self) -> Uuid {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Sequence(pub u64);

impl Sequence {
    pub fn genesis() -> Self {
        Self(1)
    }

    pub fn next(self) -> Self {
        Self(self.0 + 1)
    }

    pub fn value(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SchemaVersion(pub u16);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventEnvelope {
    pub event_id: EventId,
    pub event_type: String,
    pub aggregate_id: AggregateId,
    pub aggregate_type: String,
    pub sequence: Sequence,
    pub occurred_at: DateTime<Utc>,
    pub recorded_at: DateTime<Utc>,
    pub actor_id: Uuid,
    pub authority_reference: Option<Uuid>,
    pub correlation_id: Option<Uuid>,
    pub causation_id: Option<EventId>,
    pub payload: CanonicalBytes,
    pub payload_hash: Sha256Digest,
    pub previous_event_hash: Option<Sha256Digest>,
    pub schema_version: SchemaVersion,
    pub provenance: Uuid,
    pub signature: Signature,
}

impl EventEnvelope {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        event_id: EventId,
        event_type: String,
        aggregate_id: AggregateId,
        aggregate_type: String,
        sequence: Sequence,
        occurred_at: DateTime<Utc>,
        recorded_at: DateTime<Utc>,
        actor_id: Uuid,
        authority_reference: Option<Uuid>,
        correlation_id: Option<Uuid>,
        causation_id: Option<EventId>,
        payload: CanonicalBytes,
        previous_event_hash: Option<Sha256Digest>,
        schema_version: SchemaVersion,
        provenance: Uuid,
        signature: Signature,
    ) -> Self {
        let payload_hash = Sha256Digest::calculate(&payload);
        Self {
            event_id,
            event_type,
            aggregate_id,
            aggregate_type,
            sequence,
            occurred_at: normalize_timestamp(occurred_at),
            recorded_at: normalize_timestamp(recorded_at),
            actor_id,
            authority_reference,
            correlation_id,
            causation_id,
            payload,
            payload_hash,
            previous_event_hash,
            schema_version,
            provenance,
            signature,
        }
    }

    pub fn is_genesis(&self) -> bool {
        self.sequence == Sequence::genesis() && self.previous_event_hash.is_none()
    }
}

fn normalize_timestamp(timestamp: DateTime<Utc>) -> DateTime<Utc> {
    let microseconds = (timestamp.timestamp_subsec_nanos() / 1_000) * 1_000;
    match DateTime::from_timestamp(timestamp.timestamp(), microseconds) {
        Some(normalized) => normalized,
        None => timestamp,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn genesis_event_has_no_predecessor() {
        let signer =
            crate::CanonicalSigner::from_key(ed25519_dalek::SigningKey::from_bytes(&[7_u8; 32]));
        let payload = CanonicalBytes::new(b"genesis".to_vec());
        let signature = signer.sign(&payload);
        let event = EventEnvelope::new(
            EventId::new(Uuid::new_v4()),
            "QuestionCreated".to_owned(),
            AggregateId::new(Uuid::new_v4()),
            "Question".to_owned(),
            Sequence::genesis(),
            Utc::now(),
            Utc::now(),
            Uuid::new_v4(),
            None,
            None,
            None,
            payload,
            None,
            SchemaVersion(1),
            Uuid::new_v4(),
            signature,
        );

        assert!(event.is_genesis());
        assert_eq!(event.sequence.value(), 1);
    }

    #[test]
    fn event_timestamps_use_microsecond_precision() {
        let signer =
            crate::CanonicalSigner::from_key(ed25519_dalek::SigningKey::from_bytes(&[7_u8; 32]));
        let timestamp = match DateTime::from_timestamp(1_000, 123_456_789) {
            Some(value) => value,
            None => return,
        };
        let payload = CanonicalBytes::new(b"timestamp".to_vec());
        let signature = signer.sign(&payload);
        let event = EventEnvelope::new(
            EventId::new(Uuid::new_v4()),
            "QuestionCreated".to_owned(),
            AggregateId::new(Uuid::new_v4()),
            "Question".to_owned(),
            Sequence::genesis(),
            timestamp,
            timestamp,
            Uuid::new_v4(),
            None,
            None,
            None,
            payload,
            None,
            SchemaVersion(1),
            Uuid::new_v4(),
            signature,
        );

        assert_eq!(event.occurred_at.timestamp_subsec_nanos(), 123_456_000);
        assert_eq!(event.recorded_at.timestamp_subsec_nanos(), 123_456_000);
    }

    #[test]
    fn payload_hash_is_derived_from_exact_payload_bytes() {
        let signer = crate::CanonicalSigner::from_key(
            ed25519_dalek::SigningKey::from_bytes(&[7_u8; 32]),
        );
        let payload = CanonicalBytes::new(b"exact-payload".to_vec());
        let expected = Sha256Digest::calculate(&payload);
        let signature = signer.sign(&payload);
        let event = EventEnvelope::new(
            EventId::new(Uuid::new_v4()),
            "EvidenceRecorded".to_owned(),
            AggregateId::new(Uuid::new_v4()),
            "Evidence".to_owned(),
            Sequence::genesis(),
            Utc::now(),
            Utc::now(),
            Uuid::new_v4(),
            None,
            None,
            None,
            payload,
            None,
            SchemaVersion(1),
            Uuid::new_v4(),
            signature,
        );

        assert_eq!(event.payload_hash, expected);
    }
}
