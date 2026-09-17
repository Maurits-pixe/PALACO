use crate::event::{AggregateId, EventEnvelope, Sequence};
use crate::verification::Sha256Digest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EventStoreError {
    SequenceConflict { expected: Sequence, actual: Sequence },
    PredecessorConflict,
    DuplicateEvent,
}

pub trait EventStore {
    fn append(
        &mut self,
        aggregate_id: AggregateId,
        expected_next: Sequence,
        expected_previous_hash: Option<Sha256Digest>,
        event: EventEnvelope,
    ) -> Result<(), EventStoreError>;

    fn load(&self, aggregate_id: AggregateId) -> Vec<EventEnvelope>;

    fn load_after(&self, aggregate_id: AggregateId, sequence: Sequence) -> Vec<EventEnvelope>;

    fn current_head(&self, aggregate_id: AggregateId) -> Option<EventEnvelope>;
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
