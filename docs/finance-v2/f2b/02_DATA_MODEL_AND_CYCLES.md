# F2B — Data Model, Months, Competence and Credit-Card Cycles

## Problem

An imported transaction's date does not answer every financial question.

For credit cards in particular, a provider may return transactions from two or more statements in one history response.

A transaction can have:

- purchase date in July;
- posting date in August;
- belong to the August statement;
- be paid in September.

All are valid facts.

Therefore Finance must never rely on a single generic `month`.

## Required temporal semantics

Each effective transaction should expose, directly or derivably:

```text
transaction_date
posted_date
purchase_month
competence_month
statement_cycle_id
cashflow_month
```

### transaction_date

Original transaction/purchase date from source where available.

### posted_date

Date the institution posted/settled the transaction when source exposes it.

### purchase_month

`YYYY-MM` derived from transaction/purchase date.

This answers:

> Em que mês eu fiz essa compra?

### statement_cycle_id

Nullable link to a card statement cycle.

This answers:

> Em qual fatura essa compra entrou?

### competence_month

The month the owner wants the expense associated with for financial analysis.

Default policy:

- checking/payment account: purchase/transaction month;
- credit-card transaction: prefer assigned statement cycle's competence month when cycle is known;
- explicit user correction overrides default.

Do not assume `competence_month == purchase_month`.

### cashflow_month

Month in which cash actually left/entered the underlying cash account.

For card purchases, this is normally linked to statement payment, not purchase date.

This allows:

- spending analysis by competence;
- cashflow analysis by payment month;
- purchase history by purchase month.

## Statement cycle entity

Introduce/reuse a first-class card cycle concept such as:

```text
financial_statement_cycles
- id
- financial_account_id
- source
- source_external_id nullable
- cycle_label
- period_start nullable
- period_end nullable
- closing_date nullable
- due_date nullable
- competence_month
- statement_currency
- statement_total_cents nullable
- effective_total_cents nullable
- status
- reconciliation_status
- imported_at
- closed_at nullable
- metadata_json
```

Status candidates:

```text
OPEN
CLOSED_SOURCE
RECONCILING
RECONCILED
DISCREPANT
ARCHIVED
```

Internal enum naming may be English. User-facing text must be pt-BR.

## Transaction-to-cycle association

Use a durable association, not a frontend filter illusion.

Each credit-card transaction may have:

```text
statement_cycle_id nullable
cycle_assignment_source
cycle_assignment_confidence
cycle_assignment_updated_at
```

Assignment source:

```text
PLUGGY_BILL
STATEMENT_IMPORT
USER
RULE
INFERRED
```

Priority:

```text
USER
> trusted statement reconciliation
> explicit upstream bill identity
> deterministic date/cycle rule
> inference
```

A stronger source must not be silently overwritten by a weaker source during sync.

## Late-arriving transaction

If a transaction is imported after a cycle was created:

- evaluate association;
- if it matches a closed but unreconciled cycle, add and mark cycle dirty;
- if it changes a reconciled cycle, do not silently rewrite closure;
- flag reconciliation drift and notify/surface it.

## Provider merges two statements

This is expected behavior to tolerate.

Never assume all transactions returned for a card account belong to one current cycle.

Cycle assignment happens in our domain using:

1. imported statement evidence;
2. upstream bill metadata when trustworthy;
3. configured closing/due date rules;
4. user correction.

## User month correction

Owner must be able to say:

> Essa compra é de agosto.

Persist:

```text
effective_competence_month=2026-08
source=USER
```

Do not change source transaction date.

## New banks and old history

When a newly connected bank imports historical data:

- determine purchase month immediately;
- do not force a statement cycle if evidence is missing;
- mark historical ambiguous transactions as onboarding backlog;
- allow later cycle reconciliation from statements.

## Aggregates

Every aggregate must declare its basis.

Examples:

```text
spend_by_competence_month
cashflow_by_cashflow_month
purchases_by_purchase_month
statement_total_by_cycle
```

Avoid ambiguous helpers such as `sumByMonth()` without semantic name.

## Effective amount + cycle

Currency correction and cycle correction are separate dimensions.

A transaction may have:

```text
raw USD/BRL data
effective amount correction
effective competence correction
statement cycle assignment
category correction
economic owner correction
```

Do not pack all corrections into one opaque JSON if typed/auditable fields are practical.
