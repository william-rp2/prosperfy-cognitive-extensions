# F2B — Bug Sweep and Known Limitations

## Bug-sweep philosophy

F2B may fix real Finance defects discovered during implementation/E2E.

It must not become an unlimited cleanup project.

---

## Must fix if discovered

- financial amount/currency corruption under our control;
- wrong aggregate basis;
- incorrect cycle assignment;
- user correction lost after sync/reprocess;
- duplicate clarifications;
- quoted reply resolving wrong transaction;
- authorization bypass;
- third-party finance access;
- raw data overwritten by effective correction;
- duplicate statement import/reconciliation;
- stale batch import overwriting newer corrections;
- merchant rule applied to wrong merchant due unsafe matching;
- new-bank onboarding causing WhatsApp flood;
- deterministic data mismatch between DB/API/Hermes;
- **runtime path different from tested path**;
- regression in PIX/card/refund/alias/notes/filter behavior;
- secret exposure;
- production mutation.

---

## Critical bug fixed — cycleAssignment composition root

**Symptom:** `PluggySyncService` accepts optional `cycleAssignment`. When missing, sync silently skips temporal assignment — `purchase_month`, `competence_month`, `statement_cycle_id` remain null on real sync.

**Root cause:** `server.ts` built `PluggySyncService` without injecting `CycleAssignmentService` even though the dependency existed in the composition root.

**Fix:** `server.ts` now wires:

```typescript
cycleAssignment: cycleAssignmentService,
```

**Regression test:** `POST /api/finance/sync` via booted app (`e2eAcceptance.test.ts`).

**Rule:**

```text
REAL_RUNTIME_PATH > HAND-BUILT UNIT INSTANCE
```

A unit test that constructs its own `PluggySyncService` with mocked dependencies does **not** prove production sync behavior.

---

## Known limitations — accepted scope (not CODE bugs)

### EMAIL_STATEMENT_PATH

```text
EMAIL_STATEMENT_PATH=DEFERRED
```

PDF multipart upload and structured JSON import are delivered. Automatic email ingestion is future work.

### SPLIT_COMPOUND_TRANSACTION

```text
SPLIT_COMPOUND_TRANSACTION=BACKLOG
```

Matcher does not auto-split compound statement lines across multiple Pluggy transactions unless explicitly modeled.

### C6 multiple cards

```text
C6_MULTIPLE_CARDS=UPSTREAM_LIMITATION
```

Current Pluggy item returns one consolidated credit account. Do not fabricate four card entities.

`creditCardMetadata.cardNumber` may appear per transaction but does not distinguish all physical/virtual cards.

### Upstream currency errors (MyPluggy)

Pluggy may report international purchase as BRL in raw.

Policy:

- preserve raw;
- allow owner correction via Correction Layer;
- never claim Pluggy sent data it did not send.

Not fixable by adulterating `raw_data`.

### IOF

- explicit IOF evidence → classify IOF;
- no explicit evidence → do not auto-label from amount/proximity/temporal correlation alone.

Statement reconciliation may provide stronger explicit IOF evidence when present in line text.

### PDF without text layer

```text
OCR=NOT_IMPLEMENTED
```

PDFs without extractable text layer return `422 pdf_without_text_layer`. No OCR fallback in current code.

Vision/LLM semantic extraction from scanned PDFs is **not** implemented.

### Hermes / WhatsApp last hop

Deploy stage blocks `hermes-gateway.service` restart.

WhatsApp E2E cannot be declared PASS without authorized runtime restart evidence.

---

## Current improvements not worth blocking F2B

- broad frontend redesign;
- aesthetic polish;
- Purchase Research;
- general-purpose email intelligence;
- Browser Harness expansion unrelated to statements;
- perfect OCR of every document.

---

## Historical counts

Never assert current transaction/clarification count is permanent. More banks change the dataset.

---

## Bugs from previous reports

Treat old report PASS as evidence, not truth.

If Human/live E2E contradicts a unit test, reproduce the **real code path**.

```text
REAL_RUNTIME_PATH > ISOLATED_FORMATTER_TEST
```

---

## Migration 014 in-place amendment

Accepted **conditionally**: 014 must not have been applied on target homolog before this deploy.

If already applied → deploy blocked → requires migration 015 in new CODE stage.

See `09_LIVE_DEPLOY_RUNBOOK.md` Step 1 and `11_HOMOLOG_DEPLOY_MANIFEST.md` section D.
