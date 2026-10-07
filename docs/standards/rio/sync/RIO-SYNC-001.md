# RIO-SYNC-001
## Offline, Queueing, Reconnect & Synchronization v0.1

### Status
Draft v0.1

### Last Updated
2026-10-06

## 1. Canonical state machine
`CONNECTED → DISCONNECTED → QUEUED → SYNCHRONIZING → CONNECTED`

Optional error branch:
`SYNCHRONIZING → CONFLICT_REVIEW → CONNECTED`

## 2. Offline guarantees
- Local draft/message queue persists across app restarts.
- Outgoing queued items have stable client-generated ids.
- Sync process is idempotent and resumable.

## 3. Conflict model
Conflicts may occur for:
- edits to same message segment
- participant/role change during offline interval
- policy/version mismatch

Resolution strategy:
1. deterministic merge where safe
2. explicit user/system review where required
3. provenance record for final decision

## 4. Sync contract
Client sends:
- last confirmed server cursor
- pending local operations
- client clock and schema version metadata

Server returns:
- authoritative timeline delta
- applied operation mapping
- rejected operation reasons (policy/validation)

## 5. Data classes
- **Hard state**: participants, roles, policy refs
- **Soft state**: typing indicators, transient UI hints

Soft state is non-blocking and may be dropped.

## 6. Acceptance criteria
- User can send offline message; message appears as queued, then delivered after reconnect.
- If server rejects queued action, reason is visible and traceable.
- No silent data loss during reconnect/sync.
