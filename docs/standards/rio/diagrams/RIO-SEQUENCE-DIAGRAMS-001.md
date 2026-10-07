# RIO-SEQUENCE-DIAGRAMS-001
## Reference Sequence Diagrams v0.2

### Status
Draft v0.2

### Last Updated
2026-10-06

## 1) Discover → Connect (Cross-Surface)

```mermaid
sequenceDiagram
  participant U as User
  participant M as Mobile Client
  participant W as Web Client
  participant R as RIO Platform
  participant C as Conversation Core

  U->>M: Open conversation
  M->>R: Authenticate + subscribe(conversation_id)
  R->>C: Resolve participants/context/state
  C-->>R: Conversation snapshot + cursor
  R-->>M: Connected(snapshot, cursor)

  U->>W: Open same conversation in browser
  W->>R: Authenticate + subscribe(conversation_id)
  R->>C: Fetch delta from latest cursor
  C-->>R: Delta events
  R-->>W: Connected(delta)
```

## 2) Message Send & Realtime Delivery

```mermaid
sequenceDiagram
  participant A as Sender Client
  participant R as RIO Transport
  participant C as Conversation Core
  participant B as Receiver Client

  A->>R: MESSAGE_CREATE(client_msg_id, body)
  R->>C: Validate + append timeline event
  C-->>R: MESSAGE_CREATED(event_id, cursor)
  R-->>A: Ack(delivery accepted, event_id, cursor)
  R-->>B: Push MESSAGE_CREATED(event_id, body, cursor)
  B-->>R: DeliveryReceipt(event_id)
  R-->>A: Delivery update(received by B session)
```

## 3) Offline Queue → Sync

```mermaid
sequenceDiagram
  participant U as User
  participant A as Mobile Client
  participant R as RIO Sync Service
  participant C as Conversation Core

  A--xR: connection lost
  U->>A: Send message while offline
  A->>A: Queue(local_op_id, client_msg_id)

  A->>R: Reconnect + sync(last_server_cursor, pending_ops[])
  R->>C: Apply ops idempotently
  C-->>R: Applied/rejected map + timeline delta
  R-->>A: SyncResult(applied[], rejected[], delta[])
  A->>A: Update UI queued->sent or rejected(reason)
```

## 4) IntentAction Boundary (Message ≠ Action)

```mermaid
sequenceDiagram
  participant U as User
  participant A as Client
  participant R as RIO Platform
  participant P as Policy/TRIAS
  participant X as Execution Service

  U->>A: "Delete ELIXER X"
  A->>R: MESSAGE_CREATE(text)
  R-->>A: Message posted (conversation)

  R->>R: Intent extraction -> IntentAction(PROPOSED)
  R->>P: Evaluate(intent, policy_ref, risk_class)
  P-->>R: Decision: APPROVAL_REQUIRED

  R-->>A: Show action preview + approval request
  U->>A: Approve
  A->>R: INTENT_APPROVE(intent_id)
  R->>P: Final authorization check
  P-->>R: APPROVED
  R->>X: Execute bounded action
  X-->>R: Execution result + evidence ref
  R-->>A: Intent EXECUTED + trace/evidence links
```

## 5) Optional: Conflict Review Branch

```mermaid
sequenceDiagram
  participant A as Client A
  participant B as Client B
  participant R as Sync Service

  A->>R: Sync op(edit message #12)
  B->>R: Sync op(delete message #12)
  R->>R: Detect semantic conflict
  R-->>A: ConflictReview required
  R-->>B: ConflictReview required
  R->>R: Apply policy resolution / user-mediated decision
  R-->>A: Resolution event
  R-->>B: Resolution event
```

## Diagram usage note
These are reference flows. Implementations may vary in protocol detail, but **must preserve constitutional semantics and auditability**.
