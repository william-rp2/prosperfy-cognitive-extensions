# F2B — WhatsApp ACL, Clarification Queue and Reply Binding

## Authorized finance actors

Finance access is owner-only.

The implementation must resolve authorized actors from canonical identity data, not hard-coded display names.

Contracts:

```text
authorized owner in finance group → ALLOW
authorized owner explicit finance DM → ALLOW
third party finance request → DENY
unknown actor → DENY
```

Authorization is pre-LLM and fail-closed.

## Finance group

Proactive finance messages must go only to the designated finance group.

The group identifier must be configuration/resource data, not hidden in prompt text.

## Clarification entity

A clarification needs durable identity.

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

Preserve the existing one-open-per-transaction/question-type invariant.

## Question types

Examples:

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

Do not create a new question type for every phrase variation.

## Queue policy

Historical backlog and normal flow are different modes.

### Historical/onboarding

- suppress proactive one-by-one messaging;
- expose count;
- support month/account/card filtering;
- support batch export/import;
- owner explicitly chooses what to process.

### Ongoing/new transactions

- prioritize recent ambiguous transactions;
- avoid excessive frequency;
- group related questions when appropriate;
- never ask the same unresolved question after each sync;
- no duplicate open clarification.

## Reply binding

Best path:

```text
outbound WhatsApp question
→ persist delivery_message_id + clarification_id
→ owner quotes/replies to message
→ inbound reply references quoted message ID
→ resolve exact clarification
```

This must work hours or days later.

LLM conversation memory is irrelevant to exact binding.

## Loose reply fallback

If owner sends a reply without quoting:

1. inspect explicit references in text;
2. inspect a small set of currently relevant/open clarifications;
3. require strong confidence;
4. if multiple plausible questions exist, ask which one;
5. never resolve a random transaction.

## Late reply

If clarification is already resolved:

- do not duplicate mutation;
- explain it was already resolved;
- allow owner to request correction/change.

## Cancellation

Owner can say:

> Deixa essa para depois.

or equivalent.

Clarification remains unresolved but delivery should not immediately repeat.

Support snooze/defer state if needed.

## Historical count behavior

Owner may ask:

> Quantas pendências?

Return a real dynamic count, not a cached historic number.

Owner may ask:

> Traga as de agosto.

Filter by effective period semantics:

- `competence_month` when known;
- otherwise a documented fallback such as purchase month;
- clearly mark items whose competence is still unknown.

## Spreadsheet workflow

Required onboarding capability:

```text
filter pending
→ export batch
→ owner edits spreadsheet
→ import
→ validate
→ apply accepted rows
→ report rejected/ambiguous rows
```

Minimum columns:

```text
transaction_id
date
institution
account_alias
merchant
original_description
amount
currency
competence_month
category
economic_owner
responsible
reimbursement
notes
action
```

The export must never expose secrets/full sensitive account numbers.

The import must:

- validate transaction IDs;
- reject stale/unknown IDs;
- validate enums/period;
- be idempotent;
- support dry-run;
- return row-level errors;
- not overwrite newer explicit corrections silently.

CSV is acceptable if XLSX transport is materially harder. If existing stack supports XLSX safely, prefer XLSX.

## Anti-spam acceptance

A sync loop may run repeatedly while a clarification is open.

Required:

```text
SYNC x 10
OPEN_QUESTION_COUNT remains 1
OUTBOUND_QUESTION_COUNT does not grow unless retry policy explicitly requires delivery recovery
```
