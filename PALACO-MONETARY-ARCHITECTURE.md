# PALACO Monetary Architecture v0.1.0

**Status:** PROPOSED / ARCHITECTURE FREEZE CANDIDATE  
**Scope:** PALACO, PALACO-INDUSTRIE, PALACO-Citadel, PALACO.NL/COM, ELIXER and future PALACO financial infrastructure.

## 1. Purpose

PALACO supports ordinary international payment methods and prepares a constitutional monetary layer alongside them. The initial PALACO-native instruments are:

- **M∆5TER COIN (M.C.)** — PALACO's native utility/loyalty currency concept.
- **MISSION COIN 7 (M.C.7)** — a separate PALACO monetary/mission instrument whose exact economic and legal classification is to be determined before issuance.
- **WORLD currencies** — optional currencies created by an eligible Citadel/WORLD under a common generation and governance framework.

External payment rails are treated as interoperability layers, not as substitutes for constitutional authorization: cards, IBAN/bank transfers, iDEAL or successor/analogous payment rails, international payment methods, and supported crypto assets may be exposed through PALACO where legally and technically supported.

## 2. Constitutional rule

**NO MONETARY ACTION BEFORE CONTEXT.**  
**NO MONETARY AUTHORITY WITHOUT PROVENANCE.**  
**NO FINANCIAL DECISION WITHOUT EVIDENCE.**  
**NO EXECUTION WITHOUT AUTHORIZATION.**

ACCESS ≠ AUTHORIZATION.

Every monetary operation MUST have an identity, instrument, scope, authorization, provenance, timestamp, status and traceability record.

## 3. Monetary layers

### Layer A — External payment rails
VISA/card rails, IBAN/bank transfer, iDEAL or equivalent payment methods, and other supported international rails.

### Layer B — External crypto interoperability
Supported external crypto assets and networks, subject to jurisdiction, chain support, custody and compliance constraints.

### Layer C — PALACO-native monetary instruments
M∆5TER COIN (M.C.) and MISSION COIN 7 (M.C.7).

### Layer D — Citadel/WORLD instruments
A qualifying Citadel/WORLD may define a native token/currency through the PALACO Crypto Generation Engine. Creation is not the same as authorization to publicly issue, custody, exchange, market or provide payment services.

## 4. M∆5TER COIN (M.C.)

M.C. is the PALACO-native monetary/utility instrument concept.

Initial intended utility:
- PALACO merchandise and participating products;
- official PALACO ELIXERS;
- event distributions/rewards;
- loyalty programmes;
- approved commercial Hotspots;
- other constitutionally authorized PALACO services.

The loyalty engine may calculate rewards from duration and configured rules, including a maximum ceiling. Reward parameters must be explicit, versioned and auditable.

M.C. must not be represented as guaranteed cash value, deposit money, investment return or redeemable bank money unless a separately approved legal and financial structure permits that representation.

## 5. MISSION COIN 7 (M.C.7)

M.C.7 is a separate instrument. Its monetary policy, supply model, utility, transferability, redemption, market access and legal classification remain configuration-controlled until formally approved.

No assumption is made that M.C.7 has the same rights, value, backing or redemption conditions as M.C.

## 6. Wallet

Each eligible Citadel ID may expose a personal PALACO Wallet.

Wallet profile contains four owner-selectable spending destinations:

1. **Filantroop**
2. **Mescenicas**
3. **Misantroop**
4. **Blanco** — owner-defined destination, e.g. an IBAN or other permitted destination identifier.

The owner may optionally associate the wallet with a phone number or e-mail address. Financial linkage is optional where the relevant function permits it.

The wallet must separate:
- identity;
- balance;
- spending policy;
- destination;
- authorization;
- contact/recovery information;
- financial account data.

## 7. BOTERHAM

**BOTERHAM** is the PALACO administrative programme for monetary, commercial and operational administration.

BOTERHAM is responsible for:
- ledger administration;
- wallet/account references;
- transaction lifecycle;
- merchant/Hotspot administration;
- loyalty calculation;
- issuance/reward records;
- reconciliation;
- invoices/orders;
- fees and pricing;
- audit trails;
- reporting/export;
- permissions and approvals;
- compliance evidence;
- dispute/refund state;
- treasury and reserve records where applicable.

