# F2B — Persistent Corrections and Learned Financial Rules

## Goal

Upstream bank data can be incomplete or wrong.

Finance needs an auditable correction layer that lets an authorized owner establish effective truth without destroying the source record.

## Correction model

Conceptually:

```text
financial_corrections
- id
- transaction_id
- field
- old_effective_value
- new_effective_value
- reason
- source
- actor_id
- created_at
- superseded_at nullable
```

Fields may include:

```text
amount
currency
amount_in_account_currency
category
merchant
economic_owner
responsible
reimbursement
competence_month
statement_cycle
notes
```

An implementation can group compatible corrections, but auditability must remain.

## Raw vs effective

Example:

```text
Pluggy raw:
amount=28.19
currency=BRL

Owner correction:
amount=5.00
currency=USD
account_amount=28.19
account_currency=BRL

Effective:
US$ 5.00
≈ R$ 28,19
```

Never overwrite the raw payload to simulate that Pluggy sent USD.

## Aggregate behavior

Accepted effective corrections must feed relevant totals.

If an owner corrects foreign currency/account amount, the dashboard must use the corrected account/base amount under the same currency safety rules as native data.

## Merchant rule model

Examples:

```text
merchant_pattern
rule_type
target_value
mode
confidence/verification metadata
active
created_by
```

Rule types:

```text
CURRENCY_HINT
CATEGORY
ECONOMIC_OWNER
RESPONSIBLE
REIMBURSEMENT
COMPETENCE
```

Modes:

```text
SUGGEST
TRUSTED
```

Default new semantic rule: `SUGGEST`.

Owner can explicitly promote:

> Sempre considere OpenAI como Tecnologia e em dólar.

Only then may deterministic application be enabled if the rule is sufficiently bounded.

## Rule matching

Never use unsafe broad substring matching that can contaminate unrelated merchants.

Prefer:

- normalized merchant identity;
- stable provider merchant when available;
- anchored/specific pattern;
- institution/account scope when relevant.

Store the evidence that caused a rule match.

## Rule precedence

Suggested order:

```text
explicit transaction correction
> owner trusted scoped rule
> deterministic source metadata
> suggestion rule
> classifier/LLM inference
```

## Conflict

If two trusted rules conflict:

- do not silently pick one;
- mark conflict;
- ask owner or require explicit precedence.

## Currency learning

A merchant being “usually USD” is not proof that every transaction is USD.

Suggested behavior:

```text
SUGGEST rule:
"Essa cobrança da OpenAI costuma ser em USD. Confirmar?"

TRUSTED scoped rule:
apply only when scope and amount semantics are known.
```

If upstream provides a reliable currency that conflicts with a learned rule, surface discrepancy rather than blindly override.

## Reimbursement semantics

Track separately:

```text
economic_owner
paid_by
receivable_from
receivable_status
```

Settlement of a receivable is not automatically personal income.

## Responsible/person attribution

Card/account owner metadata is not enough to claim who made a transaction.

If card-level upstream identity is absent:

- owner can assign responsibility per transaction;
- a learned rule can suggest responsibility when safe;
- never fabricate attribution from consolidated C6 account identity.
