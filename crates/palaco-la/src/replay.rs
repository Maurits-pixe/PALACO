use crate::event::EventEnvelope;
use crate::signature::CanonicalVerifier;
use crate::verification::Sha256Digest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReplayError {
    EmptyHistory,
    SequenceMismatch,
    AggregateMismatch,
    PredecessorMismatch,
    PayloadHashMismatch,
    InvalidSignature,
}

pub fn verify_history(
    events: &[EventEnvelope],
    verifier: &CanonicalVerifier,
) -> Result<(), ReplayError> {
    let first = events.first().ok_or(ReplayError::EmptyHistory)?;
    if !first.is_genesis() {
        return Err(ReplayError::PredecessorMismatch);
    }

    for (index, event) in events.iter().enumerate() {
        if index > 0 {
            let previous = &events[index - 1];
            if event.aggregate_id != previous.aggregate_id
                || event.aggregate_type != previous.aggregate_type
            {
                return Err(ReplayError::AggregateMismatch);
            }
            if event.sequence != previous.sequence.next() {
                return Err(ReplayError::SequenceMismatch);
            }
            if event.previous_event_hash != Some(previous.payload_hash) {
                return Err(ReplayError::PredecessorMismatch);
            }
        }

        if Sha256Digest::calculate(&event.payload) != event.payload_hash {
            return Err(ReplayError::PayloadHashMismatch);
        }

        if verifier.verify(&event.payload, &event.signature).is_err() {
            return Err(ReplayError::InvalidSignature);
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::{AggregateId, EventEnvelope, EventId, SchemaVersion, Sequence};
    use crate::signature::CanonicalSigner;
    use crate::verification::CanonicalBytes;
    use chrono::Utc;
    use ed25519_dalek::SigningKey;
    use uuid::Uuid;

    fn history() -> (Vec<EventEnvelope>, CanonicalVerifier) {
        let signer = CanonicalSigner::from_key(SigningKey::from_bytes(&[7_u8; 32]));
        let aggregate_id = AggregateId::new(Uuid::new_v4());
        let first_payload = CanonicalBytes::new(b"one".to_vec());
        let first_signature = signer.sign(&first_payload);
        let first = EventEnvelope::new(
            EventId::new(Uuid::new_v4()),
            "AuthorizationIssued".to_owned(),
            aggregate_id,
            "Authorization".to_owned(),
            Sequence::genesis(),
            Utc::now(),
            Utc::now(),
            Uuid::new_v4(),
            Some(Uuid::new_v4()),
            None,
            None,
            first_payload,
            None,
            SchemaVersion(1),
            Uuid::new_v4(),
            first_signature,
        );
        let second_payload = CanonicalBytes::new(b"two".to_vec());
        let second_signature = signer.sign(&second_payload);
        let second = EventEnvelope::new(
            EventId::new(Uuid::new_v4()),
            "AuthorizationInvalidated".to_owned(),
            aggregate_id,
            "Authorization".to_owned(),
            Sequence(2),
            Utc::now(),
            Utc::now(),
            Uuid::new_v4(),
            first.authority_reference,
            None,
            Some(first.event_id),
            second_payload,
            Some(first.payload_hash),
            SchemaVersion(1),
            first.provenance,
            second_signature,
        );
        (
            vec![first, second],
            CanonicalVerifier::from_key(signer.verifying_key()),
        )
    }

    #[test]
    fn valid_history_replays() {
        let (events, verifier) = history();
        assert_eq!(verify_history(&events, &verifier), Ok(()));
    }

    #[test]
    fn tampered_payload_fails_replay() {
        let (mut events, verifier) = history();
        events[1].payload = CanonicalBytes::new(b"tampered".to_vec());
        assert_eq!(
            verify_history(&events, &verifier),
            Err(ReplayError::PayloadHashMismatch)
        );
    }

    #[test]
    fn broken_predecessor_fails_replay() {
        let (mut events, verifier) = history();
        events[1].previous_event_hash = None;
        assert_eq!(
            verify_history(&events, &verifier),
            Err(ReplayError::PredecessorMismatch)
        );
    }
}
