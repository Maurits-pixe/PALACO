# ERA/P.G.E. offline EDTR + PAD comparator v0.1

Status: SYNTHETIC_ONLY / source_authenticity=UNVERIFIED. No ERA service, issued
EDTR, seal, conformance, readiness, signing, database, network or external clock.
The prototype checkout is unavailable; this is a separate PALACO verification
component, not a claim of integration with that prototype or BRI9ADE.
Notion preparation is task context only; its source commit/pin is UNKNOWN.
No new interpretation of historical EDTR protocols is asserted.

## Input contract

`compareEraPad(input)` accepts a plain JavaScript object, not JSON text. Objects
must have Object.prototype or null prototype and exactly the own enumerable data
properties below (no accessors, symbols or inherited application properties).
Arrays, exotic prototypes and additional/missing fields are rejected. Every
string must be well-formed Unicode. All limits are inclusive.

Maximum input: 16,384 UTF-8 bytes of `JSON.stringify(input)` after structural
validation; individual limits apply first, avoiding unbounded traversal.
Maximum depth is the fixed structure below. This API does not parse JSON,
resolve duplicate JSON keys or execute a fixture runner.

| Object | Exact fields and values |
| --- | --- |
| root | schema_version=`ERA_PAD_COMPARATOR_V1`, classification=`SYNTHETIC_ONLY`, source_authenticity=`UNVERIFIED`, assessment_id, request_digest, pad, temporal |
| pad | assessment_id, request_digest, observation_id, raw_result, raw_result_sha256, normalized_result |
| temporal | assessment_id, request_digest, source_kind, observed_at, recorded_at, sync_status, uncertainty |
| uncertainty | null, or exactly value and unit |

IDs (`assessment_id`, `observation_id`) are 1–128 ASCII characters from
`[A-Za-z0-9._:-]`. Every request_digest and raw_result_sha256 is exactly 64 lowercase
hex characters. Request digests are unverified opaque context references.
`raw_result` is an unchanged UTF-8 string of 0–4096 bytes.
SHA-256 covers precisely those UTF-8 bytes, without trimming, case changes,
Unicode normalization, serialization, newline addition or replacement characters.
The digest verifies consistency, not authenticity.

Normalized codes are exactly PASS, FAIL, UNKNOWN, ERROR, TIMEOUT.
Raw strings exactly matching those tokens map to the same code; all other raw
strings (including whitespace/case variations) map only to UNKNOWN. No positive
inference from free text. An ERROR/TIMEOUT/UNKNOWN cannot normalize to PASS.
Mismatched normalization is diagnostic REJECTED, while retaining valid PAD data.

source_kind is SYNTHETIC_FIXTURE or UNKNOWN. sync_status is SYNCHRONIZED,
UNSYNCHRONIZED or UNKNOWN. Each time is null or canonical UTC
`YYYY-MM-DDTHH:mm:ss.sssZ`, years 0001–9999, with calendar validity checked by
round-trip; offsets, leap seconds and impossible dates are rejected.
Uncertainty is null or a finite number value >=0 plus unit `ms` or `s`, with
converted milliseconds <=86,400,000. Negative zero is rejected.
No inferred timestamp, sequence, EDTR ID, generation, signature or seal.

## Output and precedence

Every result includes classification=SYNTHETIC_ONLY, source_authenticity=UNVERIFIED,
disposition=HOLD, operativeAuthority=NONE, canOpenContact=false,
runtimeConnected=false, externalSideEffect=false and commit_order=UNKNOWN.
REJECTED never means an authenticated guard STOP.

Malformed shape/type/value/limit -> result=REJECTED, reason=INVALID_INPUT;
binding_status, temporal_status, pad_status, integrity_status are UNKNOWN.
No rejected raw input is echoed.

For structurally valid input, return independent copied pad and temporal data:
- binding_status is MATCH or MISMATCH against root assessment_id/request_digest.
- integrity_status is MATCH or INTEGRITY_MISMATCH against unchanged raw bytes.
- pad_status is the raw-derived code; normalization_status is MATCH or MISMATCH.
- temporal_status is KNOWN only with SYNTHETIC_FIXTURE, both times present,
  SYNCHRONIZED and explicit zero uncertainty; otherwise UNKNOWN.
  KNOWN means complete synthetic context only, not trusted time.

Binding mismatch takes precedence (REJECTED/BINDING_MISMATCH), then digest mismatch
(INTEGRITY_MISMATCH), then normalization mismatch (REJECTED/NORMALIZATION_MISMATCH).
Otherwise result=CONSISTENT_SYNTHETIC_ONLY, even for UNKNOWN/ERROR/TIMEOUT/FAIL or
incomplete temporal context: consistency is never a positive operational verdict.
PAD data is retained when time is missing/uncertain. Output has no references to
caller-owned objects; no writes or durable state. Identical repetition creates
no authority. Equal timestamps establish no commit order, replay prevention or
rollback protection. No polling or live freshness guarantee.

