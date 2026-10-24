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
Numeric tokens with a nonzero decimal significand that round to zero are rejected
(positive or negative underflow); exponent digits do not make a zero significand
nonzero. Exact positive zero forms such as `0e-999` and `0.000e+999` remain valid;
negative zero remains invalid. Other finite numbers still use IEEE-754 rounding,
including representable tiny positive values; this is not arbitrary-precision
decimal validation. The object API cannot recover lexical precision or detect
underflow that occurred before it received a JavaScript number.
JSON escapes are decoded normally; raw_result hashing covers exactly the decoded
string's UTF-8 bytes, not the JSON source spelling. No trimming or normalization.
Parse failures reuse the existing HOLD/NONE REJECTED/INVALID_INPUT diagnostic
without any raw content.

### Optional independently selected request context

`compareEraPadJsonForRequest(bytes, expectedContext)` is a distinct additive export
from `era-pad-json.mjs`. The existing object API, `compareEraPadJson` and CLI are
unchanged; the input schema/version is unchanged. It shares the bounded byte,
fatal UTF-8 and duplicate-rejecting parser above, parses once and validates the
parsed local object with `compareEraPad`.

The caller must independently select `expectedContext`, not derive it from the
incoming JSON. It is exactly an Object.prototype or null-prototype object with
only two own enumerable **data** fields: `assessment_id` (1–128 ASCII characters
from `[A-Za-z0-9._:-]`) and `request_digest` (exactly 64 lowercase hex characters).
Missing, undefined, null, extra, nonenumerable, accessor, symbol and exotic
properties/objects are rejected. Frozen contexts are accepted. Descriptor `.value`
fields are snapshotted into a local null-prototype object without invoking field
getters or mutating the caller. Ordinary JavaScript Proxy inspection traps are
not sandboxable: inspection can execute traps, and caught errors are sanitized.
This is not a claim that adversarial JavaScript objects can be inspected without
executing their code.

Precedence and privacy:
- Invalid expected context, malformed bytes/JSON or invalid fixed input schema
  returns the existing sanitized REJECTED/INVALID_INPUT diagnostic first.
- For valid context and input, compare expected fields with the **root**
  `assessment_id` and `request_digest`, not only pad/temporal references. Either
  root mismatch overrides inner binding, integrity and normalization outcomes:
  result=REJECTED, reason=BINDING_MISMATCH, binding_status=MISMATCH. Other independent
  comparator status fields remain unchanged, as do all HOLD/NONE invariants.
  This report is status-only: pad and temporal are omitted so misbound payloads
  are not echoed.
- When both root fields match, return the existing comparator report unchanged,
  including diagnostic pad/temporal payloads for existing inner binding, integrity
  or normalization mismatches.

Expected context is an unverified host-selected reference, not trusted or
authenticated context. Matching adds no authenticity, authorization, replay
prevention, freshness, authority, network, durable state or clock guarantees.

Run `node /home/runner/work/PALACO/PALACO/verification/era-pad-comparator/era-pad-cli.mjs` with binary stdin and
**no arguments**; there is no file reader or optional raw-export mode. It reads no
more than the byte budget into retained buffers and destroys input on excess,
timeout, end or error. A fixed two-second deadline covers input acquisition only:
EOF is required, even after a complete JSON document. This is not a hard-realtime
guarantee or a sandbox; event-loop scheduling and process startup can add latency.
Empty/truncated input, stream errors, premature close, timeout and invalid arguments
emit only the sanitized INVALID_INPUT diagnostic, never fixture text, errors,
paths, IDs or hashes.

Every CLI report omits pad and temporal, including for valid but inconsistent
fixtures. It attempts one JSON status line without retries or stderr fallback.
Exit 0 requires both CONSISTENT_SYNTHETIC_ONLY (including FAIL/ERROR/TIMEOUT/UNKNOWN
PAD codes) and a successful local output write callback; all other outcomes exit 2.
Output acknowledgement has a separate fixed two-second deadline, bounded by
event-loop scheduling, not realtime. Write throws, callback errors, stream errors,
premature close, unavailable output and timeout destroy output without exposing
raw errors. A failed owned output retains a minimal error listener because an
asynchronous error can follow its callback or destruction; successful output
retains no listener. The callback does not establish delivery, durability or
consumer acceptance. Transport failure may expose partial sanitized status;
there is no guarantee of one complete line on failed output.
Neither exit code grants permission or authority.
Importing the CLI module has no execution side effects. There is no network,
database, server, external service, BRI9ADE change or new protocol evidence.

### Separate mandatory request-bound CLI

Run `node /home/runner/work/PALACO/PALACO/verification/era-pad-comparator/era-pad-request-cli.mjs ASSESSMENT_ID REQUEST_DIGEST`
with binary stdin. Exactly two positional references are required, using the same
ID length/ASCII and lowercase digest constraints as `compareEraPadJsonForRequest`.
There are no flags, options or file inputs. The host must independently select both
references; neither JSON nor environment variables supply context or a fallback.
These arguments can be visible in OS process listings: use only non-secret
synthetic references, never credentials. This adds no trust provisioning or
authentication claim.

