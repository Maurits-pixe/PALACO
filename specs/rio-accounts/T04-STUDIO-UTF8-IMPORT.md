# T04 — Refuse damaged UTF-8 drafts without changing the open concept

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

Parent draft #74 at `34261f1c4a4c548a6433340d889d6b76d7838808` passed exact-head
GO-13 and full RIO. A subsequent actual-browser negative check demonstrated that
File.text() replacement-decoded invalid UTF-8 inside an otherwise valid draft.
Import accepted the altered text and overwrote the current fields and preview;
export then retained the replacement character. This is a local content-integrity
defect, not an authentication or account-authority finding.

Studio imports now read the file as bytes. Both the declared file size and returned
buffer must be nonempty and at most the existing 12288-byte limit. A fatal UTF-8
decoder refuses malformed byte sequences before JSON parsing or assigning any
draft/field state. Existing exact object/authority checks, field limits, import
generation guard, fixed feedback, focus and export behavior remain.

An invalid encoding uses the existing generic import error and leaves the current
fields, literal preview, counters and local draft label unchanged. A stale failed
or successful read cannot replace newer typed text or its feedback. Correctly
encoded replacement characters are legitimate text and remain accepted; emoji,
multiline content, optional UTF-8 BOM handling and canonical export remain
compatible. Native text-field/newline readback still follows the previous rule.

The separate presentation-only browser checks provide raw malformed File bytes
and require refusal with exact previous content preserved. Positive controls use
real valid UTF-8 bytes and compare canonical exports. The existing real mobile
Studio case also attempts a damaged file and retains its session/receipt,
zero-write, no-persistence and authority checks. The earlier stale-read test now
controls File.arrayBuffer(), the actual asynchronous read boundary.

This narrowly changes byte decoding. JSON member-duplication semantics are still
those of the existing JSON.parse; this draft makes no duplicate-member rejection
claim. No dependency, account, consent, provider binding, TLS, cookie, network,
polling, lifetime or storage rule changes. Full exact-head RIO is required;
offline presentation evidence does not establish real authentication or human
accessibility acceptance.

Historical causes #51/#60/#64 remain UNKNOWN. Human acceptance #50, physical
Android/manual screen reader, real accounts/invitations, NOVA contact, staging,
off-site recovery policy and production remain HOLD. Draft only; no merge/deploy.
