use chrono::{SecondsFormat, Utc};
use palaco_runtime::sixri9ade::{self, GateBundleV01, GateInputV01};
use std::io::{self, Read, Write};
use std::process;

const BUNDLE_SCHEMA: &str = "elixer-6ri9ade-bundle-v0.1";
const MAX_INPUT_BYTES: usize = 1_048_576;

fn main() {
    if let Err(error) = run() {
        eprintln!("6RI9ADE evaluator: {error}");
        process::exit(2);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let input = read_bounded(io::stdin().lock())?;
    let bundle = parse_bundle(&input)?;
    let now = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    let result = sixri9ade::evaluate(
        GateInputV01 {
            request: &bundle.request,
            initiation: &bundle.initiation,
            nova_admission: &bundle.nova_admission,
            evidence: &bundle.evidence,
            final_receipts: &bundle.final_receipts,
            initial_snapshot: &bundle.initial_snapshot,
            final_snapshot: &bundle.final_snapshot,
        },
        &now,
    );
    let stdout = io::stdout();
    let mut output = stdout.lock();
    serde_json::to_writer_pretty(&mut output, &result)?;
    output.write_all(b"\n")?;
    Ok(())
}

fn read_bounded(mut reader: impl Read) -> io::Result<Vec<u8>> {
    let mut input = Vec::new();
    reader
        .by_ref()
        .take((MAX_INPUT_BYTES + 1) as u64)
        .read_to_end(&mut input)?;
    if input.len() > MAX_INPUT_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "input exceeds the 1 MiB limit",
        ));
    }
    Ok(input)
}

fn parse_bundle(input: &[u8]) -> Result<GateBundleV01, &'static str> {
    let bundle: GateBundleV01 =
        serde_json::from_slice(input).map_err(|_| "invalid or incomplete JSON bundle")?;
    if bundle.schema != BUNDLE_SCHEMA {
        return Err("unsupported bundle schema");
    }
    Ok(bundle)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundle_input_size_is_bounded() {
        let input = vec![b' '; MAX_INPUT_BYTES + 1];
        assert!(read_bounded(input.as_slice()).is_err());
    }

    #[test]
    fn bundle_rejects_unknown_or_incomplete_contracts() {
        assert!(parse_bundle(br#"{"schema":"elixer-6ri9ade-bundle-v0.1","active":true}"#).is_err());
        assert!(parse_bundle(br#"{"schema":"wrong-version"}"#).is_err());
    }
}
