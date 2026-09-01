# F2B — Homolog Deploy Manifest

> **Executor de host only.** Cursor prepara; não deploya, não reinicia serviços, não toca Production.

## A. SOURCE_SHA esperado

```text
BRANCH=dev/finance-v2-f2b
SOURCE_SHA=b719bf14780acf05a4fae91607d93bff67516628
FUNCTIONAL_CODE_SHA=21bccff2788cd354452d3c1ef664dcbc3e3f7a34
CANONICAL_MASTER=f4f491c745c970766274f0f37abfdb3874bc1222  (must remain untouched)
```

- `FUNCTIONAL_CODE_SHA` — último commit de código funcional F2B (pré-docs).
- `SOURCE_SHA` — tip com documentação Bloco 4 alinhada (runtime idêntico ao functional SHA).
- Tip docs-only posterior na mesma branch também é válido se incluir ambos como ancestors.

Verificar após checkout:

```bash
git rev-parse HEAD
git merge-base --is-ancestor 21bccff2788cd354452d3c1ef664dcbc3e3f7a34 HEAD
git merge-base --is-ancestor b719bf14780acf05a4fae91607d93bff67516628 HEAD
# both ancestor checks must exit 0
# HEAD may equal SOURCE_SHA or a later docs-only tip on this branch
```

---

## B. Arquivos / diretórios para o runtime homolog

### Finance API

```text
apps/financeiro-pessoal-api/dist/
apps/financeiro-pessoal-api/package.json
apps/financeiro-pessoal-api/package-lock.json
apps/financeiro-pessoal-api/node_modules/   # rebuild on host — see D
```

Código-fonte espelhado (se o host compila localmente):

```text
apps/financeiro-pessoal-api/src/
```

### Finance Web (se UI mudou)

```text
apps/financeiro-pessoal-web/dist/          # production build
apps/financeiro-pessoal-web/package.json
apps/financeiro-pessoal-web/package-lock.json
apps/financeiro-pessoal-web/node_modules/
```

### Cognitive homolog (se ACL/adapter/orchestrator mudou)

```text
core/cognitive/cognitive/
core/cognitive/tests/                      # optional — validation only
```

Paths operacionais conhecidos (host):

| Componente | Path típico |
|---|---|
| Finance API | `/home/will/deploy-staging/p2-finance-whatsapp/apps/financeiro-pessoal-api` |
| Finance Web | `/home/will/deploy-staging/p2-finance-whatsapp/apps/financeiro-pessoal-web` |
| Cognitive | `/home/will/projetos/prosperfy-cognitive-gate-0.3` |
| Finance DB | `/home/will/data/financeiro-pessoal/financeiro-pessoal.sqlite3` |

### Hermes (somente se integração mudou — restart **não autorizado** neste estágio)

```text
hermes/capability-intelligence/src/capability_intelligence/
hermes/p2-finance-whatsapp/
```

---

## C. Novas dependências npm

Finance API (verificar `package.json` no SHA):

- `pdfjs-dist` — extração de texto PDF in-memory
- `better-sqlite3` — **módulo nativo**: `npm install` / `npm rebuild better-sqlite3` obrigatório no host após upgrade

Finance Web: sem dependência F2B crítica além das já existentes.

---

## D. Migrations — ordem e gate

Migrations aplicadas **automaticamente** no startup da Finance API via `openFinanceDb()` → `runMigrations()`.

| # | Arquivo | Em master (F2A)? | Adicionada F2B? |
|---|---|---|---|
| 001 | `001_init.sql` | YES | NO |
| 002 | `002_manual_categories_budgets.sql` | YES | NO |
| 003 | `003_enrichment_clarifications.sql` | YES | NO |
| 004 | `004_financial_asset_types.sql` | YES | NO |
| 005 | `005_financial_account_preferences.sql` | YES | NO |
| 006 | `006_annotations_responsible.sql` | YES | NO |
| 007 | `007_transaction_account_currency.sql` | YES | NO |
| 008 | `008_statement_cycles.sql` | NO | YES |
| 009 | `009_transaction_temporal.sql` | NO | YES |
| 010 | `010_financial_corrections.sql` | NO | YES |
| 011 | `011_merchant_rules.sql` | NO | YES |
| 012 | `012_clarification_delivery.sql` | NO | YES |
| 013 | `013_onboarding_state.sql` | NO | YES |
| 014 | `014_statement_imports.sql` | NO | YES (**emendada in-place**) |

