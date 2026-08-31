# F2B — Homolog Live Deploy Runbook

## Scope

Only homolog.

Production is forbidden.

## Pre-deploy

Record:

```text
SOURCE_SHA=
BRANCH=dev/finance-v2-f2b
WORKTREE_CLEAN=
MASTER_UNTOUCHED=
```

Run all relevant suites/build.

## Backup

Before migrations:

- backup Finance SQLite/DB;
- record schema version;
- never print secrets.

If persistent state spans multiple stores, back up each store affected by F2B migrations.

## Migrations

- apply incremental migrations only;
- verify schema;
- if backfill required, dry-run first when feasible;
- record counts before/after.

## Services

Restart only services required for F2B.

Use safe stop/start procedures.

Verify runtime SHA for:

```text
Finance API
Finance Web if changed
Cognitive if changed
Hermes if changed
WhatsApp bridge integration if changed
```

## Data integrity baseline

Capture:

```text
transactions
accounts/items
open clarifications
multi-open violations
corrections
rules
statement cycles
statement imports
```

## Backfill

If migration derives new period/cycle fields:

- do not invent statement cycles without evidence;
- purchase month may be derived;
- competence defaults must be documented;
- historical ambiguous items remain onboarding backlog.

## WhatsApp live

Use authorized test actors only.

Do not send historical pending questions in bulk.

Test one controlled clarification and quoted reply.

## Statement live

Use a safe homolog statement artifact.

Prefer owner-supplied/known statement or sanitized fixture.

Do not process unrelated mailbox attachments.

## Rollback

Rollback if:

- migration corrupts counts;
- duplicate clarifications appear;
- ACL leaks finance data;
- corrected values disappear after sync;
- statement import duplicates;
- historical backlog floods WhatsApp;
- unexpected Production target is observed.

Rollback procedure must preserve newly captured evidence for debugging without exposing secrets.

## Live report

Include:

```text
SOURCE_SHA
RUNTIME_SHA(s)
MIGRATIONS
BACKUPS
TESTS
DATA_COUNTS_BEFORE_AFTER
ACL_E2E
CLARIFICATION_E2E
REPLY_BINDING_E2E
BATCH_ONBOARDING_E2E
CORRECTION_E2E
STATEMENT_E2E
REGRESSIONS
KNOWN_LIMITATIONS
```

Only declare `LIVE_READY=YES` after actual integrated paths are proven.
