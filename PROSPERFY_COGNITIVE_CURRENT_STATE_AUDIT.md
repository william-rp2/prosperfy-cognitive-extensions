# PROSPERFY COGNITIVE — Current State Audit

**Data:** 2026-08-16  
**Repositório auditado:** `prosperfy-cognitive-extensions`  
**Escopo:** descoberta / inventário / diagnóstico apenas (nenhuma alteração de código, banco, secrets ou deploy)  
**Método:** evidência em código, migrations, configs e catálogo MCP externo; documentação usada apenas como hipótese e marcada quando não confirmada

---

## 1. Executive Summary

Este repositório **não é** uma plataforma Prosperfy Cognitive completa (RAW → RAG → Tasks → multi-tenant). É o repositório oficial de **extensões cognitivas**, com dois núcleos reais:

| Núcleo | Stack | Estado |
|--------|-------|--------|
| **Capability Intelligence** (`hermes/capability-intelligence/`) | Python 3.11+, plugin Hermes | Pipeline unitário bem testado (~247 testes documentados); **integração MCP/produção incompleta** |
| **Financeiro Pessoal** (`apps/financeiro-pessoal-*`) | Fastify + React/Vite + Pluggy + SQLite | API de sync Pluggy **operacional em código**; UI principal ainda **protótipo com seed fictício** |

### Vereditos-chave

| Tema | Estado |
|------|--------|
| RAW / chunks / embeddings / RAG | **AUSENTE** neste repo |
| Cognitive Register (events/entities/tasks) | **SOMENTE MODELO + mocks** |
| Tasks / Projects / Kanban | **AUSENTE** (só menções/heurísticas) |
| Finance | **PARCIAL** (backend sync real + UI seed + enrichment DDL sem writer) |
| Collectors (WhatsApp/e-mail/docs) | **AUSENTE** como collectors; canais só em modelo/seed |
| Email / Infra monitor | **Consumir ProsperfySkill/MCP** (186 capabilities externas confirmadas) — **não reimplementar** |
| Proposal Engine | **AUSENTE** (`GapProposal` ≠ proposta comercial) |
| Multi-tenancy | **EMBRIONÁRIO** (`tenant_id` no envelope; sem RLS/schema) |
| LLM calls neste repo | **Nenhuma** confirmada |
| Dependência Hermes | **Cognitive Extension depende do runtime Hermes** (plugin); inverso desejado ainda não materializado |

### Aviso de escopo

Documentação (`README.md`, ADR-001) descreve `core/` futuro e memória em Supabase/Obsidian. No disco: **`core/` não existe**, **não há pasta `supabase/`**, **não há migrations Postgres**, **não há Docker/CI**. Sistemas citados fora do tree devem ser tratados como **NÃO CONFIRMADO neste repositório**.

---

## 2. Repository Map

### 2.1 Estrutura real (confirmada)

```
prosperfy-cognitive-extensions/
├── apps/
│   ├── financeiro-pessoal-api/     # Fastify + Pluggy + SQLite
│   └── financeiro-pessoal-web/     # React/Vite UI + POC Pluggy
├── hermes/
│   └── capability-intelligence/    # Extensão Python + plugin Hermes
├── docs/                           # ADR, Architecture, Developer, reports
├── examples/                       # só README
├── scripts/                        # install/sync/uninstall/validate plugin
├── .claude/launch.json
├── README.md
└── .gitignore
```

**Ausente no disco (citado no README):** `core/`, `packages/`, `services/`, `.github/`, Docker.

### 2.2 Stack

| Camada | Tecnologia | Evidência |
|--------|------------|-----------|
| Linguagens | TypeScript, Python 3.11+, SQL (SQLite), Bash | `package.json`, `pyproject.toml`, `*.sql`, `scripts/*.sh` |
| API | Fastify 5, Zod, dotenv, better-sqlite3, pluggy-sdk | `apps/financeiro-pessoal-api/package.json` |
| Web | React 19, Vite 6, Tailwind 4, Radix Slot, lucide-react, pluggy-js / react-pluggy-connect | `apps/financeiro-pessoal-web/package.json` |
| Hermes extension | stdlib Python (`http.client`); deps runtime vazias | `hermes/.../pyproject.toml` (`dependencies = []`) |
| Testes | Vitest (API), pytest + pytest-asyncio (Hermes) | configs e pastas `tests/` |
| Banco | SQLite local | `finance/db.ts`, `FINANCE_DB_PATH` |
| Cache / filas | Nenhum Redis/Bull/Celery | busca negativa |
| Embeddings / vector DB | Nenhum | busca negativa |
| Observabilidade | logs Fastify + logging Python; sem Sentry/Datadog/Prometheus | — |
| Deploy / Docker / CI | Ausentes | sem Dockerfile, compose, workflows |

### 2.3 APIs / endpoints (financeiro)

