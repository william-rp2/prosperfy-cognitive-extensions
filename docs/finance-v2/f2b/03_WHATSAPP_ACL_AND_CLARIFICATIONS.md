# F2B — WhatsApp ACL, Clarification Queue and Reply Binding

## Authorized finance actors

Finance access is owner-only.

Authorization is **pre-LLM**, **deterministic**, and **fail-closed**.

Implementation: `core/cognitive/cognitive/policy/finance_acl.py`

Wiring: `PolicyEngine(finance_acl=FinanceAcl())` in `core/cognitive/cognitive/gateway/app.py` — always injected, no toggle.

---

## Frozen contract (Decisão A — do not reopen)

| Caller | ACL behavior |
|---|---|
| `NON_FINANCE` capabilities | Pre-F2B behavior preserved — FinanceAcl not evaluated |
| `finance.*` with valid ACL context | Evaluate FinanceAcl |
| `finance.*` without valid ACL/context | **DENY** |
| Unknown context kind | **DENY** |

Deny message (fixed pt-BR, no leak):

```text
Acesso financeiro não autorizado para este contato/conversa.
```

Internal deny reasons (never exposed to user): `no_channel_context`, `no_transport_principal`, `unknown_actor`, `third_party_actor`, `chat_not_allowlisted`, `acl_not_configured`, `internal_principal_not_trusted`, `unknown_context_kind`.

---

## Configuration (env — names only)

| Variable | Purpose |
|---|---|
| `FINANCE_OWNER_ACTOR_IDS` | Canonical owner actor IDs (CSV) |
| `FINANCE_GROUP_CHAT_IDS` | Authorized WhatsApp group chat IDs |
| `FINANCE_OWNER_DIRECT_CHAT_IDS` | Authorized owner DM chat IDs |
| `FINANCE_ACTOR_BINDINGS` | `transport_principal=actor_id,...` mapping |

**Empty config → everything DENY** (`acl_not_configured`).

Logs use SHA256 fingerprints — never raw JIDs/chat IDs.

---

## WhatsApp context (`FinanceContextKind.WHATSAPP`)

Evaluation order:

1. ACL configured (owners + at least one chat allowlist)
2. `channel` present
3. `transport_principal` present
4. Binding → canonical actor via `FinanceActorDirectory`
5. Actor ∈ `FINANCE_OWNER_ACTOR_IDS`
6. Group: `chat_id` ∈ `FINANCE_GROUP_CHAT_IDS` → ALLOW `owner_in_finance_group`
7. DM: `chat_id` ∈ `FINANCE_OWNER_DIRECT_CHAT_IDS` → ALLOW `owner_in_finance_dm`
8. Else → DENY

Third-party group participant → DENY before LLM sees any finance payload.

---

## INTERNAL context (`FinanceContextKind.INTERNAL`) — Decisão B

**`kind=INTERNAL` is NOT proof of trust.**

Trusted internal access requires:

- Explicit `FinanceContextKind.INTERNAL` classification
- **`credential_ref` present** — produced by authenticated boundary (Bearer → IdentityResolver)
- Actor resolved via binding or `ctx.actor_id`
- Actor ∈ `FINANCE_OWNER_ACTOR_IDS`
- ALLOW reason: `trusted_internal_principal`

**No HTTP caller may self-promote to INTERNAL.**

INTERNAL does **not** require `chat_id` (unlike WhatsApp). Requiring synthetic chat_id would be a bypass vector.

Missing `credential_ref` → DENY `internal_principal_not_trusted`.

Tests: `core/cognitive/tests/security/test_finance_acl.py` (INTERNAL section)

---

## Finance group

Proactive finance messages go only to the designated finance group (`FINANCE_GROUP_CHAT_IDS`).

Group ID is configuration, not prompt text.

---

## Clarification entity

Persistent identity with one-open-per-transaction/question-type invariant.

Minimum concepts:

```text
clarification_id
transaction_id
question_type
status
priority
created_at
first_delivered_at
last_delivered_at
resolved_at
resolved_by_actor_id
resolution_payload
delivery_message_id
delivery_chat_id
reply_message_id
```

Delivery tracking: migration `012_clarification_delivery.sql`

---

## Question types

```text
CATEGORY
ECONOMIC_OWNER
RESPONSIBLE
REIMBURSEMENT
CURRENCY
AMOUNT_CORRECTION
COMPETENCE_MONTH
STATEMENT_CYCLE
MERCHANT
OTHER
```

---

## Queue policy

### Historical/onboarding

- suppress proactive one-by-one messaging;
- expose dynamic count;
- month/account/card filtering;
- batch export/import;
- owner explicitly chooses what to process.

### Ongoing/new transactions

- prioritize recent ambiguous transactions;
- no duplicate open clarification;
- no re-ask on every sync.

---

## Reply binding

Best path:

```text
outbound question → delivery_message_id + clarification_id
→ owner quotes/replies → quoted message ID
→ exact clarification resolved
```

Works hours/days later. LLM memory is irrelevant.

Loose reply: strong confidence required; never resolve random transaction.

---

## Spreadsheet workflow

```text
filter pending → export → owner edits → dry-run import → apply
```

Import: validate IDs, idempotent, row-level errors, no silent overwrite of newer corrections.

---

## Anti-spam acceptance

```text
SYNC x 10 → OPEN_QUESTION_COUNT remains 1
OUTBOUND_QUESTION_COUNT does not grow unless delivery recovery policy requires
```

---

## Tests

- `core/cognitive/tests/security/test_finance_acl.py`
- `core/cognitive/tests/security/test_finance_acl_wiring.py`
- `hermes/capability-intelligence/tests/test_finance_reply_binding.py`
