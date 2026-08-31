# OPUS 5 LOOP — FINANCE V2 F2B AUTONOMOUS EXECUTION

## Mission

Implement **Finance V2 F2B completely**, from the accepted F2A baseline through code, migrations, tests, homolog deployment and live technical E2E.

Work autonomously until:

```text
CODE_READY=YES
LIVE_READY=YES
HUMAN_PASS=NO
```

Then STOP and return the final report for owner Human Acceptance.

Do not stop for normal implementation decisions. Inspect the existing codebase, reuse existing patterns, write tests, fix regressions, and continue.

Use subagents aggressively where work can be parallelized safely.

## Repository

```text
REPO=william-rp2/prosperfy-cognitive-extensions
EXPECTED_F2A_SOURCE=f4f491c745c970766274f0f37abfdb3874bc1222
TARGET_BRANCH=dev/finance-v2-f2b
```

## PRE-FLIGHT — mandatory

Before any code:

1. Fetch `origin`.
2. Confirm `master` is canonical and equals the accepted F2A source.
3. Confirm clean worktree.
4. Confirm F2A tests/build baseline.
5. Create or reset only the authorized F2B branch from canonical master.

Required:

```text
MASTER_SHA=
EXPECTED_F2A_SOURCE=f4f491c745c970766274f0f37abfdb3874bc1222
MASTER_EQUALS_ACCEPTED_F2A=YES
WORKTREE_CLEAN=YES
```

If `MASTER_EQUALS_ACCEPTED_F2A=NO`:

```text
STOP
BASELINE_MISMATCH=YES
```

Do not silently merge or rebase unrelated work.

## Read these files first

Read the complete dossier in order:

1. `README.md`
2. `01_SCOPE_AND_ARCHITECTURE.md`
3. `02_DATA_MODEL_AND_CYCLES.md`
4. `03_WHATSAPP_ACL_AND_CLARIFICATIONS.md`
5. `04_CORRECTIONS_AND_LEARNING.md`
6. `05_STATEMENTS_EMAIL_RECONCILIATION.md`
7. `06_ONBOARDING_HISTORICAL_BACKFILL.md`
8. `07_BUG_SWEEP_AND_KNOWN_LIMITATIONS.md`
9. `08_TEST_AND_E2E_ACCEPTANCE_MATRIX.md`
10. `09_LIVE_DEPLOY_RUNBOOK.md`
11. `10_FINAL_REPORT_TEMPLATE.md`

Inspect actual source/runtime before deciding implementation details. Documentation defines **behavior and invariants**, not permission to rewrite working architecture unnecessarily.

## Autonomous checkpoints

Do not ask for approval between checkpoints.

### CP0 — Baseline / architecture inventory

Map the actual code paths for:

- Finance API;
- Finance web;
- Pluggy sync;
- transaction normalization/enrichment;
- clarifications;
- Cognitive finance capabilities;
- Hermes finance routing;
- WhatsApp inbound/outbound bridge;
- identity/auth;
- current DB/migrations;
- notes/preferences;
- current file/attachment capabilities;
- current email capabilities;
- current deployment services.

Output an internal implementation plan and continue.

### CP1 — Domain + migrations

Implement the minimum durable domain for:

- transaction month/competence;
- statement cycles;
- transaction-to-cycle assignment;
- statement imports;
- reconciliation;
- corrections;
- learned rules;
- clarification deliveries/replies;
- onboarding/batch resolution.

Migrations must be incremental and rollback-safe where practical.

### CP2 — Core services

Implement deterministic services before LLM-facing integration.

The DB/service layer owns state. LLM never owns persistent resolution state.

### CP3 — ACL / Cognitive / Hermes

Implement deterministic owner authorization and narrow finance capabilities.

Authorization must happen before LLM interpretation.

### CP4 — Clarification engine

Implement:

- priority queue;
- one-open-question invariant;
- proactive new-item flow;
- quoted reply binding;
- late replies;
- cancellation;
- conflict handling;
- historical backlog suppression.

### CP5 — Financial correction + learning

Implement raw/effective separation, explicit corrections, merchant rules and auditable application.

### CP6 — Month / card-cycle / statement reconciliation

Implement first-class cycle handling and statement matching.

The system must not assume Pluggy cycle grouping is correct.

### CP7 — Historical onboarding

Implement period filtering and spreadsheet export/import for bulk cleanup.

Historical backlog must not be pushed one-by-one.

### CP8 — Bug/integrity sweep

Fix in-scope bugs discovered by real E2Es. Do not redesign the entire frontend.

### CP9 — Automated E2E

Run the full matrix in `08_TEST_AND_E2E_ACCEPTANCE_MATRIX.md`.

### CP10 — Homolog live E2E

Deploy only to homolog under `09_LIVE_DEPLOY_RUNBOOK.md`.

### CP11 — Final audit

Require:

```text
CODE_READY=YES
LIVE_READY=YES
HUMAN_PASS=NO
```

Then STOP.

Do not merge F2B to master.

# Subagents

Use subagents to reduce overnight wall-clock time.

Recommended decomposition:

```text
SUBAGENT_A_DOMAIN
  DB, migrations, cycles, correction model

SUBAGENT_B_CLARIFICATIONS
  queue, idempotency, reply binding, batch onboarding

SUBAGENT_C_HERMES_ACL
  Cognitive capabilities, owner ACL, WhatsApp routing

SUBAGENT_D_STATEMENTS
  statement ingestion, email/PDF path, reconciliation engine

SUBAGENT_E_TESTING
  fixtures, negative tests, E2E harness, regression matrix

SUBAGENT_F_FRONTEND_MINIMAL
  only required functional UI/API exposure; no redesign
```

Rules for subagents:

