use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalBytes(Vec<u8>);

impl CanonicalBytes {
    pub fn new(bytes: Vec<u8>) -> Self {
        Self(bytes)
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Sha256Digest([u8; 32]);

impl Sha256Digest {
    pub fn calculate(bytes: &CanonicalBytes) -> Self {
        let digest = Sha256::digest(bytes.as_slice());
        let mut value = [0_u8; 32];
        value.copy_from_slice(&digest);
        Self(value)
    }

    pub fn from_bytes(bytes: [u8; 32]) -> Self {
        Self(bytes)
    }

    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_is_deterministic_for_exact_bytes() {
        let bytes = CanonicalBytes::new(b"PALACO-LA".to_vec());
        assert_eq!(Sha256Digest::calculate(&bytes), Sha256Digest::calculate(&bytes));
    }

    #[test]
    fn different_bytes_produce_different_digest() {
        let first = CanonicalBytes::new(b"A".to_vec());
        let second = CanonicalBytes::new(b"B".to_vec());
        assert_ne!(Sha256Digest::calculate(&first), Sha256Digest::calculate(&second));
    }

    #[test]
    fn digest_can_be_reconstructed_from_exact_bytes() {
        let bytes = CanonicalBytes::new(b"PALACO-LA".to_vec());
        let digest = Sha256Digest::calculate(&bytes);
        assert_eq!(Sha256Digest::from_bytes(*digest.as_bytes()), digest);
    }
}
