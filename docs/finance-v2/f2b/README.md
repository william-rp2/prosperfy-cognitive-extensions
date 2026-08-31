# Finance V2 — F2B Autonomous Delivery Pack

## Purpose

This package is the canonical execution dossier for **Finance V2 — F2B**.

The goal is to let **Opus 5 in autonomous/loop mode** implement the module end-to-end, using subagents where useful, with minimal owner intervention and with a final Human Acceptance only after the system reaches `CODE_READY=YES` and `LIVE_READY=YES` in homolog.

## Mandatory prerequisite

Do **not** start F2B from a stale branch.

Expected F2A source:

- `dev/finance-v2-f2a`
- `f4f491c745c970766274f0f37abfdb3874bc1222`

Before F2B begins:

1. F2A must be accepted as `HUMAN_PASS=YES`.
2. `master` must be fast-forwarded to exactly the accepted F2A source.
3. `origin/master` must equal the accepted source.
4. API/Web suites must be green.
5. Create `dev/finance-v2-f2b` **from canonical master**.

If master is not exactly the accepted F2A source at F2B bootstrap, **STOP** and report the mismatch.

## What F2B is

F2B is the phase in which Finance stops being mainly a synchronized/read interface and becomes a persistent financial assistant integrated with Hermes/WhatsApp.

Core areas:

- finance owner ACL;
- finance WhatsApp group and explicit owner DMs;
- clarification queue;
- quoted-reply binding;
- historical onboarding;
- month/competence and credit-card cycle modeling;
- closed-statement ingestion/reconciliation;
- persistent financial corrections;
- learned merchant rules;
- correction of upstream Pluggy errors without destroying raw data;
- historical spreadsheet export/import;
- incremental onboarding as more banks are connected;
- bounded bug/integrity sweep;
- technical + live E2E.

## Hard principles

1. Raw upstream data is immutable evidence.
2. Effective financial truth may differ from raw via explicit corrections.
3. Never invent bank/card/currency data that upstream did not provide.
4. Financial totals must never silently mix currencies.
5. Authorization is deterministic and pre-LLM.
6. State belongs in DB, not LLM memory.
7. A clarification is persistent and idempotent.
8. A quoted reply must resolve the correct pending question even days later.
9. Historical backlog must never spam WhatsApp.
10. New banks must be supported without hard-coded item counts.
11. Credit-card statement cycles are first-class domain entities.
12. Closed statements are reconciliation evidence, not a reason to overwrite raw Pluggy data.
13. Human corrections outrank upstream interpretation for effective finance.
14. No payment initiation, PIX sending, transfer execution, or financial mutation outside bookkeeping metadata.
15. Production is out of scope unless separately and explicitly authorized.

## Files

- `00_OPUS5_LOOP_EXECUTION_PROMPT.md` — copy/paste prompt for autonomous Opus 5.
- `01_SCOPE_AND_ARCHITECTURE.md` — system scope, architecture, invariants.
- `02_DATA_MODEL_AND_CYCLES.md` — transaction months, competence, statements, cycle model.
- `03_WHATSAPP_ACL_AND_CLARIFICATIONS.md` — finance group, owners, replies, queue.
- `04_CORRECTIONS_AND_LEARNING.md` — user overrides and learned merchant rules.
- `05_STATEMENTS_EMAIL_RECONCILIATION.md` — PDF/email statement ingestion and reconciliation.
- `06_ONBOARDING_HISTORICAL_BACKFILL.md` — historical pendings, month filtering, spreadsheet workflow.
- `07_BUG_SWEEP_AND_KNOWN_LIMITATIONS.md` — what to fix, what not to chase.
- `08_TEST_AND_E2E_ACCEPTANCE_MATRIX.md` — required tests and scenarios.
- `09_LIVE_DEPLOY_RUNBOOK.md` — homolog deploy/recovery gates.
- `10_FINAL_REPORT_TEMPLATE.md` — mandatory final report.