- give each agent explicit files/area ownership;
- avoid concurrent edits to the same file;
- each subagent returns tests + changed files + assumptions;
- parent agent integrates and owns final architecture;
- parent agent must review every subagent diff;
- never trust a subagent PASS without running integrated suites;
- no subagent may deploy independently;
- no subagent may touch Production;
- no subagent may change master.

Use sequential integration checkpoints if two subagents need the same core domain files.

# Owner-facing behaviors to support

### Pending count

Owner:

> Quantas pendências financeiras eu tenho?

System:

> Existem N pendências históricas. Posso filtrar por mês, conta ou cartão.

### Historical August batch

Owner:

> Traga as de agosto.

System resolves August by **effective competence/cycle semantics**, not naive import date.

It returns a filtered batch and supports spreadsheet export.

### Currency correction

Owner:

> Essa OpenAI de 20 foi em dólar.

Persist correction without altering raw Pluggy evidence.

### Learned rule

Owner:

> OpenAI normalmente é em dólar.

Persist a merchant rule. Default behavior should be `SUGGEST`, not blind auto-application, unless the owner explicitly promotes it to trusted/automatic behavior.

### Economic ownership

Owner:

> Isso é da Prosperfy.

Persist effective economic owner/entity.

### Reimbursement

Owner:

> Isso é reembolsável pelo Guilherme.

Persist receivable metadata without treating reimbursement settlement as new personal income.

### Statement

Owner sends a closed card statement PDF.

System:

1. identifies account/card candidate;
2. extracts cycle/closing/due date and lines;
3. matches against imported transactions;
4. reports matched/unmatched/discrepant;
5. asks for confirmation if ambiguity exists;
6. closes/reconciles the cycle only when safe.

# Credit card month/cycle requirement

Pluggy may return transactions spanning multiple billing statements in one account/history.

Therefore every transaction needs distinct concepts:

```text
transaction_date
posted_date
purchase_month
competence_month
statement_cycle_id
cashflow_month
```

Do not collapse all of them into one `month`.

See `02_DATA_MODEL_AND_CYCLES.md`.

# New bank onboarding

The current live item count is not a contract.

More banks/accounts will be connected.

Never hard-code:

```text
ITEMS=3
BANKS=3
CURRENT_TX_COUNT=1322
```

When a new bank is registered:

- sync all available history;
- classify historical imports as onboarding backlog;
- do not proactively spam;
- expose backlog count/filter;
- allow month-by-month batch resolution;
- after onboarding cutover, new ambiguous transactions enter normal proactive flow.

# Upstream truth vs effective truth

Never mutate/delete the raw upstream payload to make the UI look correct.

Required model:

```text
RAW SOURCE
  ↓
NORMALIZED SOURCE
  ↓
USER CORRECTION / LEARNED RULE
  ↓
EFFECTIVE FINANCIAL VIEW
```

Aggregates use effective values when an accepted correction exists.

Audit must explain why effective != raw.

# STOP / escalation conditions

Normal coding uncertainty is not a STOP condition.

STOP only when one of these occurs:

```text
ARCHITECTURE_ESCALATION_REQUIRED=YES
```

Examples:

- requirement implies a new trust boundary not described here;
- Production mutation is necessary;
- destructive data rewrite is unavoidable;
- a secret must be exposed to browser/client;
- payment initiation would be required;
- owner identity cannot be resolved deterministically;
- current WhatsApp transport cannot safely bind replies and requires a new external service;
- file/email ingestion requires a material platform change with multiple viable architectures;
- canonical baseline mismatch.

Report:

```text
ARCHITECTURE_ESCALATION_REQUIRED=YES
CAUSE=
IMPACT=
MINIMAL_OPTION_A=
MINIMAL_OPTION_B=
RECOMMENDATION=
```

Otherwise continue autonomously.

# Allowed

- inspect entire repository;
- create F2B branch from canonical master;
- edit Finance/Cognitive/Hermes code necessary for F2B;
- add migrations;
- add tests;
- add docs;
- use existing email/WhatsApp/ProsperfySkill capabilities;
- use homolog secrets by reference/environment only;
- deploy to homolog;
- create safe backups;
- run controlled reprocess/backfill in homolog;
- fix in-scope regressions;
- commit and push F2B branch.

# Prohibited

- Production deploy/mutation;
- merge to master;
- force-push master;
- payment initiation;
- real PIX/transfer/payment;
- exposing API tokens to browser;
- logging raw secrets;
- inventing C6 cards not supplied by upstream;
- deleting raw financial evidence;
- mass messaging historical clarifications;
- using LLM memory as persistence;
- broad frontend redesign;
- unrelated Browser Harness/Supabase/Trello work.

# Commit discipline

Prefer cohesive commits by subsystem.

Examples:

```text
feat(finance): add statement cycle and competence model
feat(finance): add persistent correction and rule engine
feat(finance): add clarification delivery and reply binding
feat(finance): reconcile imported closed statements
feat(finance): add historical clarification batch workflow
feat(hermes): route owner finance clarification replies
test(finance): add f2b end-to-end acceptance coverage
docs(finance): document f2b architecture and runbook
```

Avoid giant unreviewable single commit if parallel subagents are used.

# Final requirement

At the end update the project documentation so it describes what was actually implemented, not only the original plan.

Return `10_FINAL_REPORT_TEMPLATE.md` fully completed.

STOP with:

```text
F2B_BRANCH=
F2B_FINAL_SHA=

CODE_READY=YES
LIVE_READY=YES
HUMAN_PASS=NO

MASTER_UNTOUCHED=YES
PRODUCTION_TOUCHED=NO
SECRETS_EXPOSED=NO

READY_FOR_OWNER_HUMAN_ACCEPTANCE=YES
```