The wrapper calls `mainForRequest()` in the existing CLI module. Both entrypoints
share a private runner and the same two-second input/output deadlines, byte budget,
stream destruction, sanitized output handling and exit rules above. Invalid
argument count or syntax destroys stdin immediately, before waiting for input or
EOF, and attempts only the existing INVALID_INPUT status with exit 2. Valid
arguments invoke `compareEraPadJsonForRequest`: malformed JSON/schema takes
INVALID_INPUT precedence over a mismatching context; valid mismatches use
BINDING_MISMATCH. Every bound CLI output is status-only, including matching
contexts; no arguments, IDs, digests, paths, raw input or errors are echoed.
Exit 0 requires CONSISTENT_SYNTHETIC_ONLY and local output acknowledgement.
Importing either CLI module performs no I/O. The original CLI remains no-argument
only; the new wrapper never silently chooses its unbound behavior.

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
`era-pad-request.test.mjs` checks the additive request-context API against all 12
golden snapshots and both existing APIs, coherent/root-only/nested-only
substitutions, precedence, status-only privacy, strict context descriptors,
caller isolation and the shared byte-parser boundaries.
`era-pad-request-cli.test.mjs` runs the real request wrapper in fresh processes
against all 12 golden statuses with matching root references, coherent component
substitutions, malformed-input precedence, argument rejection without EOF, ID
boundaries, import isolation, actual acquisition timeout and excess incoming
bytes. Fresh injected `mainForRequest` processes also check delayed output
acknowledgement, sanitized output errors and the actual output deadline.
All child tests have fixed timeouts and hung-child cleanup.

`era-pad-schema.test.mjs` pins an explicit 22-field matrix (root 7, pad 6,
temporal 7, uncertainty 2): 22 deletions, 22 disallowed boolean types and four
extra-key mutations. Each checks exact sanitized INVALID_INPUT output through
the object and byte APIs, including matching and valid mismatching host contexts,
without changing caller inputs. Eight fresh CLI processes cover one mutation per
object layer through both entrypoints. Positive controls preserve nullable times
and uncertainty independently and in all combinations, plus empty raw_result
with a fixed empty-string SHA-256 and UNKNOWN normalization.

`era-pad-duplicates.test.mjs` pins the same 22 paths (root 7, pad 6, temporal 7,
uncertainty 2): 88 textual mutations pair original values with boolean true in
both orders, using exact keys and first-ASCII-character `\uXXXX` equivalents.
Both byte APIs require the literal golden INVALID_INPUT report without payload,
including matching and valid mismatching host contexts. Native JSON.parse is
only a fixture control verifying last-key-wins values and exact target paths.
Five duplicate-free representations of all 11 structurally valid goldens preserve
exact statuses/payloads and Unicode raw values/digests: ordinary, recursively
reversed, legal whitespace, every property name escaped, and their combination.
Sixteen fresh CLI children pair spellings across both entrypoints at four object
layers in both orders, checking exact sanitized output, exit 2 and empty stderr
with five-second timeouts and hung-child cleanup. This bounded CLI sample is not
the full API cross-product; equal-value duplicates are not separately enumerated.

`era-pad-stream.test.mjs` exercises the actual CLI `main` in fresh child processes
with scheduled standard-stream writes and child-side chunk-count assertions:
split raw UTF-8/emoji and JSON escapes/surrogate pairs, cumulative byte limits,
incomplete UTF-8/truncated JSON at EOF, errors after complete JSON and premature
close. It checks exact corpus status-only output, exits and sanitization with
bounded timeouts and child cleanup. These deterministic injected streams do not
establish OS-pipe chunk boundaries, transport behavior or hard-realtime guarantees;
the existing deadline tests remain separate.
This is bounded consistency conformance only: shared implementation paths and
hand-authored expectations are not an independent protocol oracle, ERA service,
revocation, browser-acceptance, trusted-time or authority evidence.

From `/home/runner/work/PALACO/PALACO`:

`for path in /home/runner/work/PALACO/PALACO/verification/era-pad-comparator/*.mjs; do node --check "$path" || break; done`

`node --test /home/runner/work/PALACO/PALACO/verification/era-pad-comparator/*.test.mjs`

`node --test /home/runner/work/PALACO/PALACO/verification/rio-accounts/test_login_observation.mjs /home/runner/work/PALACO/PALACO/verification/rio-accounts/test_safe_reporter.mjs`

The separate `.github/workflows/era-pad-comparator.yml` runs syntax checks for all
comparator modules, this test suite and the existing offline login-observation and
sanitized-reporter regression suites in separate Node 22 and 24 matrix jobs.
Each job has its own five-minute timeout; fail-fast is disabled so a failure on
one runtime does not cancel verification on the other. Node 22 checks the
documented minimum major version; this matrix does not certify every newer major
or every patch version. Adding matrix jobs is not evidence that they have run.
Relevant path-filtered pushes
and pull requests trigger it; manual dispatch is also available. Pull requests
test GitHub's merge ref; pushes/manual runs test the event ref. The workflow uses
SHA-pinned actions, read-only contents permission, no persisted checkout
credentials, no package installation/cache, no secrets, no browser/database
fixture, no artifact upload and no deployment. Checkout and Node provisioning
still require network; only verification itself is offline. A green run is not
trusted-time, revocation-recovery, browser-acceptance or production evidence.

Technical contract review remains the next gate, not production activation.