BOTERHAM is an administrative system, not automatically a bank.

## 8. HOTSPOT

The **HOTSPOT Module** allows approved commercial participants to host PALACO monetary functionality.

A Hotspot may, when authorized:
- accept M.C./M.C.7;
- distribute approved PALACO rewards;
- present payment/QR/NFC/Bluetooth interaction;
- participate in campaigns;
- expose an approved PALACO wallet endpoint.

Bluetooth may support proximity discovery and later a PALACO-approved "Goldthooth" push channel. Proximity MUST NOT itself grant authority. A Hotspot receives a scoped authorization credential and can be suspended/revoked.

## 9. PALACO BANK and PALACO EXCHANGE

The architecture reserves two future institutional domains:

- **PALACO BANK** — banking/payment infrastructure, only where legally authorized and appropriately licensed/partnered.
- **PALACO EXCHANGE** — exchange/trading infrastructure, only where the required regulatory permissions and controls exist.

These names are architectural reservations, not a claim that PALACO currently operates a licensed bank, exchange or CASP.

## 10. I.W.K. / I.E.O.

Canonical PALACO terminology:

**I.W.K. — Interstalair Wissel Kantoor**  
**I.E.O. — Interstalair Exchange Office**

The I.E.O. has a dedicated PALACO symbol/icon (provided by the Architect) and acts as the interstellar exchange/registry concept for PALACO monetary instruments and WORLD currencies.

The registry must distinguish:
- currency identity;
- issuer/creator;
- Citadel/WORLD scope;
- jurisdiction;
- status;
- supply;
- policy;
- permitted uses;
- exchange rules;
- provenance;
- authorization;
- suspension/revocation.

## 11. Crypto Generation Engine

The Crypto Generation Engine provides a low-threshold creation workflow:

IDENTITY → WORLD/CITADEL → CURRENCY DEFINITION → TOKEN POLICY → PROVENANCE → CONSTITUTIONAL REVIEW → AUTHORIZATION → DEPLOYMENT → REGISTRY → OPERATION → TRACEABILITY.

Generation alone creates a technical artifact. Public issuance or financial service operation requires the appropriate authorization gates.

## 12. Legal/compliance gate

For EU/NL deployment, the system must classify each instrument and each service before activation. MiCAR regulates crypto-assets and crypto-asset services; CASP activities can include custody, trading-platform operation, exchange, execution, placement, order transmission, advice, portfolio management and transfer services. Where applicable, authorization/notification and additional payment-service requirements must be checked.

Therefore every instrument gets a **COMPLIANCE_STATUS**:
DRAFT | CLASSIFICATION_REQUIRED | REVIEW | AUTHORIZED | ACTIVE | SUSPENDED | REVOKED | ARCHIVED.

## 13. Free-product principle

PALACO remains designed as a free product at the core. Optional additions may be priced by PALACO HOOFDKANTOOR. Product pricing is separate from monetary issuance policy.

Third parties may create PALACO-compatible commercial supply where constitutionally and commercially permitted. Revenue-sharing, royalties, commissions and marketplace rules are explicit configuration, never hidden.

## 14. Core data objects

Currency:
currency_id, symbol, name, issuer_id, scope, chain/network, supply_policy, decimals, utility, redemption_policy, compliance_status, provenance, created_at, version.

Wallet:
wallet_id, owner_citadel_id, identity_ref, currency_balances, spending_policy, destination_profile, contact_ref, authorization_state, status.

Transaction:
transaction_id, currency_id, from_wallet, to_wallet, amount, purpose, authorization_ref, provenance_ref, timestamp, status, reversal_ref.

Hotspot:
hotspot_id, operator_id, location_scope, supported_instruments, authorization_ref, device_binding, status, audit_ref.

## 15. Non-negotiable safety properties

- No hidden monetary issuance.
- No balance mutation without a traceable transaction.
- No transaction without authorization.
- No continued operation after revocation.
- Expiration is distinct from revocation.
- Supply changes are policy-governed and auditable.
- Signature verifies authenticity/integrity; provenance proves lineage; neither grants authority.
- Administrative access never implies monetary authority.
- Monetary records are append-only/auditable wherever technically appropriate.
