#[cfg(test)]
mod tests {
    #[test]
    fn constitutional_boundaries_are_explicit() {
        let rules = [
            "ACCESS != AUTHORIZATION",
            "DECISION != AUTHORITY",
            "DECISION != EXECUTION",
            "AUTHORITY != AUTHORIZATION",
            "AUTHORIZATION != EXECUTION",
            "AUTHORIZATION REQUIRED FOR EXECUTION",
            "EXECUTION PERMIT REQUIRED",
            "SIGNATURE != AUTHORITY",
            "PROVENANCE != PERMISSION",
            "UNKNOWN => FAIL_CLOSED",
            "QUESTION != EVIDENCE",
            "EVIDENCE != EPISTEMIC_STATE",
            "THRESHOLD != DECISION",
            "EXECUTION RECEIPT != EXECUTION PERMIT",
            "OBSERVATION != EXECUTION",
            "EXECUTION SUCCESS REQUIRES OBSERVATION",
            "UNKNOWN EXECUTION OUTCOME => FAIL_CLOSED",
            "CONSEQUENCE != OBSERVATION",
            "REASSESSMENT REQUIRES NEW HISTORY",
            "REVOCATION => STOP",
            "EXPIRATION => STOP",
            "SUSPENSION => REASSESS",
            "ACTIVE AUTHORITY => LIFECYCLE MAY CONTINUE",
            "REVOKE => PROPAGATE",
            "REVOCATION PRESERVES PROVENANCE",
            "REVOCATION DOES NOT REWRITE HISTORY",
            "PROPAGATION STATUS IS EXPLICIT",
            "AUTHORIZATION BINDS AUTHORITY IDENTITY",
            "MISMATCHED AUTHORITY => STOP",
        ];

        assert_eq!(rules.len(), 28);
    }
}