| Método | Path | Função | Auth |
|--------|------|--------|------|
| GET | `/health` | healthcheck | público |
| GET | `/api/pluggy/config-status` | status config + contagens store | público |
| POST | `/api/connect-token` | Connect Token Pluggy | público (segredos no server) |
| POST | `/api/pluggy/items` | registra `itemId` | público |
| GET | `/api/pluggy/snapshot` | snapshot Pluggy mascarado | público |
| GET | `/api/pluggy/poc-state` | estado POC JSON | público |
| GET/POST/OPTIONS | `/api/webhooks/pluggy` | webhook (secundário) | header secret |
| GET | `/api/finance/status` | status sync | público |
| GET | `/api/finance/accounts` | contas | público |
| GET | `/api/finance/transactions` | extrato filtrado | público |
| GET | `/api/finance/summary` | resumo mês | público |
| GET | `/api/finance/sync/status` | runs | público |
| POST | `/api/finance/sync` | sync manual | Bearer `FINANCE_API_TOKEN` |

Evidência: `apps/financeiro-pessoal-api/src/server.ts`, `routes/finance.ts`.

### 2.4 Workers / cron / jobs

| Componente | Path | Tipo |
|------------|------|------|
| `PluggySyncScheduler` | `finance/scheduler.ts` | `setInterval` in-process |
| `PluggySyncService.syncAll` | `finance/pluggySyncService.ts` | sync polling |
| Lock `financial_sync_runs` | `syncRunsRepository.ts` | unique partial index `running` |
| Dedup / turn locks | `hermes/.../deduplication.py` | in-memory |
| Feedback / gaps | `feedback_store.py`, `gap_proposal.py` | in-memory |

### 2.5 Variáveis de ambiente (nomes apenas)

#### `apps/financeiro-pessoal-api` (`config.ts` + `.env.example`)

| Variável | Uso |
|----------|-----|
| `HOST`, `PORT` | bind HTTP |
| `CORS_ORIGIN` | CORS frontend |
| `PLUGGY_CLIENT_ID`, `PLUGGY_CLIENT_SECRET` | SDK Pluggy |
| `PLUGGY_WEBHOOK_SECRET`, `PLUGGY_WEBHOOK_HEADER`, `PLUGGY_ALLOW_UNSIGNED_WEBHOOKS` | webhook |
| `PLUGGY_CLIENT_USER_ID`, `PLUGGY_ENV` | identidade / ambiente Pluggy |
| `PLUGGY_STORE_PATH` | JSON store legado |
| `PUBLIC_BASE_URL` | URL pública (webhook) |
| `FINANCE_DB_PATH` | SQLite |
| `FINANCE_API_TOKEN` | Bearer sync manual |
| `PLUGGY_SYNC_ENABLED`, `PLUGGY_SYNC_INTERVAL_HOURS` | cron |
| `PLUGGY_SYNC_SAFETY_WINDOW_HOURS` | janela incremental |
| `PLUGGY_SYNC_MAX_CONCURRENT_ITEMS` | paralelismo |
| `PLUGGY_SYNC_STALE_LOCK_MINUTES` | liberação de lock morto |

#### Hermes / MCP

| Variável | Uso |
|----------|-----|
| `MCP_PROSPERFYSKILLS_API_KEY` | Bearer MCP em `plugin/__init__.py` → `MCPAdapter` |
| `MCP_API_KEY` / `PROSPERFY_API_KEY` | apenas testes (`test_fase_i.py`) |

Frontend: **sem** `VITE_*` no código; proxy Vite `/api` → `127.0.0.1:8787`.

### 2.6 Autenticação

| Mecanismo | Onde | Notas |
|-----------|------|-------|
| PBKDF2 + AES-GCM localStorage | `financeiro-pessoal-web/src/lib/auth.ts` | sem IdP |
| Bearer `FINANCE_API_TOKEN` | `routes/finance.ts` | só POST sync |
| Webhook secret Pluggy | `server.ts` | comparação timing-safe |
| MCP Bearer | `mcp_adapter.py` | API key Skills |
| PolicyEngine | Hermes pipeline | ambiente/aprovação; authorize MCP é placeholder `authorized=True` |

**Não encontrado:** OAuth/OIDC, JWT app, Supabase Auth, RLS.

### 2.7 Testes / docs

- Hermes: suíte ampla (`tests/test_fase_*.py`, etc.); relatório `docs/reports/relatorio-consolidado.md` (247 testes em 2026-07-25).
- API: `server.test.ts`, `pluggySyncService.test.ts`, `retry.test.ts`, `syncRunsRepository.test.ts`.
- Docs: ADR-001, Architecture, reports por fase; `apps/.../docs/pluggy-personal-integration.md`.

---

## 3. Current Architecture