### Migration 014 — gate obrigatório **ANTES** de copiar/aplicar

**Path:** `apps/financeiro-pessoal-api/src/finance/migrations/014_statement_imports.sql`

**Purpose:** camada de evidência F2B — imports de extrato fechado, linhas parseadas, links de reconciliação e discrepâncias.

**Premissa:** 014 **nunca** foi aplicada em homolog que receberá este deploy.

**Query READ-ONLY em homolog (primeiro passo do executor):**

```sql
SELECT name, applied_at
FROM schema_migrations
WHERE name = '014_statement_imports.sql';
```

| Resultado | Ação |
|---|---|
| **0 rows** | `MIGRATION_014_ALREADY_APPLIED=NO` → deploy pode continuar |
| **1 row** | `DEPLOY_BLOCKED=YES` — **STOP** |

Se `MIGRATION_014_ALREADY_APPLIED=YES`:

```text
REASON=amended migration 014 already applied on target
CODE_ACTION_REQUIRED=new migration 015 in separate CODE stage
```

Não reaplicar. Não editar banco manualmente. Nenhum deploy parcial.

**Backup SQLite obrigatório** antes do primeiro startup pós-deploy:

```text
/home/will/data/financeiro-pessoal/backups/financeiro-pessoal-<tag>-<timestamp>.sqlite3
```

---

## E. Environment variables (nomes only — nunca valores)

### Finance API

```text
HOST
PORT
CORS_ORIGIN
FINANCE_DB_PATH
FINANCE_API_TOKEN
PLUGGY_CLIENT_ID
PLUGGY_CLIENT_SECRET
PLUGGY_WEBHOOK_SECRET
PLUGGY_WEBHOOK_HEADER
PLUGGY_ALLOW_UNSIGNED_WEBHOOKS
PLUGGY_CLIENT_USER_ID
PLUGGY_ENV
PLUGGY_STORE_PATH
PUBLIC_BASE_URL
PLUGGY_SYNC_ENABLED
PLUGGY_SYNC_INTERVAL_MINUTES
PLUGGY_SYNC_INTERVAL_HOURS
PLUGGY_SYNC_SAFETY_WINDOW_HOURS
PLUGGY_SYNC_MAX_CONCURRENT_ITEMS
PLUGGY_SYNC_STALE_LOCK_MINUTES
FINANCE_REPROCESS_ALLOW          # CLI reprocess em production only
```

### Finance Web (proxy server-side)

```text
FINANCE_API_TOKEN                # injetado pelo Vite proxy — NUNCA no browser
VITE_FINANCE_DEMO_MODE           # optional
VITE_FINANCE_ADMIN_POC           # optional
```

### Cognitive homolog (Finance ACL + adapter)

```text
FINANCE_API_BASE_URL
FINANCE_API_TOKEN
FINANCE_OWNER_ACTOR_IDS
FINANCE_GROUP_CHAT_IDS
FINANCE_OWNER_DIRECT_CHAT_IDS
FINANCE_ACTOR_BINDINGS
COGNITIVE_GATEWAY_CREDENTIAL
COGNITIVE_MODE
COGNITIVE_DB_URL
COGNITIVE_DB_WORKER_URL
COGNITIVE_DB_ADMIN_URL
COGNITIVE_DEV_TENANT_ID
COGNITIVE_DEV_ACTOR_ID
COGNITIVE_TENANT_ID
COGNITIVE_TENANT_SLUG
COGNITIVE_CORS_ORIGINS
COGNITIVE_ENV
COGNITIVE_API_VERSION
COGNITIVE_LIVE_MCP
MCP_PROSPERFYSKILLS_API_KEY
MCP_PROSPERFYSKILLS_HOST
COGNITIVE_BROWSER_WORKER_HOST
COGNITIVE_TRELLO_POLL_ENABLED
COGNITIVE_TRELLO_POLL_INTERVAL_SECONDS
COGNITIVE_RESOURCE_KEY
COGNITIVE_LOG_LEVEL
COGNITIVE_LOG_REDACT_FIELDS
```

