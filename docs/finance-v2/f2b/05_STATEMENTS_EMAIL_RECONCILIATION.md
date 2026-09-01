# F2B — Closed Statements, PDF Upload and Reconciliation

## Goal

A closed credit-card statement is strong evidence for cycle assignment, closed total, due date, currency/account amount, missing/duplicate provider transactions, and discrepancy detection.

Finance accepts statements via **structured JSON import**, **PDF multipart upload**, and (future) email/Hermes attachment paths. Reconciliation compares statement lines against Pluggy transactions without overwriting raw provider data.

---

## Implementation status (Bloco 4)

| Capability | Status |
|---|---|
| `POST /api/finance/statements/import` (JSON) | **IMPLEMENTED** |
| `POST /api/finance/statements/import/pdf` (multipart) | **IMPLEMENTED** |
| `POST /api/finance/statements/:id/reconcile` | **IMPLEMENTED** |
| `GET /api/finance/cycles` | **IMPLEMENTED** |
| Cognitive `finance.statement.import` | **IMPLEMENTED** (JSON route only) |
| Cognitive PDF multipart | **NOT EXPOSED** — PDF is Finance API direct / Web proxy |
| Email automation | **DEFERRED** — see § Email |

---

## PDF upload — as implemented

**Route:** `POST /api/finance/statements/import/pdf`

**Implementation:** `apps/financeiro-pessoal-api/src/routes/financeStatementRoutes.ts`

### Transport

- `@fastify/multipart` in encapsulated sub-scope
- Single file: `request.file()`
- Limits: `fileSize: 10 MiB`, `files: 1`

### Validation

- Bearer auth (`FINANCE_API_TOKEN`) — fail-closed
- Magic bytes: `%PDF-` (`pdfTextExtractor.ts`)
- Oversized/truncated buffer → `413 pdf_too_large`
- Not PDF → `415 not_a_pdf`
- No extractable text layer → `422 pdf_without_text_layer`
- Unreadable PDF → `422 pdf_unreadable`

### Extraction

- **In-memory only** — no disk, no network during extraction
- `pdfjs-dist/legacy/build/pdf.mjs` via dynamic import
- Text grouped by Y coordinate; empty result → `pdf_without_text_layer`
- **No OCR** in current implementation

### Multipart fields

| Field | Required | Notes |
|---|---|---|
| `financialAccountId` | YES | Note: JSON route uses `accountId` |
| `competenceMonth` | YES | `YYYY-MM` |
| `statementTotalCents` | YES | integer cents string, strict regex |
| `statementCurrency` | optional | |
| `institutionHint`, `cardLast4` | optional | |
| `periodStart`, `periodEnd`, `closingDate`, `dueDate` | optional | ISO dates |
| file | YES | PDF bytes |

Filename sanitized (regex + max 120 chars).

### Flow

```text
multipart PDF
  → extractPdfText(bytes)           [pdfTextExtractor.ts]
  → reconciliation.importStatement({
       source: 'PDF_UPLOAD',
       rawText: extracted.text,
       ...
     })                             [reconciliationService.ts]
  → parseStatement → content hash idempotency
  → upsert cycle (CLOSED_SOURCE, reconciliationStatus: PENDING)
  → upsert import + lines
```

Statement content is **untrusted data**. Extracted text is never interpreted as instructions. Prompt injection in PDF text is inert — parser returns structured fields only.

### Tests

- `apps/financeiro-pessoal-api/src/finance/e2eStatementPdf.test.ts`
- Fixtures: `apps/financeiro-pessoal-api/src/finance/__fixtures__/makeStatementPdf.js`

---

## Structured JSON import

**Route:** `POST /api/finance/statements/import`

Same downstream `importStatement()` as PDF after text is available.

Sources in DB (`014_statement_imports.sql`):

```text
HERMES_ATTACHMENT
FINANCE_EMAIL_ATTACHMENT
MANUAL_UPLOAD
PLUGGY_BILL
PDF_UPLOAD
```

Cognitive adapter `finance.statement.import` calls the JSON route only.

---

## Email boundary — DEFERRED

```text
EMAIL_STATEMENT_PATH=DEFERRED
```

Upload PDF via Finance API / Web and structured JSON via Cognitive/Hermes are **F2B delivered**.

