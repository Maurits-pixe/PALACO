# RIO-TRANSPORT-001
## Realtime Delivery & Session Transport v0.1

### Status
Draft v0.1

### Last Updated
2026-10-06

## 1. Goal
Provide low-latency, cross-surface conversation delivery with robust fallback.

## 2. Transport profile
Primary:
- persistent bidirectional channel (e.g., WebSocket)

Fallback:
- resumable polling/SSE where persistent channel is unavailable

Out-of-band:
- push notification for wake-up/re-entry signals

## 3. Delivery semantics
- At-least-once network delivery
- Idempotent client apply (dedupe by message/event id)
- Monotonic cursor progression per conversation stream

## 4. Envelope (transport-level)
```json
{
  "stream": "rio.conversation.rio_conv_...",
  "cursor": 1821,
  "event": {
    "event_id": "rio_evt_...",
    "event_type": "MESSAGE_CREATED",
    "payload": {}
  },
  "sent_at": "ISO-8601"
}
```

## 5. Presence
Presence is advisory, not authoritative:
- `ONLINE`
- `IDLE`
- `OFFLINE`
- `UNKNOWN`

Presence must never be used as sole evidence of message acknowledgment.

## 6. Acknowledgment
Two distinct receipts:
1. **Delivery receipt**: reached target client session
2. **Read receipt**: rendered/seen by participant context

Both are optional by policy and user settings.

## 7. Reliability controls
- heartbeat interval
- reconnect backoff with jitter
- cursor-based replay after reconnect
- server-side replay window

## 8. Acceptance criteria
- If a client reconnects within replay window, missing events are recovered without timeline corruption.
- Duplicate transport frames do not duplicate messages in timeline.
