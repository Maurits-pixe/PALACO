# RIO-AUTH-BOUNDARY-001
## Communication-Action Separation v0.1

### Status
Draft v0.1

## 1. Canonical law
**COMMUNICATION ≠ AUTHORITY**  
**MESSAGE ≠ ACTION**  
**INTENT REQUIRES POLICY PATH**

## 2. IntentAction model
```json
{
  "intent_id": "rio_intent_...",
  "conversation_id": "rio_conv_...",
  "requested_by": "palaco:identity:...",
  "intent_type": "CREATE|UPDATE|DELETE|GRANT|REVOKE|EXECUTE",
  "target_ref": "palaco:...",
  "intent_payload": {},
  "risk_class": "LOW|MEDIUM|HIGH|CRITICAL",
  "policy_ref": "palaco:policy:...",
  "trias_required": true,
  "state": "PROPOSED|REVIEW|APPROVED|DENIED|EXPIRED|EXECUTED"
}
```

## 3. Mandatory flow
Chat message expressing request  
→ Intent extraction/proposal  
→ Policy/TRIAS evaluation  
→ Explicit authorization decision  
→ Action execution (or denial)  
→ Evidence + traceability record

## 4. UX obligation
RIO must clearly distinguish:
- conversational reply
- policy explanation
- executable action preview
- authorization prompt
- execution result

## 5. Forbidden behaviors
- implicit destructive action from plain text command
- hidden authority escalation
- irreversible action without explicit confirmation path

## 6. Acceptance criteria
- “Delete ELIXER X” in chat creates an intent proposal, not immediate deletion.
- User can inspect what would change before approval.
- Final execution includes policy/evidence references.