Automatic email ingestion (list candidates, fetch attachment, recurring monitoring) is **future debt**, not a Bloco 4 blocker.

Narrow capabilities when implemented:

```text
finance.email.list_candidates
finance.email.read_statement
finance.email.fetch_attachment
```

Do not expose general mailbox access to Finance LLM context.

---

## Line-item model

Statement lines live in separate tables — never replace Pluggy transaction rows.

Tables (migration 014):

- `financial_statement_imports`
- `financial_statement_lines`
- `financial_statement_reconciliations`
- `financial_statement_discrepancies`

Raw Pluggy `financial_transactions.raw_data` is never written by this feature.

---

## Reconciliation semantics — as implemented

**Service:** `reconciliationService.ts` + `statementMatchingService.ts`

### Per-line match status

| Status | Meaning |
|---|---|
| `EXACT` | amount + description + date exact (within policy) |
| `HIGH` | strong match, not exact |
| `AMBIGUOUS` | multiple plausible candidates or score tie |
| `CONFLICT` | uniqueness violation — 2+ lines claim same transaction |
| `STATEMENT_ONLY` | line has no app transaction match |
| `APP_ONLY` | app transaction has no statement line match |
| `AMOUNT_MISMATCH` | identity/date/context plausible, **value diverges** |

### Discrepancy kinds (persisted)

`TOTAL_MISMATCH`, `STATEMENT_ONLY`, `APP_ONLY`, `AMOUNT_MISMATCH`, `AMBIGUOUS`, `CONFLICT`

### Import status

`PARSED` → `RECONCILING` → `RECONCILED` | `DISCREPANT`

### Cycle status / reconciliation_status

Cycle: `OPEN`, `CLOSED_SOURCE`, `RECONCILING`, `RECONCILED`, `DISCREPANT`, `ARCHIVED`

Cycle reconciliation_status: `PENDING`, `IN_PROGRESS`, `MATCHED`, `DRIFT`, `DISCREPANT`

Post-reconcile aggregate: `clean` requires zero open discrepancies + statement total matches.

### Matching signals (deterministic)

Matching does **not** use magnitude alone.

| Signal | Effect |
|---|---|
| Direction gate | line PAYMENT/REFUND vs CHARGE; tx sign vs type |
| Currency | mismatch → candidate discarded |
| Date tolerance | default ±3 days |
| Amount (magnitude) | default tolerance 0 cents |
| Description overlap | Jaccard on normalized tokens |
| AMOUNT_MISMATCH threshold | overlap ≥ 0.6 or equal description |

### CONFLICT vs AMOUNT_MISMATCH

**CONFLICT** — dispute / uniqueness violation between candidates. **Never auto-resolved.**

**AMOUNT_MISMATCH** — plausible same transaction but value differs. **Not** classified as simple `STATEMENT_ONLY`. **Never** counts as confirmed match in reconcile totals.

Greedy claim by score; claimed transactions excluded from later lines.

### Reconcile pipeline

1. Set import `RECONCILING`, cycle `IN_PROGRESS`
2. Clear prior reconciliations + resolve open discrepancies
3. `matchStatementLines`
4. `AMOUNT_MISMATCH` excluded from confirmed match count
5. `APP_ONLY` for unmatched transactions
6. `TOTAL_MISMATCH` if parsed total ≠ reconciled total
7. Final cycle/import status

---

## Cycle close policy

Cycle becomes `RECONCILED` only when policy allows (no unresolved CONFLICT/AMBIGUOUS material items, total within tolerance, etc.).

Otherwise `DISCREPANT` with explicit difference report.

---

## Statement via WhatsApp

Requires Hermes attachment transport + authorized ACL context.

Last hop (WhatsApp bridge / Hermes gateway restart) is **not authorized** in current deploy stage — see runbook.

---

## IOF in statements

Explicit IOF in statement line → may classify as fee/IOF when evidence is explicit.

No explicit signal → do not auto-label IOF from proximity to international purchase alone.

---

## Idempotency

Re-importing same statement content (same account + content hash) updates in place — no duplicate cycles/lines.

---

## Owner query example

> Confere minha fatura do C6 de agosto.

Report returns: statement total, reconciled total, matched count, statement-only, app-only, difference, ambiguities.
