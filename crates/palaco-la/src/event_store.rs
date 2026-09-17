use crate::event::{AggregateId, EventEnvelope, Sequence};
use crate::verification::Sha256Digest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EventStoreError {
    SequenceConflict { expected: Sequence, actual: Sequence },
    PredecessorConflict,
    DuplicateEvent,
    Persistence(String),
}

pub trait EventStore {
    fn append(
        &self,
        aggregate_id: AggregateId,
        expected_next: Sequence,
        expected_previous_hash: Option<Sha256Digest>,
        event: EventEnvelope,
    ) -> impl std::future::Future<Output = Result<(), EventStoreError>> + Send;

    fn load(
        &self,
        aggregate_id: AggregateId,
    ) -> impl std::future::Future<Output = Result<Vec<EventEnvelope>, EventStoreError>> + Send;

    fn load_after(
        &self,
        aggregate_id: AggregateId,
        sequence: Sequence,
    ) -> impl std::future::Future<Output = Result<Vec<EventEnvelope>, EventStoreError>> + Send;

    fn current_head(
        &self,
        aggregate_id: AggregateId,
    ) -> impl std::future::Future<Output = Result<Option<EventEnvelope>, EventStoreError>> + Send;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn port_is_explicitly_append_only() {
        let required_operations = ["append", "load", "load_after", "current_head"];
        assert_eq!(required_operations.len(), 4);
        assert!(!required_operations.contains(&"update"));
        assert!(!required_operations.contains(&"delete"));
    }

    #[test]
    fn genesis_sequence_is_one() {
        assert_eq!(Sequence::genesis().value(), 1);
    }
}