### Hermes → Cognitive (se bridge ativo)

```text
COGNITIVE_GATEWAY_URL
COGNITIVE_GATEWAY_CREDENTIAL
COGNITIVE_TENANT_ID
COGNITIVE_ACTOR_ID
COGNITIVE_CORRELATION_ID
```

---

## F. Serviços — restart autorizado

| Serviço | Restart? | Notas |
|---|---|---|
| **Finance API** | **YES** | Manual: `node dist/index.js` — sem systemd conhecido |
| **Finance Web** | YES (se frontend mudou) | Vite/preview `:5175` |
| **Cognitive homolog API** | YES (se cognitive mudou) | `prosperfy-cognitive-homolog-api.service` uvicorn `:8800` |
| **Hermes gateway** | **NO** | Owner-only; ver seção G |
| **WhatsApp bridge** | **NO** | Neste estágio |
| **Production** | **NO** | Proibido |

Após `better-sqlite3` upgrade: `npm install && npm rebuild better-sqlite3` no host Finance API.

---

## G. Hermes / WhatsApp boundary

```text
hermes-gateway.service restart = NOT AUTHORIZED at this stage
```

Deploy executor pode validar tudo **até** o último hop WhatsApp.

Se código Hermes precisar restart para ficar live:

```text
HERMES_LIVE_RESTART_REQUIRED=YES
WHATSAPP_LAST_HOP=BLOCKED_BY_RESTART_AUTH
```

Não declarar `WhatsApp PASS` sem evidência runtime pós-restart autorizado.

Cognitive ACL E2E testável em `:8800` sem restart Hermes.

---

## H. Smoke tests pós-deploy

1. `GET /health` — Finance API 200
2. `GET /api/finance/summary` — Bearer válido → 200
3. `POST /api/finance/sync` — cycleAssignment ativo → `purchase_month` / `competence_month` / `statement_cycle_id` não nulos em txs novas
4. `POST /api/finance/statements/import/pdf` — PDF fixture → 201, `source=PDF_UPLOAD`
5. `POST /api/finance/statements/{id}/reconcile` — reconcile determinístico
6. Cognitive `:8800` — capability `finance.*` com ACL configurada → ALLOW owner / DENY third party
7. Verificar `git rev-parse` / runtime SHA = `SOURCE_SHA`
8. `schema_migrations` contém `014_statement_imports.sql` **após** primeiro boot (se gate pré-deploy era NO)

---

## I. Rollback plan

1. Parar Finance API
2. Restaurar SQLite do backup pré-deploy
3. Restaurar `dist/` + `node_modules` do backup de artefatos (tag anterior)
4. Reiniciar Finance API na SHA anterior
5. Se Cognitive foi atualizado: restaurar tree cognitive + restart homolog API
6. **Não** force-push master
7. Preservar logs e counts before/after para forensics

Rollback triggers:

- migration corrompe counts
- ACL leak
- duplicate clarifications / statement imports
- corrected values lost after sync
- `MIGRATION_014_ALREADY_APPLIED=YES` detectado tarde demais

---

## J. Composition-root invariant (deploy-critical)

`apps/financeiro-pessoal-api/src/server.ts` **deve** injetar `cycleAssignment` em `PluggySyncService`.

Sem isso, sync real deixa colunas temporais nulas.

Regressão: `POST /api/finance/sync` via app bootado (`e2eAcceptance.test.ts`).

**Regra:** `REAL_RUNTIME_PATH > HAND-BUILT UNIT INSTANCE`.
