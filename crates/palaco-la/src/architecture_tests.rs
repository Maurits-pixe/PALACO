#[cfg(test)]
mod tests {
    #[test]
    fn constitutional_boundaries_are_explicit() {
        let rules = [
            "ACCESS != AUTHORIZATION",
            "DECISION != EXECUTION",
            "SIGNATURE != AUTHORITY",
            "PROVENANCE != PERMISSION",
            "UNKNOWN => FAIL_CLOSED",
            "QUESTION != EVIDENCE",
            "EVIDENCE != EPISTEMIC_STATE",
            "THRESHOLD != DECISION",
            "DECISION != AUTHORIZATION",
            "DECISION != EXECUTION",
        ];

        assert_eq!(rules.len(), 10);
    }
}
