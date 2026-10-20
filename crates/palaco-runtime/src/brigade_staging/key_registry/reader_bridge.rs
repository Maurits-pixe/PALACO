//! Versioned Python-reader snapshot import, never proof that a reader ran.
//!
//! The host supplies bytes over its own private channel. A caller can forge any
//! field; no signature, pin verification or provenance is inferred in Rust.
//! Rust does not spawn Python or acquire file/network data through this module.

use super::{
    Binding, ClockSample, KeyRecord, KeyRegistryAdapter, MAX_RECORDS, Mode, RegistryError,
    Snapshot, reference_valid,
};

/// Maximum UTF-8 bridge bytes, including the mandatory final newline.
pub const MAX_BRIDGE_BYTES: usize = 140_000;
const HEADER: &str = "BRIGADE_UNVERIFIED_SNAPSHOT_V1";

fn next<'a>(fields: &mut impl Iterator<Item = &'a str>) -> Result<&'a str, RegistryError> {
    fields.next().ok_or(RegistryError::Invalid)
}

fn number<'a>(fields: &mut impl Iterator<Item = &'a str>) -> Result<u64, RegistryError> {
    let field = next(fields)?;
    if field.is_empty()
        || field.len() > 20
        || !field.bytes().all(|byte| byte.is_ascii_digit())
        || (field.len() > 1 && field.starts_with('0'))
    {
        return Err(RegistryError::Invalid);
    }
    field.parse().map_err(|_| RegistryError::Invalid)
}

fn reference<'a>(fields: &mut impl Iterator<Item = &'a str>) -> Result<String, RegistryError> {
    let field = next(fields)?;
    if !reference_valid(field) {
        return Err(RegistryError::Invalid);
    }
    Ok(field.to_owned())
}

fn decode(bytes: &[u8]) -> Result<Snapshot, RegistryError> {
    if bytes.len() > MAX_BRIDGE_BYTES {
        return Err(RegistryError::Invalid);
    }
    let text = std::str::from_utf8(bytes).map_err(|_| RegistryError::Invalid)?;
    let body = text.strip_suffix('\n').ok_or(RegistryError::Invalid)?;
    let mut fields = body.split('\n');
    if next(&mut fields)? != HEADER {
        return Err(RegistryError::Invalid);
    }
    let mode = match next(&mut fields)? {
        "Synthetic" => Mode::Synthetic,
        "LocalObservation" => Mode::LocalObservation,
        _ => return Err(RegistryError::Invalid),
    };
    let revision = reference(&mut fields)?;
    let issued_at = number(&mut fields)?;
    let expires_at = number(&mut fields)?;
    let count = number(&mut fields)?;
    if count > MAX_RECORDS as u64 {
        return Err(RegistryError::Invalid);
    }
    let mut records = Vec::new();
    for _ in 0..count {
        records.push(KeyRecord {
            tenant: reference(&mut fields)?,
            actor: reference(&mut fields)?,
            device: reference(&mut fields)?,
            key_ref: reference(&mut fields)?,
            epoch: number(&mut fields)?,
            valid_from: number(&mut fields)?,
            expires_at: number(&mut fields)?,
            revoked: match next(&mut fields)? {
                "0" => false,
                "1" => true,
                _ => return Err(RegistryError::Invalid),
            },
        });
    }
    if fields.next().is_some() {
        return Err(RegistryError::Invalid);
    }
    Ok(Snapshot {
        revision,
        mode,
        issued_at,
        expires_at,
        records,
    })
}

impl KeyRegistryAdapter {
    /// Import unverified snapshot bytes, bound to host-selected context and key.
    ///
    /// Reject malformed/trailing data, mode/revision mismatch and stale snapshots.
    /// The local clock is not authenticated. A successful import grants no rights
    /// and does not authenticate the Python file pin or the host's transport.
    pub fn from_reader_bytes(
        bytes: &[u8],
        expected_revision: &str,
        mode: Mode,
        binding: &Binding,
        key_ref: &str,
    ) -> Result<Self, RegistryError> {
        let now = ClockSample::observe().map_err(|_| RegistryError::Unavailable)?;
        Self::from_reader_at(
            bytes,
            expected_revision,
            mode,
            binding,
            key_ref,
            now.unix_seconds,
        )
    }

