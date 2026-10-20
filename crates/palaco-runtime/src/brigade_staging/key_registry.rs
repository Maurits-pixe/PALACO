//! BG05/sender snapshot diagnostics, not device enrollment or trusted revocation.
//!
//! The host must supply a separately obtained staging snapshot and expected
//! revision. Neither is authenticated here. There is no file/network reader,
//! isolated worker, timeout enforcement, live revocation or E2EE verification.

use super::{
    AdapterError, Binding, ClockSample, Finding, Mode, Observation, ObservationAdapter, Party, Role,
};

/// Maximum records accepted in one local diagnostic snapshot.
pub const MAX_RECORDS: usize = 128;
/// Maximum snapshot lifetime; this is a local bound, not a trusted-time lease.
pub const MAX_SNAPSHOT_SECONDS: u64 = 60;

/// Public references only. Never put private keys or personal identifiers here.
#[derive(Clone)]
pub struct KeyRecord {
    pub tenant: String,
    pub actor: String,
    pub device: String,
    pub key_ref: String,
    pub epoch: u64,
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked: bool,
}

/// Host-supplied, unverified register data. Modes do not prove provenance.
#[derive(Clone)]
pub struct Snapshot {
    pub revision: String,
    pub mode: Mode,
    pub issued_at: u64,
    pub expires_at: u64,
    pub records: Vec<KeyRecord>,
}

/// Sanitized construction failures, without source data in error messages.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RegistryError {
    Unavailable,
    Invalid,
    RevisionMismatch,
    DuplicateBinding,
}

/// Owned snapshot frozen to one complete request, mode and requested key.
///
/// This adapter never enrolls keys, trusts an issuer or upgrades guard coverage.
/// A new snapshot requires constructing a new adapter. A revision comparison is
/// not a digest check and cannot detect forged data under the same revision.
pub struct KeyRegistryAdapter {
    snapshot: Snapshot,
    binding: Binding,
    key_ref: String,
}

fn reference_valid(value: &str) -> bool {
    !value.trim().is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}

impl KeyRegistryAdapter {
    /// Copies only a bounded, structurally valid snapshot supplied by the host.
    ///
    /// `expected_revision` must come from host configuration, not the observation
    /// source. It prevents accidental version mismatch, not malicious substitution.
    pub fn new(
        snapshot: Option<&Snapshot>,
        expected_revision: &str,
        mode: Mode,
        binding: &Binding,
        key_ref: &str,
    ) -> Result<Self, RegistryError> {
        let snapshot = snapshot.ok_or(RegistryError::Unavailable)?;
        if !binding.well_formed()
            || !reference_valid(key_ref)
            || !reference_valid(expected_revision)
            || !reference_valid(&snapshot.revision)
            || snapshot.mode != mode
            || snapshot.records.len() > MAX_RECORDS
            || snapshot.expires_at <= snapshot.issued_at
            || snapshot.expires_at - snapshot.issued_at > MAX_SNAPSHOT_SECONDS
        {
            return Err(RegistryError::Invalid);
        }
        if snapshot.revision != expected_revision {
            return Err(RegistryError::RevisionMismatch);
        }
        for (index, record) in snapshot.records.iter().enumerate() {
            if ![
                &record.tenant,
                &record.actor,
                &record.device,
                &record.key_ref,
            ]
            .into_iter()
            .all(|value| reference_valid(value))
                || record.expires_at <= record.valid_from
            {
                return Err(RegistryError::Invalid);
            }
            if snapshot.records[..index].iter().any(|previous| {
                previous.tenant == record.tenant
                    && previous.actor == record.actor
                    && previous.device == record.device
                    && previous.epoch == record.epoch
            }) {
                return Err(RegistryError::DuplicateBinding);
            }
        }
        Ok(Self {
            snapshot: snapshot.clone(),
            binding: binding.clone(),
            key_ref: key_ref.to_owned(),
        })
    }

