use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};

use crate::verification::CanonicalBytes;

/// PVB-011 signing boundary.
///
/// The signer receives the exact canonical byte sequence. No semantic
/// transformation is permitted between canonicalization and signing.
pub struct CanonicalSigner {
    key: SigningKey,
}

impl CanonicalSigner {
    pub fn from_key(key: SigningKey) -> Self {
        Self { key }
    }

    pub fn sign(&self, bytes: &CanonicalBytes) -> Signature {
        self.key.sign(bytes.as_slice())
    }

    pub fn verifying_key(&self) -> VerifyingKey {
        self.key.verifying_key()
    }
}

/// PVB-011 verification boundary.
///
/// Verification is performed against the exact bytes supplied by the caller.
/// A valid signature proves authenticity/integrity of those bytes; it does
/// not grant constitutional authority or permission.
pub struct CanonicalVerifier {
    key: VerifyingKey,
}

impl CanonicalVerifier {
    pub fn from_key(key: VerifyingKey) -> Self {
        Self { key }
    }

    pub fn verify(
        &self,
        bytes: &CanonicalBytes,
        signature: &Signature,
    ) -> Result<(), ed25519_dalek::SignatureError> {
        self.key.verify(bytes.as_slice(), signature)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand_core::OsRng;

    #[test]
    fn exact_bytes_are_signed_and_verified() {
        let signer = CanonicalSigner::from_key(SigningKey::generate(&mut OsRng));
        let bytes = CanonicalBytes::new(b"PALACO-PVB-011".to_vec());
        let signature = signer.sign(&bytes);
        let verifier = CanonicalVerifier::from_key(signer.verifying_key());

        assert!(verifier.verify(&bytes, &signature).is_ok());
    }

    #[test]
    fn changed_bytes_fail_verification() {
        let signer = CanonicalSigner::from_key(SigningKey::generate(&mut OsRng));
        let original = CanonicalBytes::new(b"original".to_vec());
        let changed = CanonicalBytes::new(b"changed".to_vec());
        let signature = signer.sign(&original);
        let verifier = CanonicalVerifier::from_key(signer.verifying_key());

        assert!(verifier.verify(&changed, &signature).is_err());
    }
}
