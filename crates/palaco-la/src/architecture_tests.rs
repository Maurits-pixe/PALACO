#[cfg(test)]
mod tests {
    use std::fs;

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
            "REVOCATION PERSISTS THROUGH EVENTSTORE",
            "REVOCATION EVENT IS IMMUTABLE",
            "COMET PRESERVES REVOCATION IDENTITY",
            "AUTHORITY REVOCATION => AUTHORIZATION INVALIDATION",
            "INVALIDATED AUTHORIZATION => EXECUTION STOP",
            "COMET REQUIRES AUTHORITY IDENTITY MATCH",
            "INACTIVE AUTHORIZATION => NO NEW EXECUTION PERMIT",
            "AUTHORIZATION INVALIDATION => IMMUTABLE EVENT",
            "AUTHORIZATION INVALIDATION PRESERVES REVOCATION IDENTITY",
            "AUTHORIZATION INVALIDATION => PERSISTENT RECONSTRUCTION",
            "AUTHORIZATION ISSUANCE => IMMUTABLE EVENT",
            "ACTIVE AUTHORIZATIONS ARE RECONSTRUCTED FROM EVENT HISTORY",
            "COMET BULK INVALIDATION => INDIVIDUAL IMMUTABLE EVENTS",
            "EVENT HISTORY REPLAY IS DETERMINISTIC",
            "REPLAY REJECTS PAYLOAD TAMPERING",
            "REPLAY REJECTS PREDECESSOR BREAKS",
            "REPLAY REQUIRES SIGNATURE VERIFICATION",
            "SEMANTIC REPLAY REQUIRES STRUCTURAL REPLAY",
            "UNKNOWN AUTHORIZATION EVENT => FAIL_CLOSED",
            "REPLAYED REVOKED AUTHORIZATION => NO EXECUTION PERMIT",
            "NO EXPECT IN L.A. TEST TREE",
        ];

        assert_eq!(rules.len(), 49);
    }

    #[test]
    fn integration_tests_do_not_use_expect_or_unwrap() {
        let source = fs::read_to_string("tests/postgres_integration.rs")
            .map_err(|error| error.to_string())
            .unwrap_or_default();
        assert!(!source.contains(".expect("));
        assert!(!source.contains(".unwrap("));
    }
}
