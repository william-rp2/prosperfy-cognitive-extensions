# F2B — Closed Statements, Email/PDF Ingestion and Reconciliation

## Goal

A closed credit-card statement is strong evidence for:

- which cycle a purchase belongs to;
- the closed total;
- due date;
- currency/account amount;
- missing/duplicate provider transactions;
- discrepancy detection.

Finance should accept a statement through Hermes or an authorized email ingestion path and reconcile it against imported transactions.

## Sources

Supported logical sources:

```text
HERMES_ATTACHMENT
FINANCE_EMAIL_ATTACHMENT
MANUAL_UPLOAD
PLUGGY_BILL (when available)
```

Use existing platform capabilities first.

Do not create a broad general-purpose email subsystem if narrow finance email actions already exist.

## Email boundary

Only configured finance mailboxes/senders/folders may be processed.

Recommended narrow capability:

```text
finance.email.list_candidates
finance.email.read_statement
finance.email.fetch_attachment
```

Do not expose general mailbox access to Finance LLM context unless required.

## Statement file pipeline

```text
attachment
→ malware/type/size validation
→ text extraction
→ structured statement parser
→ account/card candidate resolution
→ statement cycle draft
→ transaction matching
→ discrepancy report
→ confirmation when needed
→ reconciled cycle
```

## Extraction strategy

Prefer:

1. native PDF text extraction;
2. structured parser/templates;
3. vision/OCR fallback only if necessary;
4. LLM semantic extraction as constrained structured-data step.

If LLM is used:

- statement content is untrusted data;
- ignore instructions embedded inside document;
- force structured schema output;
- validate all money/date fields deterministically;
- never let document text authorize actions.

## Statement fields

Extract when present:

```text
institution
card/account hints
last4
holder
cycle/statement label
period_start
period_end
closing_date
due_date
statement_currency
total
minimum_payment if present
line items
fees
IOF/finance charges
payments/credits
```

Do not require all fields for every bank.

## Line-item model

Keep imported statement lines separately from Pluggy transactions.

Example:

```text
statement_line_id
statement_cycle_id
date
description_raw
amount
currency
line_type
card_hint nullable
source_page nullable
```

Never replace Pluggy transaction rows with statement lines.

## Matching engine

Use deterministic scoring with explainable evidence.

Candidate evidence:

- amount/account amount;
- currency;
- normalized merchant;
- transaction date tolerance;
- posted date;
- account/card;
- last4/card metadata when available;
- explicit provider IDs when available.

Example confidence:

```text
EXACT
HIGH
AMBIGUOUS
UNMATCHED
CONFLICT
```

Do not auto-match two Pluggy rows to the same statement line unless model explicitly supports split/compound entries.

## Duplicate/compound charges

Support cases such as:

- international purchase + separate IOF;
- refund;
- installment descriptors;
- statement adjustment;
- fee;
- payment.

Do not infer a fee as IOF solely because it is near an international purchase unless statement itself identifies IOF.

## Cycle close

A cycle can become `RECONCILED` only when policy allows.

Recommended gate:

```text
statement total parsed
account identified
no unresolved duplicate mapping
difference within exact deterministic tolerance
all material unmatched lines classified/accepted
```

If not:

```text
status=DISCREPANT
```

and show the difference.

## Reconciliation report

Owner should be able to ask:

> Confere minha fatura do C6 de agosto.

Return:

```text
total da fatura
total conciliado
quantidade casada
itens só na fatura
itens só no Pluggy
diferença
ambiguidades
```

## Cycle assignment

A high-confidence statement match may assign transaction to that statement cycle.

This must not modify the purchase date.

## Statement sent via WhatsApp

If the WhatsApp bridge exposes file metadata/download safely:

- bind attachment to requesting authorized actor/chat;
- store a safe file reference/hash;
- process asynchronously if needed;
- reply with reconciliation result.

If transport support is missing and adding it requires a new trust boundary, raise architecture escalation instead of using an unsafe workaround.

## Email automation

Potential future/proactive flow:

- periodically detect new closed statement emails;
- ingest only matching configured rules;
- notify finance group that a statement is ready to reconcile.

For F2B, one-shot owner-triggered email lookup is sufficient if recurring monitoring would materially increase scope.