### 3.1 Diagrama ASCII — COMO EXISTE HOJE

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     FORA DESTE REPOSITÓRIO                               │
│  Hermes Agent runtime (~/.hermes/)  │  Prosperfy Skills MCP              │
│  Obsidian Vault (docs ADR)          │  skills.prosperfy.com.br/mcp       │
│  Supabase "Cognitive Register"      │  (~186 capabilities: email, VPS…)  │
│  (referenciado; SEM migrations aqui)│                                    │
└───────────────┬─────────────────────┴───────────────────┬────────────────┘
                │ plugin install                          │ HTTPS JSON-RPC/SSE
                ▼                                         ▼
┌───────────────────────────────┐           ┌─────────────────────────────┐
│ hermes/capability-intelligence│           │ MCPAdapter                  │
│ plugin: /capability           │──────────▶│ (resolve_catalog/execute…)  │
│ Pipeline (Resolver→…→Feedback)│           │ ⚠ nomes ≠ CatalogPort/Exec  │
│ FeedbackStore / GapStore RAM  │           └─────────────────────────────┘
│ ContextEnvelope / ToolGate    │
│ FollowUpService (SQL string)  │──(esperado)──▶ follow_ups no Supabase
│ Interpreter + CognitiveRegister Protocol (sem client real)
└───────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ apps/financeiro-pessoal-web (Vite :5175)                                 │
│  Login local │ UI seed fictícia │ /poc/pluggy (Connect Widget)           │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ fetch /api/*
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ apps/financeiro-pessoal-api (Fastify :8787)                              │
│  Connect Token │ Items │ Snapshot │ Webhooks (opcional)                  │
│  PluggySyncScheduler ──▶ PluggySyncService ──▶ Repositories              │
│  JsonPocStore (JSON)     + SQLite (financial_*)                          │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ pluggy-sdk
                                ▼
                         ┌──────────────┐
                         │ Pluggy API   │
                         │ Meu Pluggy   │
                         └──────────────┘
```

### 3.2 Observação crítica de integração Hermes↔MCP

- `CatalogPort` exige `resolve()` (`resolver.py`).
- `MCPAdapter` implementa `resolve_catalog()` (`mcp_adapter.py`).
- `ExecutionPort` exige `result()` / `status()` (`executor.py`).
- `MCPAdapter` implementa `get_result()` / `get_status()`.
- Plugin monta `Pipeline` com `MCPAdapter`, mas `/capability run` **não chama** `Pipeline.run()` — apenas ecoa intent/domínio (`plugin/__init__.py` linhas ~141–145).

**Conclusão:** pipeline está maduro em testes com mocks; caminho plugin→MCP real está **quebrado/ incompleto** por contrato + comando slash.

---

## 4. Database

### 4.1 Inventário CONFIRMADO (SQLite)

Fonte: `apps/financeiro-pessoal-api/src/finance/migrations/001_init.sql` + bootstrap `schema_migrations` em `finance/db.ts`.

Engine: **SQLite** (`better-sqlite3`). Sem schemas Postgres. Sem RLS. Sem `tenant_id`.

#### `schema_migrations`

| Campo | Notas |
|-------|-------|
| `name` PK, `applied_at` | controle de migrations |

#### `financial_items`

| Aspecto | Detalhe |
|---------|---------|
| Finalidade | Conexão Pluggy (Item) |
| Campos | `pluggy_item_id` UNIQUE, connector, status, timestamps, `raw_metadata` |
| FKs | raiz |
| Tenant/RLS | não |
| Escrita | `itemsRepository.ts`, `server.ts` POST items |
| Leitura | sync + `/api/finance/status` |
| Uso | **ativo** |

#### `financial_accounts`

| Aspecto | Detalhe |
|---------|---------|
| Finalidade | Contas bancárias/cartão |
| Campos | saldos/limites em cents, `raw_data`, `number_masked` |
| FK | `pluggy_item_id` → `financial_items` |
| Index | `ix_financial_accounts_item` |
| Escrita | sync (`accountsRepository`) |
| Uso | **ativo** |

#### `financial_transactions`

| Aspecto | Detalhe |
|---------|---------|
| Finalidade | Extrato bruto Pluggy |
| Campos | amount cents, date, category/merchant original, soft-delete `deleted_at`, `raw_data` |
| FK | → `financial_accounts` |
| Indexes | account+date, date |
| Uso | **ativo** |

#### `financial_transaction_enrichment`

| Aspecto | Detalhe |
|---------|---------|
| Finalidade | classificação interna (categoria, tags, project, responsible…) |
| FK | → `financial_transactions` |
| Escrita TS | **não encontrada** (só DDL) |
| Uso | **schema pronto / writer ausente** |

#### `financial_credit_card_bills` / `financial_investments`

| Aspecto | Detalhe |
|---------|---------|
| Finalidade | faturas CC / investimentos |
| Escrita | `productsRepository.ts` via sync |
| Uso | **ativo no sync** (exposição HTTP dedicada limitada — summary/status usam accounts/tx) |

#### `financial_sync_runs`

| Aspecto | Detalhe |
|---------|---------|
| Finalidade | auditoria + lock de sync |
| Indexes | unique parcial `running` por provider; `started_at` |
| Uso | **ativo** |

### 4.2 Diagrama FK

```
financial_items
  ← financial_accounts
      ← financial_transactions
          ← financial_transaction_enrichment
      ← financial_credit_card_bills
  ← financial_investments
financial_sync_runs (isolada)
```

### 4.3 Persistência não-SQL

| Store | Path | Estado |
|-------|------|--------|
| JSON POC | `store.ts` + `PLUGGY_STORE_PATH` | items/webhooks legado |
| FeedbackStore | `feedback_store.py` | RAM |
| GapProposalStore | `gap_proposal.py` | RAM |
| DeduplicationStore | `deduplication.py` | RAM (doc: Redis/Supabase futuro) |
| UI seed | `finance-seed.ts` | fictício |

### 4.4 Conceitos buscados — status

| Conceito | Status |
|----------|--------|
| conversations / raw_messages / raw_items / message_attachments / message_chunks | **AUSENTE** |
| embeddings / entity_mentions / knowledge / memories | **AUSENTE** (memória = mock Cognitive Register) |
| tasks / projects / kanban | **AUSENTE** como tabelas; `create_task` só Protocol/mock; `project` = coluna enrichment |
| users / contacts / clients / tenants | **AUSENTE** (campos envelope / clientUserId Pluggy) |
| follow_ups | **NÃO CONFIRMADO** DDL — SQL em `follow_up_service.py` espera tabela externa |
| events / entities / artifacts | Protocol + mocks — **NÃO CONFIRMADO** no banco |
| email / meetings / documents / workflows | **AUSENTE** como schema |
| financial_* | **CONFIRMADO** |

---

## 5. RAW Pipeline

Pipeline desejado: `SOURCE → RAW → CLASSIFY/ENRICH → KNOWLEDGE / DATA / EVENT`

| Etapa | Existe? | Implementada? | Quem executa? | Onde armazena? |
|-------|---------|---------------|---------------|----------------|
| SOURCE collectors | Não (genérico) | — | — | — |
| RAW messages/items | Não | — | — | — |
| Processamento/classify | Parcial só financeiro enrichment DDL | Writer **ausente** | — | tabela enrichment vazia de código |
| Chunks | Não | — | — | — |
| Embeddings | Não | — | — | — |
| Entities | Modelo Interpreter | Mock | Interpreter (testes) | dict in-memory |
| Knowledge | Não | — | — | — |
| Retrieval/RAG | Não | — | — | — |

**Financeiro raw-first (parcial):** Pluggy → `raw_data` / `raw_metadata` nas tabelas + enrichment separado (bom padrão), mas **sem pipeline cognitivo RAW geral**.

**Hermes:** `ContextEnvelope` isola contexto por mensagem (conceito de ingresso), sem persistência RAW.

---

## 6. RAG / Knowledge

| Item | Estado |
|------|--------|
| Embeddings | **AUSENTE** |
| Vector DB | **AUSENTE** |
| RAG retrieval | **AUSENTE** |
| Cognitive Register | Interface `CognitiveRegister` em `interpreter.py`; persistência real **NÃO CONFIRMADA** |
| Scorers | Heurísticos (`ContextRetrievalScorer`, Negotiator, ToolGate) — **não** embeddings |
| Duplicações vault/Supabase/arquivo | ADR cita Obsidian + Supabase; **nenhum client** no código deste repo |

**Múltiplos caminhos de “memória” hoje:**

1. FeedbackStore (Hermes-side, RAM)  
2. GapProposalStore (RAM)  
3. Cognitive Register Protocol (mock)  
4. Follow-ups SQL externo (se configurado)  
5. Seed UI financeiro (fictício)  
6. SQLite financeiro (dados reais Pluggy)

Risco futuro: duplicar “memória Hermes” vs “memória Cognitive” sem um Register único.

---

## 7. Tasks / Projects

| Capacidade desejada | Estado |
|---------------------|--------|
| Projetos | **AUSENTE** |
| Tarefas / demandas / backlog | **SOMENTE MODELO** (`create_task` Protocol + mocks) |
| Kanban / status (bloqueado, stand-by…) | **AUSENTE** (`"kanban"` só em allowlist de tools em `context_envelope.py`) |
| Prazos / responsáveis / dependências | **AUSENTE** |
| Metas | UI seed “Reservas e Metas” (**protótipo**, não domínio tasks) |
| Planejamento diário/semanal/mensal | UI seed “Visão Mensal” (**protótipo**) |

**PRONTO / PARCIAL / SOMENTE MODELO / AUSENTE → predominantemente AUSENTE + SOMENTE MODELO.**

---

## 8. Finance

### 8.1 Frontend

| Item | Evidência | Estado |
|------|-----------|--------|
| App React | `apps/financeiro-pessoal-web` | existe |
| Telas | dashboard, monthly, decisions, reserves, transactions, debts, cards, documents, integrations, settings | **seed fictício** (`finance-seed.ts`); sidebar admite “Protótipo sem dados reais” |
| POC Pluggy | `/poc/pluggy` → `PluggyPocPage.tsx` | Connect Token + widget |
| Auth | `lib/auth.ts` | local |
| Ligação API finance summary/accounts | **não confirmada** nas telas seed (API client genérico em `lib/api.ts` usado sobretudo na POC) |

### 8.2 Backend

| Item | Estado |
|------|--------|
| Pluggy Connect Token | **PRONTO** |
| Persistência items + sync polling | **PRONTO** |
| Contas / transações / summary API | **PRONTO** |
| Faturas / investimentos no sync | **PRONTO** (repositório) |
| Enrichment (categorias internas) | **SOMENTE MODELO** (DDL) |
| Orçamento | **AUSENTE** |
| Anexos/comprovantes | UI seed “Notas e Documentos” — **simulado** |
| Multi-user / permissões | **AUSENTE** (uso pessoal documentado) |
| Webhooks | Código existe; doc: **indisponível no Conector 200**; sync por polling |

Doc oficial do módulo: `apps/financeiro-pessoal-api/docs/pluggy-personal-integration.md`.

### 8.3 Estado consolidado Finance

**PARCIAL — backend de coleta Pluggy avançado para POC pessoal; produto financeiro familiar ainda protótipo visual.**

---

## 9. Collectors

| Fonte | Neste repo | Notas |
|-------|------------|-------|
| WhatsApp | Modelo/dedup/seed | `notification_channel="whatsapp"`, testes e2e; **sem API WhatsApp** |
| E-mail | Follow-up fields + MCP externo | ver §10–11 |
| Documentos / OCR | Seed UI | sem collector |
| Áudio / reuniões / transcrições | **AUSENTE** | — |
| Arquivos | **AUSENTE** (exceto VPS MCP externo) | — |
| APIs | Pluggy | collector financeiro real |
| Webhooks | Pluggy (secundário) | — |

Arquitetura `SOURCE→RAW→…`: **quase só o braço financeiro Pluggy→SQLite** existe.

---

## 10. Email

### Neste repositório (Cognitive Extensions)

| Aspecto | Estado |
|---------|--------|
| Gmail/SMTP/IMAP clients | **AUSENTE** |
| Classificação / threads / attachments storage | **AUSENTE** |
| Geração de tasks a partir de e-mail | **AUSENTE** |
| Menções | labels em follow-up; domínio communication no `Domain` enum |

### Fora do repositório — ProsperfySkill/MCP (confirmado 2026-08-16)

Catálogo MCP: **~60 tools `prosperfy_email_*`** (accounts, IMAP/SMTP, labels, batch, classify, summarize, send, sync, etc.) + `prosperfy_notify_email`.

**Classificação recomendada:** **consumir ProsperfySkill/MCP existente** — **não reimplementar** no Cognitive.

---

## 11. Infrastructure

### Neste repositório

| Aspecto | Estado |
|---------|--------|
| SSH / Docker host control | **AUSENTE** |
| Health | `GET /health` da API financeira apenas |
| CPU/disco/memória/uptime monitors | **AUSENTE** |
| `InfrastructureInterpreter` | interpreta resultados de capability domain `infrastructure` (Hermes) — **sem coleta** |

### ProsperfySkill/MCP (confirmado)

**13 tools `prosperfy_vps_*`** (containers, serviços, arquivos, logs, portas, panorama, etc.) + tools Supabase admin.

**Classificação:** **consumir MCP** — adapter fino no Cognitive, sem duplicar.

---

## 12. Proposals

| Item | Estado |
|------|--------|
| Propostas comerciais / PDF / HTML / branding / preços | **AUSENTE** |
| `GapProposal` / `GapProposalStore` | lacunas de **capabilities** (`gap_proposal.py`) — **não** Proposal Engine |
| Lead sites / imagem / copy | MCP externo (`prosperfy_lead_sites_*`, content, NotebookLM) — reutilizável como **insumos**, não como engine de proposta no Cognitive |

**Para Proposal Engine futuro:** quase tudo **criar novo** no Cognitive + **consumir MCP** para PDF/HTML/assets se já existir skill adequada (verificar capability específica — geração PDF comercial **NÃO CONFIRMADA** no catálogo amostrado).

---

## 13. Hermes Integration

| Item | Path / evidência | Dependência |
|------|------------------|-------------|
| Plugin slash `/capability` | `plugin/__init__.py` | **Cognitive depende do Hermes** (host de plugin) |
| `plugin.yaml` | `plugin/plugin.yaml` | runtime Hermes |
| Install scripts | `scripts/install-plugin.sh` etc. | copiam para `~/.hermes/plugins` |
| Pipeline CI | `pipeline.py` | independente de Hermes em testes |
| Models contrato | `models.py` (“contrato Hermes↔Skills”) | acoplamento conceitual |
| SOUL / prompts / agents / profiles Hermes | **não encontrados** neste repo | NÃO CONFIRMADO |
| Memória Hermes | FeedbackStore local | RAM |
| Cron Hermes | **não** | cron é só Pluggy na API |
| UI “Hermes” no financeiro | `App.tsx`, seed actor | cosmético |

**Direção atual:**  
`Hermes (host) → plugin Cognitive → (tentativa) MCP Skills`

**Direção desejada:**  
`Hermes → Cognitive API/MCP → dados/workflows`

Para inverter: expor Cognitive como serviço/MCP próprio e reduzir plugin a cliente fino; hoje o código **vive dentro** do ciclo de vida Hermes.

---

## 14. MCP / External Integrations

### 14.1 Cliente neste repo

`MCPAdapter` → `skills.prosperfy.com.br/mcp`  
Tools usadas no adapter: `prosperfy_list_tools`, tool dinâmica por `capability_id`, `prosperfy_hello`.

### 14.2 Catálogo Prosperfy Skills (evidência MCP 2026-08-16)

| Categoria | ~Qtd | Relevância MVP |
|-----------|------|----------------|
| email | 60 | Email Intelligence |
| notebooklm | 39 | docs/knowledge auxiliar |
| mercado | 24 | fora do MVP atual |
| sites / lead | 16 | Proposal/marketing auxiliar |
| infra / vps | 13 | Infrastructure Monitor |
| cloud / supabase | 9+ | ops DB |
| notifications | 2 | WhatsApp/email notify |
| scheduling / content / review | vários | Social Engine futuro |

**Regra de reuso:** para e-mail, VPS, notify, supabase ops → **consumir MCP**; no Cognitive criar apenas orquestração determinística + persistência multi-tenant + políticas.

### 14.3 Outras integrações

| Integração | Estado |
|------------|--------|
| Pluggy | **implementada** no app financeiro |
| WhatsApp Evolution/Twilio | **AUSENTE** (só notify MCP) |
| Composio | string allowlist tools — **NÃO CONFIRMADO** uso |

---

## 15. Multi-tenancy

| Sinal | Evidência | Avaliação |
|-------|-----------|-----------|
| `tenant_id` | `ContextEnvelope` default `""` | campo sem enforcement |
| `organization_id` / `workspace_id` | não encontrados | — |
| `user_id` | envelope + auth local web | sem tabela users |
| RLS | inexistente (SQLite) | — |
| Namespaces embeddings | N/A | — |
| Credentials por tenant | Pluggy env global; MCP key global | single-tenant implícito |
| Finance doc | “finanças pessoais do William”, sem SaaS | explícito |

**Classificação: EMBRIONÁRIO**

**Bloqueadores para vender a vários clientes:**

1. SQLite single-file sem isolamento  
2. Rotas finance majoritariamente públicas  
3. Auth local browser-only  
4. Sem schema tenant / RLS  
5. Secrets Pluggy/MCP de processo único  
6. Cognitive Register e follow_ups externos sem modelo tenant confirmado  

---

## 16. LLM Usage & Cost Risks

### 16.1 Chamadas LLM neste repositório

| Local | Função | Modelo/provider | Trigger | Contexto | Frequência | Código? | SQL? | Precisa LLM? |
|-------|--------|-----------------|---------|----------|------------|---------|------|--------------|
| — | — | — | — | — | — | — | — | — |

**Nenhuma chamada LLM/embeddings confirmada no código deste tree.**

LLM, se houver, ocorre **dentro** do Hermes Agent host ou de tools Skills remotas — **NÃO CONFIRMADO aqui**.

### 16.2 Riscos indiretos de custo

| Risco | Evidência | Nota |
|-------|-----------|------|
| Agente Hermes orquestra tudo via LLM | fora do repo | principal risco futuro |
| Pipeline CI poderia reduzir tokens | Negotiator/Policy determinísticos | bom alinhamento ao princípio Código→SQL→RAG→LLM |
| `/capability run` não executa pipeline | plugin | hoje não gasta tokens via CI; também não entrega valor |
| MCP `authorize=True` sempre | `mcp_adapter.py` | risco de execuções caras/indevidas se ligado |
| Scorers heurísticos | tool_gate, negotiator | preferir manter determinístico |

---

## 17. Duplications / Technical Debt

| Item | Detalhe |
|------|---------|
| `ProtocolAdapter` vs Ports | nomes divergentes; audit anterior já marcou ProtocolAdapter como morto/divergente |
| MCPAdapter ≠ CatalogPort/ExecutionPort | integração real quebrada |
| Plugin não chama `Pipeline.run` | comando slash incompleto |
| JSON store + SQLite | duas persistências Pluggy (legado + sync) |
| UI seed vs API real | duas “fontes da verdade” financeiras |
| FeedbackStore vs Cognitive Register vs Follow-ups | três memórias conceituais |
| README `core/` vs disco | documentação desatualizada |
| Enrichment DDL sem repository | schema órfão |
| SQL string interpolation em `FollowUpRepository` | dívida de segurança se ligado a executor real |
| `MCPAdapter` sync `HTTPSConnection` em async | bloqueia event loop |
| GapProposal vs Proposal Engine | homônimo confuso |

---

## 18. Security Risks

| Risco | Severidade | Evidência |
|-------|------------|-----------|
| Endpoints finance GET sem auth | Alta (se exposto) | `routes/finance.ts` |
| `PLUGGY_ALLOW_UNSIGNED_WEBHOOKS` | Alta se true em prod | config |
| Auth MCP authorize sempre true | Alta | `mcp_adapter.py` |
| SQL montado por f-string em follow_ups | Alta se executor real | `follow_up_service.py` |
| Secrets em `.env` local | Normal | não auditar valores; garantir gitignore |
| Auth web só no browser | Média | sem backend session |
| Snapshot Pluggy com mask parcial | Média | `maskSensitive` |
| Sem HTTPS enforcement local | Baixa em LAN | `PUBLIC_BASE_URL` só se publicado |

---

## 19. Reusable Components

| Componente | Reuso sugerido |
|------------|----------------|
| Pipeline CI (Resolver→…→Feedback) | Adaptar como orquestrador determinístico de capabilities |
| `models.py` Domain/contratos | Base para catálogo interno |
| PolicyEngine | Adaptar para multi-tenant policies |
| ContextEnvelope / ToolGate | Isolamento de contexto (base multi-tenant conversacional) |
| Deduplication / TurnLock | Adaptar com store persistente |
| Follow-up domain model | Adaptar sobre DB real multi-tenant |
| PluggySyncService + repos + migration raw-first | Reutilizar/adaptar para Finance capability |
| Finance enrichment DDL | Completar writer (não recriar schema) |
| UI financeiro (layout/nav) | Adaptar quando ligar a API real |
| ProsperfySkill email/VPS/notify/supabase | **Consumir MCP** |
| Scripts install plugin | Manter enquanto Hermes for host |

---

## 20. Missing Components (para o MVP Cognitive desejado)

- Core multi-tenant (tenants, credentials, RLS)  
- RAW store + collectors genéricos  
- Chunk/embed/RAG com provenance  
- Projects/Tasks/Kanban domain  
- Cognitive API pública (inversão Hermes)  
- Proposal Engine  
- Customer Agent domain  
- Wire UI finance → SQLite API  
- Enrichment pipeline financeiro  
- Observabilidade/CI/CD/Docker  
- Integração real MCP adapter ↔ ports  

---

## 21. MVP Gap Analysis

| # | Capability | Quanto existe | Reutilizável | Gaps | Deps | Risco | Esforço | LLM? | Predominantemente determinística? |
|---|------------|---------------|--------------|------|------|-------|---------|------|-----------------------------------|
| 1 | Collector | Só Pluggy | Sync Pluggy, envelope | WhatsApp/email/docs RAW | MCP email/notify; canais | Médio (escopo) | Alto | Não no núcleo | **Sim** |
| 2 | Projects/Tasks/Kanban | Quase zero | Protocol create_task | Domínio completo + UI + DB | Register | Alto (greenfield) | Alto | Opcional | **Sim** |
| 3 | Finance | Parcial forte backend | API+SQLite+Pluggy+UI shell | Multi-tenant, enrichment, UI live, orçamento | Pluggy | Médio | Médio | Não | **Sim** |
| 4 | Infrastructure Monitor | Interpreter stub | — | Tudo de coleta/alerta | **MCP VPS** | Baixo se MCP | Baixo–médio | Não | **Sim** |
| 5 | Proposal Engine | Ausente | MCP lead/content parcial | Engine + templates + pricing | Branding | Médio | Alto | Parcial (copy) | Mista |
| 6 | Email Intelligence | Ausente no Cognitive | **MCP email 60 tools** | Orquestração + RAW + tasks | MCP | Médio (integração) | Médio | Classificação pode usar LLM Skills | Mista (preferir MCP+SQL) |
| 7 | Customer Agent | Ausente | Follow-up model | CRM/agent loop | Tasks+email | Alto | Alto | Sim (interface) | Núcleo determinístico + LLM UI |
| 8 | Social Engine | Ausente (baixa prioridade) | MCP schedule IG/LI | — | MCP | Baixo agora | — | Sim | Futura |

---

## 22. Reuse / Adapt / Remove Matrix

| Componente | Estado | Classificação principal | Explicação |
|------------|--------|-------------------------|------------|
| Capability Intelligence pipeline | Maduro em testes | **Adaptar** | Virar orquestrador Cognitive API, não só plugin Hermes |
| MCPAdapter | Quebrado p/ ports | **Adaptar** | Alinhar `resolve`/`result`/`status`; async HTTP |
| ProtocolAdapter ABC | Divergente | **Simplificar/Remover** | Unificar com Ports |
| FeedbackStore / GapStore RAM | POC | **Adaptar** | Persistência tenant-aware |
| CognitiveRegister Protocol | Interface | **Adaptar** | Implementar no DB multi-tenant |
| FollowUpService | Código + SQL externo | **Investigar** + **Adaptar** | Confirmar tabela Supabase fora do repo; sanitizar SQL |
| Plugin Hermes | Runtime coupling | **Simplificar** | Cliente fino sobre Cognitive API |
| Finance API + SQLite | Útil | **Reutilizar** | Base Finance MVP |
| Finance enrichment table | DDL only | **Adaptar** | Completar writers |
| JsonPocStore | Legado | **Simplificar** | Migrar responsabilidades p/ SQLite |
| Finance Web seed UI | Protótipo | **Adaptar** | Ligar a `/api/finance/*` |
| Pluggy webhook path | Secundário | **Manter** | Útil se plano pago |
| ProsperfySkill email/VPS | Externo maduro | **Consumir MCP** | Não duplicar |
| README `core/` | Fiction no tree | **Investigar** | Atualizar docs ou criar depois |
| Docs Obsidian/Supabase memory | Externo | **Investigar** | Inventariar vault/DB reais fora deste repo |

---

## 23. Questions Requiring Human Decision

1. Este repo é a **fonte única** do “Prosperfy Cognitive” futuro, ou existe outro monorepo/Cognitive core a inventariar (Supabase projeto, vault Obsidian, Hermes home)?  
2. O Cognitive Register / `follow_ups` já existem em algum projeto Supabase? Qual?  
3. Hermes deve permanecer host obrigatório no curto prazo, ou priorizar **Cognitive API/MCP** imediatamente?  
4. Financeiro pessoal (William) vira módulo multi-tenant do produto ou permanece app separado?  
5. Qual provedor de embeddings/vector (se RAG entrar no MVP)?  
6. Collectors prioritários do MVP: WhatsApp, e-mail, ou só Finance+Infra primeiro?  
7. Política de secrets multi-tenant: vault próprio, Supabase Vault, ou Prosperfy Skills?  
8. Proposal Engine: gerar PDF no Cognitive ou via skill MCP/mercado?  

---

## 24. Recommended Next Analysis Steps

1. **Inventário externo obrigatório:** projeto(s) Supabase reais (schemas, RLS, `follow_ups`, register); vault Obsidian; instalação `~/.hermes` (SOUL, skills, memória).  
2. **Mapa 1:1 ProsperfySkill → MVP capabilities** (email, VPS, notify, supabase) com gaps só de orquestração.  
3. **Spike de contrato:** fazer MCPAdapter implementar Ports e um `Pipeline.run` real end-to-end (análise, ainda sem redesign amplo).  
4. **Decisão de fonte da verdade financeira:** seed UI vs SQLite API.  
5. **Threat model multi-tenant** sobre exposição atual das rotas finance.  
6. **Somente depois:** desenhar arquitetura alvo Código→SQL→RAG→LLM e backlog de implementação.

---

## Apêndice A — Evidências de arquivos principais

| Área | Paths |
|------|-------|
| Hermes pipeline | `hermes/capability-intelligence/src/capability_intelligence/{pipeline,resolver,negotiator,policy_engine,executor,interpreter}.py` |
| Plugin | `hermes/capability-intelligence/plugin/__init__.py`, `plugin.yaml` |
| MCP | `transport/adapters/mcp_adapter.py` |
| Finance API | `apps/financeiro-pessoal-api/src/{server,config,pluggy}.ts`, `routes/finance.ts`, `finance/*` |
| Migration | `apps/financeiro-pessoal-api/src/finance/migrations/001_init.sql` |
| Finance Web | `apps/financeiro-pessoal-web/src/{App.tsx,data/finance-seed.ts,components/PluggyPocPage.tsx}` |
| ADR | `docs/ADR/ADR-001-fonte-oficial-extensoes.md` |
| Audit anterior CI | `docs/reports/auditoria-tecnica-final-v1.0.md` |

## Apêndice B — O que este relatório deliberadamente NÃO faz

Não alterou código, migrations, banco, secrets, Hermes, nem implementou multi-tenancy.  
Não assume existência de tabelas só por nome em docs.  
Não recomenda reimplementar e-mail/VPS já cobertos pelo ProsperfySkill/MCP.

---

*Fim da auditoria de estado atual — 2026-08-16*
