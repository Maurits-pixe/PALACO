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

## Validation

From `/home/runner/work/PALACO/PALACO`:

`node --check verification/era-pad-comparator/era-pad-comparator.mjs`

`node --test verification/era-pad-comparator/era-pad-comparator.test.mjs`

Technical contract review remains the next gate, not production activation.
