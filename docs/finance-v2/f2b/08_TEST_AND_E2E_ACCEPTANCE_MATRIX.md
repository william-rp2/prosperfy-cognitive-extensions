# F2B — Test and E2E Acceptance Matrix

## Principle

Unit tests are necessary but insufficient.

F2B requires end-to-end evidence across persistent state and actual routing.

## Baseline regression

Before/after:

- API suite all pass (expected **299/299** on F2B head);
- Web suite all pass (expected **48/48**);
- Cognitive Python suite (expected **658 pass / 103 skip / 0 fail**);
- Hermes relevant tests pass;
- `tsc` pass;
- no new secret/log violations.

## Adapter ↔ Finance API route contract

Two layers prove Cognitive adapter routes match the booted Finance app:

### 1. Registry ↔ adapter map (Python)

`core/cognitive/tests/unit/test_finance_api_route_selection.py`

- Every `finance.*` capability in YAML has a route in `_ROUTES` / `_MODE_ROUTES`
- Every adapter route belongs to a registered capability
- `mode` enum values match YAML `input_schema` — no free-text routing
- Unknown mode / unmapped capability → fail-closed

### 2. Booted Fastify app (TypeScript)

`apps/financeiro-pessoal-api/src/finance/e2eAcceptanceResilience.test.ts`

- Parses `_ROUTES` and `_MODE_ROUTES` from `client.py`
- **Under-parse guard:** all `(METHOD, path)` tuples in file must be captured by parser blocks
- Translates `{param}` → `:param` and asserts `app.hasRoute()` for each

**Note:** PDF route `/api/finance/statements/import/pdf` is **not** in Cognitive adapter — by design. Cognitive uses JSON import only.

## PDF upload tests

`apps/financeiro-pessoal-api/src/finance/e2eStatementPdf.test.ts`

- multipart upload
- magic-byte validation
- text extraction → `importStatement`
- oversize / non-PDF / no-text-layer errors

## Sync composition-root test

`apps/financeiro-pessoal-api/src/finance/e2eAcceptance.test.ts`

- `POST /api/finance/sync` via real app proves `cycleAssignment` wired
- temporal columns populated after sync

## E2E 1 — New ambiguous transaction

```text
new Pluggy tx
→ sync
→ deterministic normalization insufficient
→ exactly one clarification created
→ one outbound finance-group question
→ repeated sync
→ no duplicate clarification
→ no duplicate outbound question
```

## E2E 2 — Quoted reply after delay

```text
question sent
→ persist delivery message id
→ simulate late quoted owner reply
→ exact clarification resolved
→ correction/category saved
→ next sync
→ remains resolved
```

## E2E 3 — Third party deny

Unauthorized group participant asks finance question.

Expected:

```text
DENY
no finance data returned
no LLM access to financial payload
no mutation
```

## E2E 4 — Explicit owner DM

Authorized owner asks an explicit finance question in DM.

Expected ALLOW under policy.

## E2E 5 — Historical backlog suppression

With large historical backlog:

```text
sync/restart/reprocess
→ zero mass proactive flood
```

Owner asks count → dynamic count returned.

Owner asks August → correct period filter.

## E2E 6 — Spreadsheet export/import

```text
filter August
→ export
→ modify 3 rows
→ dry-run import
→ apply
→ 3 accepted
→ reimport same file
→ 0 duplicate mutations
```

Test stale-conflict row.

## E2E 7 — Currency correction

Raw:

```text
28.19 BRL
```

Owner:

> Essa compra foi US$ 5; os R$ 28,19 são o valor da conta.

Expected:

- raw unchanged;
- effective USD 5;
- account amount BRL 28.19;
- aggregate uses 28.19 BRL;
- audit identifies owner correction;
- sync/reprocess does not erase it.

## E2E 8 — Learned merchant rule

Owner creates a scoped suggestion rule.

Next matching transaction:

- rule match visible;
- suggestion generated;
- no unsafe auto-override.

Promote to trusted only via explicit owner action.

Conflict test required.

## E2E 9 — Competence correction

Purchase July, owner says:

> Essa compra entra em agosto.

Expected:

```text
purchase_month=July unchanged
competence_month=August
August competence aggregate includes it
```

## E2E 10 — Two statement cycles in one Pluggy history

Create fixture where one credit account returns July + August transactions together.

Expected:

- not all assigned to one cycle;
- imported statement evidence splits correctly;
- cycle aggregates correct.

## E2E 11 — Closed statement PDF

Import fixture statement via **`POST /api/finance/statements/import/pdf`**.

Expected:

```text
statement parsed (PDF_UPLOAD source)
cycle draft created
exact matches linked
unmatched listed
ambiguous not auto-resolved
CONFLICT never auto-resolved
AMOUNT_MISMATCH not counted as confirmed match
total discrepancy reported when applicable
```

## E2E 11b — Structured JSON import (Cognitive path)

`POST /api/finance/statements/import` with `rawText` or `lines`.

Same downstream reconcile semantics as PDF.

## E2E 12 — Reconciliation close

Exact statement + transactions.

Expected:

```text
RECONCILED
statement total == effective reconciled total
```

Then add late transaction to closed cycle.

Expected:

- cycle flagged dirty/discrepant;
- no silent rewrite.

## E2E 13 — Duplicate statement

Import same statement twice.

Expected idempotency/no duplicate cycle lines.

## E2E 14 — IOF explicit

Statement/transaction explicitly identifies IOF.

Expected IOF.

No explicit signal + close international purchase:

Expected not auto-IOF solely by heuristic.

## E2E 15 — New bank onboarding

Add synthetic new item/account with history.

Expected:

- historical records imported;
- no WhatsApp flood;
- backlog count increases;
- can filter only that bank/month;
- ongoing cutover works.

## E2E 16 — C6 consolidated card

Current-style fixture with one account and same card metadata.

Expected:

- one upstream card account;
- no fabricated extra cards;
- owner transaction responsibility can still be assigned manually.

## E2E 17 — Failure recovery

Inject WhatsApp outbound failure.

Retry must not duplicate state.

## E2E 18 — LLM unavailable

Deterministic paths still preserve data.

No ambiguous correction is silently applied.

## E2E 19 — Attachment prompt injection

Statement contains malicious instruction text.

Expected:

- treated as statement data;
- no instruction execution;
- no payment action;
- parser only returns allowed schema.

## E2E 20 — Production safety

Prove:

```text
PRODUCTION_TOUCHED=NO
PAYMENT_CAPABILITY_PRESENT=NO
SECRETS_IN_BROWSER=NO
```

## Live acceptance sample

Homolog live must demonstrate at least:

- real finance owner ACL;
- finance group routing;
- quoted reply persistence;
- one real or safely synthetic correction;
- one historical period query;
- one statement reconciliation path using safe statement fixture/owner-provided homolog artifact;
- no historical spam.
