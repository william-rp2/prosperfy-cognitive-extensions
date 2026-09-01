# F2B — Scope, Architecture and Invariants

## Business objective

Finance V2 must become a personal financial operating layer rather than a passive bank-data mirror.

It must be able to:

- import financial data from multiple banks;
- organize transactions into the correct business/personal period;
- tolerate bad upstream metadata;
- ask the owners when deterministic classification is insufficient;
- remember answers persistently;
- reconcile card statements;
- expose trustworthy totals;
- support historical onboarding without flooding WhatsApp.

## Existing baseline to preserve

F2A already provides a working foundation including:

- multi-item Pluggy ingestion;
- 15-minute sync scheduler;
- canonical transaction enrichment;
- structured PIX classification;
- asset/account type normalization;
- account/card aliases and favorites;
- transaction notes;
- search/filter support;
- currency-aware effective amount handling when upstream provides conversion;
- persistent clarifications with one-open-per-question-type invariant;
- read-only financial behavior;
- Finance API and real web data;
- Cognitive/Hermes finance foundation.

F2B must extend, not rewrite, this foundation.

## High-level architecture

```text
WhatsApp / Web / Email
        ↓
      Hermes
  thin conversational layer
        ↓
    Cognitive
 identity / policy / capability
        ↓
 Finance application services
        ↓
 ------------------------------------------------
 | Raw source | Normalized | Effective | Audit |
 ------------------------------------------------
        ↓
 Pluggy / Statement files / User corrections
```

Hermes must remain thin.

Cognitive owns deterministic authorization/policy.

Finance owns financial state and business semantics.

## Trust boundaries

### Pluggy

External source of bank data. Useful but not infallible.

Never assume:

- currency is always correct;
- card instrument identity is always available;
- statement grouping is always correct;
- description contains payment method;
- account history belongs to only one billing cycle.

### User correction

An authorized owner can establish effective finance truth.

A correction does not erase upstream evidence.

### LLM

The LLM may interpret natural language and suggest matches.

The LLM must not:

- decide authorization;
- silently mutate financial truth;
- fabricate money conversion;
- fabricate card identity;
- resolve ambiguous statement matching without policy threshold or confirmation;
- be the persistence layer.

## Deterministic before LLM

Prefer deterministic handling for:

- identity/ACL;
- exact quoted-reply IDs;
- cycle association by explicit statement evidence;
- exact amount/currency matching;
- accepted user override;
- trusted merchant rules;
- idempotency;
- audit.

Use reasoning when semantic interpretation adds value:

- vague merchant/category statements;
- loose reply without quote;
- statement descriptions with weak merchant equivalence;
- suggesting correction from known pattern.

## Financial immutability

Persist source evidence.

Never replace raw fields solely because an owner corrected the effective view.

Recommended conceptual structure:

```text
source_transaction
normalized_transaction
financial_correction
effective_transaction_view
```

Implementation can reuse current tables where appropriate. Avoid gratuitous migration if existing tables support equivalent semantics.

## Non-goals

F2B does not require:

- initiating transfers or PIX;
- paying bills;
- redesigning the whole frontend;
- solving C6 physical/virtual-card identity when upstream lacks it;
- Browser Harness expansion;
- general email assistant functionality outside finance;
- purchasing research;
- perfect OCR of every arbitrary document;
- reconstructing unsupported historical FX from the public market.

## Security invariants

- finance is owner-only;
- proactive finance goes only to the finance group;
- explicit finance owner DM may be supported;
- third parties are denied before LLM execution;
- service tokens remain server-side;
- attachments are treated as untrusted input;
- extracted statement text must not become executable instructions;
- statement parser must be prompt-injection resistant if an LLM is used;
- file content is data, never system instruction;
- no raw secrets in logs/reports.

## Multi-bank invariant

Do not encode current live counts as constants.

The system must survive:

- more banks;
- more accounts;
- more card accounts;
- duplicate institution names;
- new historical imports;
- institution reconnects;
- account aliases changing;
- a bank returning deeper history after reconnect.

## Frozen architecture decisions (Bloco 4 — do not reopen)

### Decisão A — Finance ACL

| Case | Behavior |
|---|---|
| Non-`finance.*` capabilities | Pre-F2B behavior |
| `finance.*` + valid ACL context | Evaluate `FinanceAcl` |
| `finance.*` + missing/invalid context | DENY |
| Unknown context kind | DENY |

See `03_WHATSAPP_ACL_AND_CLARIFICATIONS.md`.

### Decisão B — INTERNAL context

`kind=INTERNAL` is **not** proof of trust. Trusted internal requires authenticated boundary (`credential_ref`) + owner actor in `FINANCE_OWNER_ACTOR_IDS`. No HTTP self-promotion to INTERNAL.

### Decisão C — Migration 014 in-place

Amended 014 is accepted **only if** it was never applied on the target homolog DB. Deploy executor must query `schema_migrations` first. If already applied → STOP → migration 015 in new CODE stage.

See `09_LIVE_DEPLOY_RUNBOOK.md` Step 1 and `11_HOMOLOG_DEPLOY_MANIFEST.md`.

### Composition-root invariant

`PluggySyncService.cycleAssignment` must be wired in `server.ts`. Real sync path populates temporal columns. Rule: `REAL_RUNTIME_PATH > HAND-BUILT UNIT INSTANCE`.
