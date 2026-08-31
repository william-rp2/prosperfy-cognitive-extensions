# F2B — Historical Onboarding and Batch Backfill

## Context

The current backlog is large and more banks will still be added.

Therefore current clarification count is temporary and must never be hard-coded.

The correct model is **incremental onboarding**.

## Onboarding states

Per source/account, maintain enough state to distinguish:

```text
HISTORICAL_IMPORT
ONGOING
```

Optional concepts:

```text
onboarding_started_at
historical_cutoff_at
onboarding_completed_at
```

Transactions imported before the cutover are historical backlog.

Transactions after cutover use normal proactive policy.

## New bank behavior

When a new bank/account is added:

1. sync available history;
2. classify/normalize deterministically;
3. create clarifications only where needed;
4. mark them historical/onboarding;
5. do not proactively send all questions;
6. report how many need attention;
7. let owner process period-by-period;
8. once baseline is acceptable, mark onboarding complete.

## Owner workflow

Example:

> Você tem N pendências históricas.

Owner:

> Traga as de agosto.

Finance:

- resolves August using `competence_month` when known;
- otherwise uses documented fallback;
- returns count and summary;
- offers spreadsheet batch.

## Spreadsheet batch

Export should be deterministic and round-trippable.

Suggested columns:

```text
transaction_id
competence_month
purchase_date
institution
account
merchant
amount_original
currency_original
amount_effective
currency_effective
category
economic_owner
responsible
reimbursement_from
reimbursement_status
statement_cycle
notes
needs_confirmation
```

Editable columns must be clearly documented.

Import flow:

```text
upload
→ parse
→ dry-run
→ row validation
→ conflict detection
→ owner confirms/apply
→ audit
```

## Stale spreadsheet protection

An owner may edit a file for hours/days while sync continues.

Export should include:

```text
export_version
transaction_revision / updated_at
```

On import, if a transaction changed after export:

- do not blindly overwrite;
- return conflict row;
- allow explicit owner override.

## Batch idempotency

Reimporting an already-applied file must not duplicate corrections or resolution events.

## Period semantics

“Agosto” should not simply mean `created_at` or sync date.

Filter order:

1. effective `competence_month`;
2. assigned statement cycle competence;
3. purchase month fallback;
4. if ambiguous, include but mark as period uncertain.

## Completion

Historical onboarding is complete when owner explicitly accepts a cutover.

Do not require 100% classification before ongoing mode.

The owner may intentionally leave low-value historical items unresolved.

## Future banks

This workflow repeats independently for each newly connected institution/account.

The system must continue to work while older banks are already in ongoing mode.
