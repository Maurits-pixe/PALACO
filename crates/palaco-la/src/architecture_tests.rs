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
        ];

        assert_eq!(rules.len(), 8);
    }
}
