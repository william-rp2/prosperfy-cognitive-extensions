# F2B — Bug Sweep and Known Limitations

## Bug-sweep philosophy

F2B autonomous execution may fix real Finance defects discovered during implementation/E2E.

It must not become an unlimited cleanup project.

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
- runtime path different from tested path;
- regression in PIX/card/refund/alias/notes/filter behavior;
- secret exposure;
- production mutation.

## Known upstream limitations — do not fake a fix

### C6 multiple cards

Current source returns one consolidated C6 credit account.

The current data does not provide enough stable identity to reconstruct all physical/virtual/additional cards.

Do not fabricate four card entities.

If future/new connector data provides stable card-level identity, support it generically.

### Upstream currency errors

MyPluggy may itself report an international transaction as BRL.

If raw source is wrong:

- preserve raw;
- allow owner correction;
- allow a scoped learned rule;
- never claim Pluggy sent data it did not send.

### IOF

Current policy:

- explicit IOF evidence → classify IOF;
- no explicit evidence → do not auto-label solely from amount/proximity.

Statement reconciliation may provide stronger IOF evidence.

## Current improvements not worth blocking F2B

- broad frontend redesign;
- aesthetic polish;
- exhaustive responsive redesign;
- visual hierarchy refactor;
- perfect institution branding;
- advanced card art;
- Purchase Research;
- general-purpose email intelligence;
- Browser Harness work unrelated to statement ingestion.

## Historical counts

Never assert that current transaction/clarification count is permanent.

More banks will change the dataset.

## Bills/statement model

F2B is explicitly allowed to implement the first-class cycle/statement model needed for reconciliation.

Do not create a second unrelated competing “bills” model if existing data can be extended cleanly.

## Bugs from previous technical reports

Treat old report PASS as evidence, not truth.

If Human/real E2E contradicts a unit test, reproduce the real code path.

Rule:

```text
REAL_RUNTIME_PATH > ISOLATED_FORMATTER_TEST
```
