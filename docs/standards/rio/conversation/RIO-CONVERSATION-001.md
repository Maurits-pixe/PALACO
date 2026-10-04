# RIO-CONVERSATION-001
## Conversation Object & Lifecycle v0.1

### Status
Draft v0.1

## 1. Canonical object

```json
{
  "conversation_id": "rio_conv_...",
  "version": "1.0",
  "identity_ref": "palaco:identity:...",
  "participants": [],
  "context": {
    "citadel_ref": null,
    "world_ref": null,
    "elixer_ref": null,
    "tags": []
  },
  "state": "ACTIVE",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "provenance": {
    "origin_surface": "mobile|web|elixer",
    "origin_endpoint": "rio://...",
    "trace_ref": "..."
  },
  "policy_refs": [],
  "evidence_refs": []
}
```

## 2. Participant model

```json
{
  "participant_id": "rio_part_...",
  "type": "PERSON|CITADEL|WORLD|ELIXER|SYSTEM",
  "identity_ref": "palaco:identity:...",
  "role": "OWNER|MEMBER|GUEST|OBSERVER|SYSTEM",
  "join_state": "INVITED|JOINED|LEFT|REMOVED",
  "joined_at": "ISO-8601",
  "left_at": null
}
```

## 3. Conversation states
- `PENDING` (created but not fully established)
- `ACTIVE`
- `PAUSED`
- `ARCHIVED`
- `REVOKED` (cannot continue as active channel)
- `DELETED_VIEW` (hidden in UI, not necessarily provenance-erased)

### State rule
`REVOKED` and `ARCHIVED` must remain historically reconstructable according to policy.

## 4. Cross-surface invariants
1. Same `conversation_id` across all participating surfaces.
2. Same timeline semantics independent of renderer.
3. Surface-specific UI can differ, semantic state cannot.

## 5. Event timeline requirements
Every timeline event must include:
- `event_id`
- `conversation_id`
- `event_type`
- `actor_ref`
- `timestamp`
- `causality_ref` (optional but recommended)
- `provenance_ref`

## 6. Acceptance criteria
- A user can continue one conversation from mobile to web without creating a second conversation.
- Participant list and roles remain consistent across surfaces.
- Archived conversation remains queryable in history with policy-allowed detail.
