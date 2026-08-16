# ADR-V2-008 — Finance Source of Truth e Boundary

**Status:** Aprovado (Sprint 0) — decisões irreversíveis **não** tomadas  
**Data:** 2026-08-16  
**Relacionado:** `06-MVP-FUNCIONALIDADES.md`, `12-FASE-0-PLANO-TECNICO.md`, auditoria financeira

---

## Context

### Estado atual confirmado no repositório

| Componente | Evidência | Estado |
|------------|-----------|--------|
| **Finance API** | `apps/financeiro-pessoal-api/` | Fastify 5, Pluggy SDK, SQLite |
| **Finance Web** | `apps/financeiro-pessoal-web/` | React 19, UI seed fictício + POC Pluggy |
| **SQLite schema** | `finance/migrations/001_init.sql` | `financial_items`, `accounts`, `transactions`, `enrichment`, `bills`, `investments`, `sync_runs` |
| **Sync** | `pluggySyncService.ts`, `scheduler.ts` | Polling Conector 200; cron in-process |
| **JSON store legado** | `store.ts`, `PLUGGY_STORE_PATH` | Items/webhooks POC |
| **Auth** | Web PBKDF2 local; API Bearer só `POST /sync` | Sem multi-user |
| **Multi-tenant** | Ausente | Uso pessoal William (doc `pluggy-personal-integration.md`) |
| **Enrichment DDL** | `financial_transaction_enrichment` | **Sem writer TS** |
| **Supabase finance** | `database.ts` hint `financeiro_pessoal` | **Sem client SDK** |

Doc explícita: SQLite escolhido por ausência de Supabase dedicado no momento; repositórios isolam SQL para migração futura.

### Escopo V2 Finance (futuro)

Pluggy + ingestão WhatsApp/docs + budgets + ACL familiar + consultas SQL (**06-MVP**). Fase 4 no roadmap (**07-FASES**).

## Problem

Sem boundary documentado:

- POC pessoal pode ser mistaken por produto multi-tenant;
- duas fontes (seed UI vs SQLite API) confundem "verdade";
- migração Pluggy→Cognitive tenant pode quebrar sync existente;
- decisões irreversíveis (shared DB vs app dedicado) prematuras.

## Decision

### Sprint 0 / Fase 0 — congelado

**Finance permanece 100% intacto:**

- sem alteração API, Web, Pluggy, SQLite, `.env`;
- sem migrations finance;
- sem integração Gateway;
- sem `tenant_id` em tabelas finance neste sprint.

### Estado documentado (não decisão final)

```text
HOJE (POC pessoal William)
  Frontend seed fictício  ──► UX/protótipo
  POC Pluggy (/poc/pluggy) ──► Connect + API real
  SQLite financial_*       ──► sync Pluggy (fonte operacional do POC backend)
  JSON store               ──► legado auditoria webhook/items
```

**CONFLITO documentado:**

| Fonte | Uso | Verdade operacional |
|-------|-----|---------------------|
| `finance-seed.ts` | Telas principais App.tsx | **Fictício** — sidebar declara "Protótipo sem dados reais" |
| SQLite API | `/api/finance/*` | **Real** para sync Pluggy — **não ligado** às telas seed |

**Recomendação Sprint 0:** tratar SQLite sync como verdade do **backend POC**; seed como **UX only** até Fase 4.

### Direção V2 (congelada como intent, não implementação)

```text
FUTURO (Fase 4)
  Cognitive multi-tenant
    → Finance capability (SQL)
    → tenant-scoped Pluggy integrations (credential_refs)
    → ACL familiar
    → budgets / enrichment writers
    → possível Postgres/Supabase (não decidido)
```

### Boundary Cognitive ↔ Finance (congelado)

| Camada | Responsabilidade futura |
|--------|------------------------|
| **Cognitive** | tenancy, policy, ACL, orchestration, audit, queries agregadas multi-tenant |
| **Finance module** | domínio Pluggy, ledger, categorization, budgets — **adaptar** apps existentes |
| **ProsperfySkill** | **não** duplicar Open Finance se API própria bastar; notify/email via MCP se necessário |

Finance **não** vive dentro do Hermes. App web pode chamar **Gateway** futuramente, não plugin.

### RAW-first finance (compatível)

Tabelas `raw_data` / `raw_metadata` + `financial_transaction_enrichment` separado — **alinhado** a R5. Completar enrichment writer na Fase 4, não Sprint 0.

### Decisões **NÃO** tomadas (requer validação humana antes Fase 4)

| # | Questão |
|---|---------|
| 1 | Finance POC William permanece app separado vs módulo tenant `prosperfy` |
| 2 | Postgres Supabase vs SQLite vs híbrido dedicated |
| 3 | Frontend: evoluir `financeiro-pessoal-web` vs novo app |
| 4 | Pluggy `client_user_id` por tenant vs global app |
| 5 | WhatsApp ingestão finance: collector RAW vs entrada direta SQL |
| 6 | Momento de desativar JSON store legado |

Marcar todas: **DECISÃO HUMANA NECESSÁRIA** antes Fase 4.

## Alternatives Considered

| Alternativa | Motivo de adiar |
|-------------|-----------------|
| Migrar Finance para Supabase Sprint 0 | Escopo proibido; Supabase intocado |
| Unificar seed→API agora | Escopo Fase 4; Finance intocado |
| Finance como só ProsperfySkill | Domínio rico demais; app existente reutilizável |
| Descartar SQLite POC | Perde sync Pluggy funcional |

## Consequences

**Positivas:**

- POC continua operável para William.
- Fase 0 focada em Foundation sem risco finance.

**Negativas:**

- Dual UX (seed vs real) persiste até Fase 4.
- Enrichment schema órfão persiste.

## Security Impact

Rotas GET finance sem auth documentadas como risco (**auditoria**); **não corrigir** Sprint 0. Correção via Gateway/tenant Fase 4.

## Multi-Tenant Impact

Finance atual single-tenant implícito. V2 exige ACL familiar (**03-MULTITENANCY**) — Fase 4.

## Cost/Token Impact

Consultas saldo/orçamento devem ser SQL sem LLM (**06-MVP**) — Fase 4.

## Migration Impact

Nenhuma neste sprint. Fase 4: adaptar repositórios existentes (`itemsRepository`, etc.) — **reutilizar**, não reescrever (**08-MIGRACAO**).

## Compatibility

- `apps/financeiro-pessoal-api/docs/pluggy-personal-integration.md` permanece referência POC.
- Gateway stub não roteia finance até Fase 4.

## Open Questions

Todas listadas em "Decisões NÃO tomadas" — **DECISÃO HUMANA NECESSÁRIA** antes Fase 4.

## Acceptance Criteria

- [x] Finance intocado Sprint 0.
- [x] Estado atual documentado com evidências.
- [x] CONFLITO seed vs SQLite registrado.
- [x] Decisões Fase 4 explicitamente abertas.
- [ ] Decisões Fase 4 respondidas — pendente humano.