    fn observe_at(&self, binding: &Binding, now: u64) -> Result<Observation, AdapterError> {
        if *binding != self.binding
            || now < self.snapshot.issued_at
            || now >= self.snapshot.expires_at
        {
            return Err(AdapterError::Unavailable);
        }
        let record = self.snapshot.records.iter().find(|record| {
            record.tenant == binding.tenant_context
                && record.actor == binding.sender
                && record.device == binding.sender_device
                && record.epoch == binding.key_epoch
                && record.key_ref == self.key_ref
        });
        let Some(record) = record else {
            return Err(AdapterError::Unavailable);
        };
        if now < record.valid_from || now >= record.expires_at {
            return Err(AdapterError::Unavailable);
        }
        Ok(Observation {
            binding: binding.clone(),
            mode: self.snapshot.mode,
            role: Role::Bg05,
            party: Party::Sender,
            issued_at: now,
            expires_at: record.expires_at.min(self.snapshot.expires_at),
            finding: if record.revoked {
                Finding::Negative
            } else {
                Finding::Positive
            },
        })
    }
}

impl ObservationAdapter for KeyRegistryAdapter {
    fn observe(&self, binding: &Binding) -> Result<Observation, AdapterError> {
        self.observe_at(binding, ClockSample::observe()?.unix_seconds)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::brigade_staging::{Checkpoint, Coverage, Registration, evaluate};

    fn binding() -> Binding {
        Binding {
            challenge: "fixture-challenge".into(),
            contract_digest: "fixture-digest".into(),
            sender: "fixture-sender".into(),
            recipient: "fixture-recipient".into(),
            sender_device: "fixture-device".into(),
            recipient_device: "fixture-other-device".into(),
            tenant_context: "fixture-tenant".into(),
            policy_version: "fixture-policy".into(),
            key_epoch: 1,
            checkpoint: Checkpoint::ServiceCommit,
        }
    }

    fn snapshot() -> Snapshot {
        Snapshot {
            revision: "fixture-r1".into(),
            mode: Mode::Synthetic,
            issued_at: 100,
            expires_at: 150,
            records: vec![KeyRecord {
                tenant: "fixture-tenant".into(),
                actor: "fixture-sender".into(),
                device: "fixture-device".into(),
                key_ref: "fixture-key-reference".into(),
                epoch: 1,
                valid_from: 90,
                expires_at: 200,
                revoked: false,
            }],
        }
    }

    fn adapter(snapshot: &Snapshot) -> Result<KeyRegistryAdapter, RegistryError> {
        KeyRegistryAdapter::new(
            Some(snapshot),
            "fixture-r1",
            Mode::Synthetic,
            &binding(),
            "fixture-key-reference",
        )
    }

    #[test]
    fn active_and_revoked_are_only_unverified_register_findings() {
        for revoked in [false, true] {
            let mut source = snapshot();
            source.records[0].revoked = revoked;
            let adapter = adapter(&source).expect("fixture");
            let observation = adapter.observe_at(&binding(), 120).expect("current");
            assert_eq!(observation.role, Role::Bg05);
            assert_eq!(observation.party, Party::Sender);
            assert_eq!(
                observation.finding,
                if revoked {
                    Finding::Negative
                } else {
                    Finding::Positive
                }
            );
            assert_eq!(observation.expires_at, 150);
        }
    }

    #[test]
    fn missing_source_or_record_and_wrong_key_are_unavailable() {
        assert!(matches!(
            KeyRegistryAdapter::new(None, "fixture-r1", Mode::Synthetic, &binding(), "key"),
            Err(RegistryError::Unavailable)
        ));
        let mut source = snapshot();
        source.records.clear();
        assert_eq!(
            adapter(&source).expect("empty").observe_at(&binding(), 120),
            Err(AdapterError::Unavailable)
        );
        source = snapshot();
        source.records[0].key_ref = "different-key".into();
        assert_eq!(
            adapter(&source)
                .expect("fixture")
                .observe_at(&binding(), 120),
            Err(AdapterError::Unavailable)
        );
    }

    #[test]
    fn wrong_actor_device_tenant_and_epoch_never_match() {
        for field in 0..4 {
            let mut source = snapshot();
            let record = &mut source.records[0];
            match field {
                0 => record.actor.push('x'),
                1 => record.device.push('x'),
                2 => record.tenant.push('x'),
                _ => record.epoch += 1,
            }
            assert_eq!(
                adapter(&source)
                    .expect("fixture")
                    .observe_at(&binding(), 120),
                Err(AdapterError::Unavailable)
            );
        }
    }

    #[test]
    fn snapshot_and_record_time_boundaries_fail_closed() {
        let current = adapter(&snapshot()).expect("fixture");
        for now in [99, 150, u64::MAX] {
            assert_eq!(
                current.observe_at(&binding(), now),
                Err(AdapterError::Unavailable)
            );
        }
        assert!(current.observe_at(&binding(), 100).is_ok());
        for (valid_from, expires_at) in [(121, 200), (90, 120)] {
            let mut source = snapshot();
            source.records[0].valid_from = valid_from;
            source.records[0].expires_at = expires_at;
            assert_eq!(
                adapter(&source)
                    .expect("fixture")
                    .observe_at(&binding(), 120),
                Err(AdapterError::Unavailable)
            );
        }
    }

    #[test]
    fn modes_revisions_duplicates_and_malformed_data_are_rejected() {
        let mut source = snapshot();
        source.revision = "changed".into();
        assert!(matches!(
            adapter(&source),
            Err(RegistryError::RevisionMismatch)
        ));
        source = snapshot();
        source.mode = Mode::LocalObservation;
        assert!(matches!(adapter(&source), Err(RegistryError::Invalid)));
        source = snapshot();
        source.records.push(source.records[0].clone());
        source.records[1].key_ref = "conflicting-key".into();
        source.records[1].revoked = true;
        assert!(matches!(
            adapter(&source),
            Err(RegistryError::DuplicateBinding)
        ));
        for invalid in ["", " ", "bad\nreference", &"x".repeat(257)] {
            source = snapshot();
            source.records[0].key_ref = invalid.into();
            assert!(matches!(adapter(&source), Err(RegistryError::Invalid)));
        }
        for (issued_at, expires_at) in [(150, 100), (100, 100), (0, 61)] {
            source = snapshot();
            source.issued_at = issued_at;
            source.expires_at = expires_at;
            assert!(matches!(adapter(&source), Err(RegistryError::Invalid)));
        }
        source = snapshot();
        source.records = vec![source.records[0].clone(); MAX_RECORDS + 1];
        assert!(matches!(adapter(&source), Err(RegistryError::Invalid)));
    }

    #[test]
    fn snapshot_is_owned_and_cannot_be_rebound_to_another_request() {
        let mut source = snapshot();
        let adapter = adapter(&source).expect("fixture");
        source.records[0].revoked = true;
        source.revision = "fixture-r2".into();
        assert_eq!(
            adapter.observe_at(&binding(), 120).expect("frozen").finding,
            Finding::Positive
        );
        let mut changed = binding();
        changed.challenge.push('x');
        assert_eq!(
            adapter.observe_at(&changed, 120),
            Err(AdapterError::Unavailable)
        );
        changed = binding();
        changed.checkpoint = Checkpoint::QueuedDelivery;
        assert_eq!(
            adapter.observe_at(&changed, 120),
            Err(AdapterError::Unavailable)
        );
    }

    #[test]
    fn real_clock_adapter_integrates_without_granting_any_authority() {
        let now = ClockSample::observe().expect("test clock").unix_seconds;
        let mut source = snapshot();
        source.issued_at = now;
        source.expires_at = now + 60;
        source.records[0].valid_from = now;
        source.records[0].expires_at = now + 60;
        source.records[0].revoked = true;
        let adapter = adapter(&source).expect("fixture");
        let observed = adapter.observe(&binding()).expect("local read");
        struct Captured(Observation);
        impl ObservationAdapter for Captured {
            fn observe(&self, _: &Binding) -> Result<Observation, AdapterError> {
                Ok(self.0.clone())
            }
        }
        let captured = Captured(observed.clone());
        let report = evaluate(
            Mode::Synthetic,
            &binding(),
            Ok(ClockSample {
                unix_seconds: observed.issued_at,
            }),
            &[Registration {
                role: Role::Bg05,
                party: Party::Sender,
                adapter: &captured,
            }],
        );
        assert_eq!(
            report.controls[4].coverage,
            Coverage::Unverified(Finding::Negative)
        );
        assert_eq!(report.disposition(), "HOLD");
        assert_eq!(report.operative_authority(), "NONE");
        assert!(!report.can_open_contact());
        assert!(!report.runtime_connected());
        assert!(!report.external_side_effect());
        assert_eq!(
            report
                .controls
                .iter()
                .filter(|c| c.coverage == Coverage::Unknown)
                .count(),
            17
        );
    }
}
