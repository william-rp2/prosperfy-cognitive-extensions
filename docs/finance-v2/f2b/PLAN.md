# F2B — Internal Execution Plan (owner: orchestrator)

Baseline: `dev/finance-v2-f2b` from `f4f491c745c970766274f0f37abfdb3874bc1222`.

This file is the coordination contract. Subagents MUST respect file ownership
and pre-allocated migration numbers. It is updated as decisions change.

## Architecture decisions (CP0 outcome)

| # | Decision | Rationale |
|---|---|---|
| D1 | Finance persistence stays SQLite + raw SQL + `src/finance/migrations/NNN_*.sql`, run at boot by `db.ts:runMigrations` | Existing working foundation; dossier says extend, not rewrite |
| D2 | New temporal fields are typed columns on `financial_transactions`, not opaque JSON | `02_DATA_MODEL_AND_CYCLES.md` requires auditable typed fields |
| D3 | Statement cycles are a new first-class table, not an extension of `financial_credit_card_bills` | Bills mirror Pluggy; cycles are our domain truth. No competing second bills model: bills stay read-only upstream mirror |
| D4 | Corrections are an append-only ledger with `superseded_at`, effective view derived at read time | Raw immutability + auditability |
| D5 | Statement upload is `@fastify/multipart` on Finance API; PDF text via a pure-JS extractor; LLM only as constrained structured step | No upload/PDF surface exists today |
| D6 | Email statement path is DEFERRED. No email module exists in-repo; only external MCP tools. Building an email subsystem is out of proportion for F2B | `05_STATEMENTS_EMAIL_RECONCILIATION.md` §8 explicitly allows upload/Hermes instead. Recorded as debt |
| D7 | E2E matrix runs as integration tests on the real runtime path (SQLite -> repo -> service -> fastify `app.inject`) plus pytest for Cognitive/Hermes. No browser harness introduced | `34. REAL_RUNTIME_PATH > ISOLATED_UNIT_ASSERTION`; adding Playwright is out of scope |
| D8 | ACL is enforced in Cognitive policy before LLM, keyed on canonical actor identity; Finance API stays the enforcement-free inner layer behind the gateway | Finance SQLite has no tenant column; tenancy lives in Cognitive Postgres |
| D9 | Spreadsheet transport is CSV (RFC4180-style, hand-written writer/parser in `spreadsheetExport.ts`/`spreadsheetImport.ts`). Decided by SUBAGENT_B | No xlsx/exceljs (or any spreadsheet) library exists in the current `package.json` dependency tree, and a safe pure-JS XLSX writer (zip container, shared-strings table, escaping) is materially harder to get right than a CSV writer/parser. CSV round-trips cleanly through every spreadsheet tool the owner already uses |

## Migration numbers — pre-allocated, do NOT deviate

| File | Owner |
|---|---|
| `008_statement_cycles.sql` | A |
| `009_transaction_temporal.sql` | A |
| `010_financial_corrections.sql` | A |
| `011_merchant_rules.sql` | A |
| `012_clarification_delivery.sql` | B |
| `013_onboarding_state.sql` | B |
| `014_statement_imports.sql` | D |
| `core/migrations/009_finance_f2b_grants.sql` | C |

## File ownership — no two agents write the same file

### SUBAGENT_A — domain / DB
Owns: `apps/financeiro-pessoal-api/src/finance/migrations/008..011`,
`statementCyclesRepository.ts`, `correctionsRepository.ts`, `merchantRulesRepository.ts`,
`effectiveTransaction.ts`, `temporalSemantics.ts`, `cycleAssignmentService.ts`,
and their `.test.ts`. May edit `transactionAmount.ts` and `pluggySyncService.ts`
ONLY at the integration points named in its brief.

### SUBAGENT_B — clarifications / onboarding
Owns: migrations `012..013`, `clarificationsRepository.ts`,
`clarificationQueueService.ts`, `onboardingRepository.ts`, `spreadsheetExport.ts`,
`spreadsheetImport.ts`, and their tests. Owns clarification routes inside
`routes/finance.ts` (see route ownership below).

### SUBAGENT_C — cognitive / ACL / hermes
Owns: `core/cognitive/cognitive/registry/capabilities/finance.*.yaml` (new files only),
`core/migrations/009_finance_f2b_grants.sql`, `policy/` finance rules,
`adapters/finance_api/client.py`, `hermes/capability-intelligence/.../finance_service.py`,
`capability_router.py`, plus pytest under `core/cognitive/tests/`. Python only —
must not touch TypeScript.

### SUBAGENT_D — statements / reconciliation
Owns: migration `014`, `statementImportRepository.ts`, `statementParser.ts`,
`statementMatchingService.ts`, `reconciliationService.ts`, upload plumbing,
and their tests. Consumes A's cycles table; must not alter A's migrations.

### SUBAGENT_E — tests / E2E
Owns: `apps/financeiro-pessoal-api/src/finance/__e2e__/**`, fixtures,
`core/cognitive/tests/e2e/**`. Must not edit production source; reports defects
to the orchestrator instead of fixing them.

### SUBAGENT_F — frontend minimal
Owns: `apps/financeiro-pessoal-web/**`. No global redesign; functional surfaces only.

### Route ownership inside `routes/finance.ts`
This file is the one true collision hazard. Each agent appends its own
`registerX` function in a separate module and the orchestrator wires it:

- `financeClarificationRoutes.ts` — B
- `financeCorrectionRoutes.ts` — A
- `financeStatementRoutes.ts` — D
- `financeOnboardingRoutes.ts` — B

Only the orchestrator edits `routes/finance.ts` itself.

## Waves

