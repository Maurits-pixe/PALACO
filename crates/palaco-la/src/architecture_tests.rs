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
        ];

        assert_eq!(rules.len(), 13);
    }
}