## Additive JSON byte adapter and offline CLI (v0.1 scope extension)

The object API above is unchanged. `compareEraPadJson(bytes)` in `era-pad-json.mjs`
accepts only Buffer/Uint8Array views with at most 16,384 incoming bytes, including
whitespace and JSON escapes. The existing serialized-object and raw-result limits
also still apply. UTF-8 decoding is fatal: malformed byte sequences and a leading
BOM are rejected, not repaired or silently removed.

The bounded parser accepts one JSON root object, JSON whitespace only, no arrays,
and at most three object levels (root, pad/temporal, uncertainty). It rejects
duplicate decoded keys at every level, including escaped equivalent names,
trailing input, comments, malformed numbers, nonfinite numeric values and malformed
Unicode (including lone escaped surrogates in keys or values). Unknown fields still
fail the existing comparator schema. Scans and allocations are bounded by the
incoming byte limit; recursion is bounded by the object-depth limit.
JSON escapes are decoded normally; raw_result hashing covers exactly the decoded
string's UTF-8 bytes, not the JSON source spelling. No trimming or normalization.
Parse failures reuse the existing HOLD/NONE REJECTED/INVALID_INPUT diagnostic
without any raw content.

Run `node verification/era-pad-comparator/era-pad-cli.mjs` with binary stdin and
**no arguments**; there is no file reader or optional raw-export mode. It reads no
more than the byte budget into retained buffers and destroys input on excess,
timeout, end or error. A fixed two-second deadline covers input acquisition only:
EOF is required, even after a complete JSON document. This is not a hard-realtime
guarantee or a sandbox; event-loop scheduling and process startup can add latency.
Empty/truncated input, stream errors, premature close, timeout and invalid arguments
emit only the sanitized INVALID_INPUT diagnostic, never fixture text, errors,
paths, IDs or hashes.

Every CLI report omits pad and temporal, including for valid but inconsistent
fixtures. It emits one JSON status line. Exit 0 means only
CONSISTENT_SYNTHETIC_ONLY (including FAIL/ERROR/TIMEOUT/UNKNOWN PAD codes);
all other outcomes exit 2. Neither exit code grants permission or authority.
Importing the CLI module has no execution side effects. There is no network,
database, server, external service, BRI9ADE change or new protocol evidence.

## Validation

`era-pad-vectors.v0.1.json` is a test-only shared corpus of 12 fully explicit,
fictional SYNTHETIC_ONLY inputs, complete literal status-only snapshots and CLI
exits. Its exact harness schema is `corpus_version=ERA_PAD_VECTORS_V0.1`,
`classification`, `source_authenticity`, `vectors`; each vector has exactly `id`,
`structurally_valid`, `input`, `expected_status`, `expected_cli_exit`.
Raw SHA-256 literals were independently authored with Node crypto (intentional
integrity failures use the fixed PASS digest for ERROR); tests do not compute
expected digests or derive expected statuses from the comparator.
`era-pad-vectors.test.mjs` checks all three entrypoints against these same fixed
snapshots, copied API payloads, sanitization, precedence and closed invariants,
with a five-second per-vector timeout and hung-child cleanup.
This is bounded consistency conformance only: shared implementation paths and
hand-authored expectations are not an independent protocol oracle, ERA service,
revocation, browser-acceptance, trusted-time or authority evidence.

From `/home/runner/work/PALACO/PALACO`:

`node --check verification/era-pad-comparator/era-pad-comparator.mjs`

`node --check verification/era-pad-comparator/era-pad-json.mjs`

`node --check verification/era-pad-comparator/era-pad-cli.mjs`

`node --check verification/era-pad-comparator/era-pad-json.test.mjs`

`node --test verification/era-pad-comparator/*.test.mjs`

The separate `.github/workflows/era-pad-comparator.yml` runs syntax checks for all
comparator modules, this test suite and the existing offline login-observation and
sanitized-reporter regression suites on Node 24. Relevant path-filtered pushes
and pull requests trigger it; manual dispatch is also available. Pull requests
test GitHub's merge ref; pushes/manual runs test the event ref. The workflow uses
SHA-pinned actions, read-only contents permission, no persisted checkout
credentials, no package installation/cache, no secrets, no browser/database
fixture, no artifact upload and no deployment. Checkout and Node provisioning
still require network; only verification itself is offline. A green run is not
trusted-time, revocation-recovery, browser-acceptance or production evidence.

Technical contract review remains the next gate, not production activation.