- Wave 1 (parallel): A, C
- Wave 2 (after A integrates): B, D
- Wave 3: F, then E across the whole matrix
- Wave 4: bug sweep, homolog deploy, live E2E, docs, final report

## D10 — Homolog runtime map (verified live, 2026-08-31)

Resolves the open `LIVE_READY` risk. Inspected read-only on host `Prosperfy`
(`will@177.7.50.182`, the same host F2A validated against). Nothing was
restarted, deployed or mutated during this inspection.

| Component | Location | Bind |
|---|---|---|
| Finance API | `/home/will/deploy-staging/p2-finance-whatsapp/apps/financeiro-pessoal-api` → `node dist/index.js` | `127.0.0.1:8787` |
| Finance Web | same tree, `apps/financeiro-pessoal-web` → vite | `127.0.0.1:5175` |
| Cognitive homolog | `/home/will/projetos/prosperfy-cognitive-gate-0.3` → uvicorn `cognitive.gateway.app:app` | `127.0.0.1:8800` |
| WhatsApp bridge | `~/.hermes/hermes-clean/scripts/whatsapp-bridge/bridge.js --mode bot` | `127.0.0.1:3000` |
| Hermes | `hermes` | `9119` / `127.0.0.1:9120` |
| Finance DB | `/home/will/data/financeiro-pessoal/financeiro-pessoal.sqlite3` | — |
| Finance DB backups | `/home/will/data/financeiro-pessoal/backups/financeiro-pessoal-<tag>-<YYYYMMDDHHMMSS>.sqlite3` | — |

`GET /api/finance/status` on `:8787` answers **401** without a token — the API
is up and fail-closed. Correct.

### Deploy method (established precedent, not invented here)

`docs/reports/DEPLOY_0b00da7_homolog.md` and `DEPLOY_227a854_homolog.md` record
the house pattern: build a staging tree under `/home/will/deploy-staging/`, then
selective `cp` into the live tree, verifying per-file md5 (`DEPLOY_HASH_MATCH`).
Backup first into `/home/will/backups/pre-<sha>/`. F2B follows the same pattern
plus a Finance SQLite backup using the existing `backups/` naming convention.

### Secret handling — already correct, do not regress

`apps/financeiro-pessoal-web/vite.config.ts` injects `FINANCE_API_TOKEN` as an
`Authorization: Bearer` header **inside the dev-server proxy**, server-side. The
token never reaches the browser. Any F2B frontend work (SUBAGENT_F) MUST keep
calling same-origin `/api/finance/*` and must never read the token client-side.
A design that needs the token in the browser is an escalation, not a workaround.

### Real limitations to carry into the final report

1. **Finance API is a bare `node dist/index.js` process, not a systemd unit.**
   No supervisor, no auto-restart, no versioned start script. Restart after an
   F2B deploy is manual and the process dies with its shell. Recorded as debt;
   it does not block `LIVE_READY` because the deploy precedent is manual anyway.
2. **`hermes-gateway.service` restart is outside authorization** (per
   `DEPLOY_227a854_homolog.md`): it is the WhatsApp runtime, not a homolog unit.
   F2A already hit this — its 4 tracks had `WHATSAPP_E2E` blocked for exactly
   this reason. F2B's WhatsApp-channel ACL E2E inherits that ceiling: the ACL
   is testable through the Cognitive gateway on `:8800` and through the Finance
   API directly, but the last hop through the live WhatsApp gateway needs an
   owner-authorized restart. **Do not fake PASS.** Report it as owner-blocked
   with this cause.
3. `hermes-live-bridge.service` was observed in `activating (auto-restart)` —
   i.e. flapping. Pre-existing, outside F2B scope, noted so it is not
   misattributed to F2B later.

## D11 — Vitest reporta suíte verde com testes que nunca rodaram

Sintoma: `npm test` retornava `success=true` enquanto 16 testes de rota (incluindo os de
autenticação) apareciam como *pending*. O worker morria antes de executar qualquer teste e o
vitest tratava isso como arquivo sem falhas.

Causa raiz: `better-sqlite3` 11.x declara suporte só até Node 23; o runtime é Node 24. O
finalizador nativo de `Statement` roda depois que o environment já foi destruído e aborta o
processo (`node::RemoveEnvironmentCleanupHook`, `Assertion failed: (env) != nullptr`).
Reproduzível fora do vitest, em `node` puro — não era problema de pool nem do código de teste.

Correção: upgrade para `better-sqlite3` ^12 (declara `24.x`). Verificado em execuções repetidas:
169/169 testes executam, zero pendentes, nos pools `threads` e `forks`.

**Consequência para o deploy (altera D10):** `better-sqlite3` é módulo nativo. O método de deploy
por `cp` seletivo de arquivos JS **não é suficiente** para esta mudança — o homolog precisa de
`npm install` (ou `npm rebuild better-sqlite3`) na árvore de staging para reconstruir o binding
contra o Node que roda lá.

Versões do homolog verificadas ao vivo em 2026-08-31: Node `v22.23.1` (binário em
`/home/will/.hermes/node/bin/node`, fora do PATH do shell não-interativo — invocar por caminho
absoluto) e `better-sqlite3` 11.10.0 na árvore de staging. Portanto o crash de Node 24 **nunca
atingiu o homolog**; era específico da máquina de desenvolvimento. O v12 declara `22.x`, então o
upgrade é compatível com o homolog — mas continua exigindo `npm install` lá para reconstruir o
binário nativo.

**Regra operacional derivada:** nunca aceitar `success=true` do vitest como prova. Conferir
sempre `numTotalTests`, `numPassedTests` e `numPendingTests` — um arquivo cujo worker morreu
aparece como sucesso.
