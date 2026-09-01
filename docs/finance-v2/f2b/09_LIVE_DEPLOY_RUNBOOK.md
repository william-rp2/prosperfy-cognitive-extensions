# F2B — Homolog Live Deploy Runbook

## Scope

Only homolog. Production is forbidden.

This runbook complements `11_HOMOLOG_DEPLOY_MANIFEST.md` — the manifest is the file checklist; this document is the procedural gate sequence.

---

## Step 0 — Pre-deploy record

```text
SOURCE_SHA=21bccff2788cd354452d3c1ef664dcbc3e3f7a34
BRANCH=dev/finance-v2-f2b
WORKTREE_CLEAN=YES
MASTER_UNTOUCHED=YES   # origin/master = f4f491c745c970766274f0f37abfdb3874bc1222
PRODUCTION_TOUCHED=NO
```

Run all relevant suites/build on SOURCE_SHA before copying artifacts.

Expected minimum (Bloco 4 handoff):

```text
FINANCE_API_TESTS=299/299
FINANCE_WEB_TESTS=48/48
PYTHON_TESTS=658 pass / 103 skip / 0 fail
TSC=PASS
```

---

## Step 1 — SCHEMA GATE (READ-ONLY — **FIRST**)

**Before** copying code or restarting Finance API, query homolog SQLite:

```sql
SELECT name, applied_at
FROM schema_migrations
WHERE name = '014_statement_imports.sql';
```

| Result | Action |
|---|---|
| **0 rows** | `MIGRATION_014_ALREADY_APPLIED=NO` → proceed |
| **1 row** | `DEPLOY_BLOCKED=YES` → **STOP** |

If blocked:

```text
REASON=amended migration 014 already applied
CODE_ACTION_REQUIRED=new migration 015 in separate CODE stage
```

Do **not**:

- reapply 014
- edit schema manually
- partial deploy

### Migration 014 contract

- **Path:** `apps/financeiro-pessoal-api/src/finance/migrations/014_statement_imports.sql`
- **Changed in-place:** YES (F2B branch only — never in master)
- **In master:** NO
- **Premise:** 014 was never applied on the target homolog DB receiving this deploy

If homolog already ran an older version of 014, the amended DDL may not match. That requires a new forward migration (015), not a redeploy of this SHA.

---

## Step 2 — Backup

Before first Finance API startup post-copy:

- backup Finance SQLite (`FINANCE_DB_PATH`);
- record `schema_migrations` full list;
- never print secrets.

If multiple stores are affected, back up each.

Suggested path:

```text
/home/will/data/financeiro-pessoal/backups/financeiro-pessoal-<tag>-<timestamp>.sqlite3
```

---

## Step 3 — Deploy artifacts

Follow `11_HOMOLOG_DEPLOY_MANIFEST.md` sections B–E.

Critical:

- `npm install` + `npm rebuild better-sqlite3` on host (native module)
- copy `dist/` including `dist/finance/migrations/`
- verify runtime SHA after deploy

Migrations run automatically on Finance API boot — **do not** run SQL manually unless rollback restore.

---

## Step 4 — Services restart

| Service | Authorized |
|---|---|
| Finance API | YES |
| Finance Web | YES (if changed) |
| Cognitive homolog API | YES (if changed) |
| **Hermes gateway** | **NO** |
| **WhatsApp bridge** | **NO** |
| Production | NO |

Finance API on homolog is typically manual (`node dist/index.js`), not systemd.

Cognitive homolog: `prosperfy-cognitive-homolog-api.service` (uvicorn `:8800`).

### Hermes boundary

```text
hermes-gateway.service restart = NOT AUTHORIZED at this stage
```

If Hermes code changed but gateway is not restarted:

```text
HERMES_LIVE_RESTART_REQUIRED=YES
WHATSAPP_LAST_HOP=BLOCKED_BY_RESTART_AUTH
```

Do not claim WhatsApp E2E PASS without runtime evidence.

Deploy executor validates everything up to the last hop.

---

## Step 5 — Post-deploy smoke

See manifest section H. Minimum:

1. `/health`
2. Authenticated `/api/finance/summary`
3. `POST /api/finance/sync` — temporal columns populated (cycleAssignment wired)
4. PDF import smoke (`POST /api/finance/statements/import/pdf`)
5. Statement reconcile smoke
6. Cognitive ACL smoke on `:8800`
7. Runtime SHA matches SOURCE_SHA
8. Confirm `014_statement_imports.sql` in `schema_migrations` (if gate was NO)

---

## Step 6 — Data integrity baseline

Capture before/after counts:

```text
transactions
accounts/items
open clarifications
multi-open violations
corrections
merchant rules
statement cycles
statement imports
statement lines
reconciliations
discrepancies
```

---

## Step 7 — Live E2E (controlled)

Use authorized test actors only.

Do not bulk-send historical clarifications.

Test one controlled:

- clarification + quoted reply
- correction persist through sync
- statement reconcile with safe fixture
- ACL deny for third party

---

## Step 8 — Rollback

Rollback if:

- migration corrupts counts;
- duplicate clarifications;
- ACL leaks finance data;
- corrections disappear after sync;
- duplicate statement imports;
- historical backlog floods WhatsApp;
- unexpected Production target;
- `MIGRATION_014_ALREADY_APPLIED=YES` discovered after partial deploy.

Procedure: stop API → restore SQLite backup → restore previous dist → restart previous SHA.

Preserve evidence for debugging without exposing secrets.

---

## Live report fields

```text
SOURCE_SHA
RUNTIME_SHA(s)
MIGRATION_014_ALREADY_APPLIED   (pre-deploy gate result)
MIGRATIONS_APPLIED              (post-boot)
BACKUPS
TESTS
DATA_COUNTS_BEFORE_AFTER
ACL_E2E
CLARIFICATION_E2E
REPLY_BINDING_E2E
STATEMENT_PDF_E2E
STATEMENT_RECONCILE_E2E
REGRESSIONS
KNOWN_LIMITATIONS
HERMES_LIVE_RESTART_REQUIRED
WHATSAPP_LAST_HOP
```

Only declare `LIVE_READY=YES` after integrated paths are proven in homolog runtime.