    fn from_reader_at(
        bytes: &[u8],
        expected_revision: &str,
        mode: Mode,
        binding: &Binding,
        key_ref: &str,
        now: u64,
    ) -> Result<Self, RegistryError> {
        let snapshot = decode(bytes)?;
        let adapter = Self::new(Some(&snapshot), expected_revision, mode, binding, key_ref)?;
        if now < snapshot.issued_at || now >= snapshot.expires_at {
            return Err(RegistryError::Unavailable);
        }
        Ok(adapter)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::brigade_staging::{Checkpoint, Finding};

    fn binding() -> Binding {
        Binding {
            challenge: "fixture-challenge".into(),
            contract_digest: "fixture-digest".into(),
            sender: "actor".into(),
            recipient: "recipient".into(),
            sender_device: "device".into(),
            recipient_device: "other-device".into(),
            tenant_context: "tenant".into(),
            policy_version: "policy".into(),
            key_epoch: 1,
            checkpoint: Checkpoint::ServiceCommit,
        }
    }

    const VECTOR: &str = "BRIGADE_UNVERIFIED_SNAPSHOT_V1\nSynthetic\nr1\n100\n150\n1\ntenant\nactor\ndevice\nkey\n1\n90\n200\n0\n";

    fn import(bytes: &[u8], now: u64) -> Result<KeyRegistryAdapter, RegistryError> {
        KeyRegistryAdapter::from_reader_at(bytes, "r1", Mode::Synthetic, &binding(), "key", now)
    }

    #[test]
    fn pinned_contract_vector_imports_only_unverified_findings() {
        for revoked in [false, true] {
            let vector = if revoked {
                VECTOR.strip_suffix("0\n").expect("fixture").to_owned() + "1\n"
            } else {
                VECTOR.into()
            };
            let adapter = import(vector.as_bytes(), 120).expect("fixture");
            assert_eq!(
                adapter
                    .observe_at(&binding(), 120)
                    .expect("current")
                    .finding,
                if revoked {
                    Finding::Negative
                } else {
                    Finding::Positive
                },
            );
        }
    }

    #[test]
    fn every_truncation_trailing_data_and_bad_encoding_is_rejected() {
        for end in 0..VECTOR.len() {
            assert!(
                import(&VECTOR.as_bytes()[..end], 120).is_err(),
                "prefix {end}"
            );
        }
        for suffix in ["\n", "junk\n", "0\n"] {
            assert!(import((VECTOR.to_owned() + suffix).as_bytes(), 120).is_err());
        }
        assert!(import(&[0xff, b'\n'], 120).is_err());
        assert!(import(&vec![b'x'; MAX_BRIDGE_BYTES + 1], 120).is_err());
    }

    #[test]
    fn versions_modes_counts_and_noncanonical_numbers_are_rejected() {
        for (old, new) in [
            ("SNAPSHOT_V1", "SNAPSHOT_V2"),
            ("Synthetic", "LocalObservation"),
            ("\nr1\n", "\nr2\n"),
            ("\n100\n", "\n0100\n"),
            ("\n100\n", "\n+100\n"),
            ("\n100\n", "\n18446744073709551616\n"),
            ("\n1\ntenant", "\n129\ntenant"),
            ("\n1\ntenant", "\n0\ntenant"),
            ("\n0\n", "\nfalse\n"),
            ("\nactor\n", "\nact\tor\n"),
            ("\n150\n", "\n161\n"),
            ("\n90\n", "\n200\n"),
        ] {
            assert!(
                import(VECTOR.replace(old, new).as_bytes(), 120).is_err(),
                "{new}"
            );
        }
        for now in [99, 150, u64::MAX] {
            assert!(import(VECTOR.as_bytes(), now).is_err());
        }
    }

    #[test]
    fn duplicate_records_are_not_hidden_in_bridge() {
        let vector = VECTOR.replace("\n1\ntenant", "\n2\ntenant")
            + "tenant\nactor\ndevice\nother-key\n1\n90\n200\n1\n";
        assert!(matches!(
            import(vector.as_bytes(), 120),
            Err(RegistryError::DuplicateBinding)
        ));
    }
}
