//! Missing-evidence boundary between OIDC login and personal activation.
//! This value grants no role, account access or runtime authority.

/// Fixed refusal metadata; no actor or client claim can strengthen it.
#[derive(Debug, PartialEq, Eq)]
pub struct Boundary {
    pub schema: &'static str,
    pub strong_authentication: &'static str,
    pub lifecycle_authority: &'static str,
    pub activation_eligible: bool,
    pub reason: &'static str,
}

/// The BFF currently retains no validated strong-authentication evidence.
pub fn blocked_assurance() -> Boundary {
    Boundary {
        schema: "rio-personal-account-boundary/v1",
        strong_authentication: "UNKNOWN",
        lifecycle_authority: "NONE",
        activation_eligible: false,
        reason: "STRONG_AUTHENTICATION_EVIDENCE_MISSING",
    }
}

#[cfg(test)]
mod tests {
    use super::{Boundary, blocked_assurance};

    #[test]
    fn oidc_login_does_not_attest_strong_authentication_or_activation() {
        assert_eq!(
            blocked_assurance(),
            Boundary {
                schema: "rio-personal-account-boundary/v1",
                strong_authentication: "UNKNOWN",
                lifecycle_authority: "NONE",
                activation_eligible: false,
                reason: "STRONG_AUTHENTICATION_EVIDENCE_MISSING",
            }
        );
    }
}
