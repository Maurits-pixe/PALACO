//! Embeds inspection reporting without spawning the runtime CLI.

use palaco_runtime::inspection::write_status_json;
use std::io::{self, BufWriter, Write};

fn main() -> io::Result<()> {
    let stdout = io::stdout().lock();
    let mut output = BufWriter::new(stdout);
    write_status_json(&mut output)?;
    output.flush()
}
