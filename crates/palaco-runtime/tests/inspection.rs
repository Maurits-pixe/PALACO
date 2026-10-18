use palaco_runtime::inspection::{write_status, write_status_json};
use std::io::{self, Write};

struct Destination {
    bytes: Vec<u8>,
    remaining: usize,
}

impl Write for Destination {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return Err(io::Error::from(io::ErrorKind::PermissionDenied));
        }
        let count = bytes.len().min(self.remaining).min(3);
        self.bytes.extend_from_slice(&bytes[..count]);
        self.remaining -= count;
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        panic!("inspection API must leave flushing to its caller");
    }
}

#[test]
fn short_writes_produce_the_complete_report_without_flushing() -> io::Result<()> {
    for json in [false, true] {
        let mut expected = Vec::new();
        let mut destination = Destination {
            bytes: Vec::new(),
            remaining: usize::MAX,
        };
        if json {
            write_status_json(&mut expected)?;
            write_status_json(&mut destination)?;
        } else {
            write_status(&mut expected)?;
            write_status(&mut destination)?;
        }
        assert_eq!(destination.bytes, expected);
    }
    Ok(())
}

#[test]
fn write_failures_propagate_before_and_after_partial_output() {
    for json in [false, true] {
        for remaining in [0, 10] {
            let mut destination = Destination {
                bytes: Vec::new(),
                remaining,
            };
            let result = if json {
                write_status_json(&mut destination)
            } else {
                write_status(&mut destination)
            };
            assert_eq!(
                result.expect_err("destination must fail").kind(),
                io::ErrorKind::PermissionDenied
            );
            assert_eq!(destination.bytes.len(), remaining);
        }
    }
}

#[test]
fn trait_object_destinations_are_supported() -> io::Result<()> {
    let mut text = Vec::new();
    let mut json = Vec::new();
    write_status(&mut text as &mut dyn Write)?;
    write_status_json(&mut json as &mut dyn Write)?;
    assert!(text.starts_with(b"PALACO runtime "));
    assert!(json.starts_with(b"{\"schema_version\":1,"));
    Ok(())
}
