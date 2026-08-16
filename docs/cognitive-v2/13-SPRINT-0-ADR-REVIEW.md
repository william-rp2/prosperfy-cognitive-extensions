# Sprint 0 — ADR Review

**Data:** 2026-08-16  
**Escopo:** documentação e congelamento arquitetural V2  
**Status:** concluído — **STOP GATE** (aguardar aprovação humana antes Sprint 0.1)

---

## Executive Summary

O Sprint 0 congelou as decisões fundamentais da **Prosperfy Cognitive V2** em **8 ADRs** (`docs/adr/ADR-V2-001` … `ADR-V2-008`), alinhados à documentação `docs/cognitive-v2/` e às revisões aprovadas do plano técnico.

**Principais decisões:**

- **Gateway:** Python + FastAPI, independente do Hermes.
- **Identidade:** `Authorization` + `X-Tenant-Id` + `X-Actor-Id` + `X-Correlation-Id` — **sem** tenant/actor no body.
- **Resource resolution:** clients passam `resource` lógico; Cognitive resolve destino real.
- **Registry:** YAML versionado = source of truth; banco = grants, audit, telemetry, estado operacional.
- **Policy:** ALLOW / CONFIRM / DENY; ordem **Policy → Adapter**; CONFIRM não executa.
- **Secrets:** `credential_refs`; nunca em prompt/RAG/audit/responses.
- **RAW / Finance / Hermes / Supabase prod:** intocados; estratégias documentadas.

**Nenhum runtime foi alterado.** Nenhuma migration executada. Hermes, Finance, VPS e Supabase prod permanecem intactos.

---

## ADRs Created

| ADR | Arquivo | Decisão central |
|-----|---------|-----------------|
| V2-001 | `docs/adr/ADR-V2-001-pipeline-raw-canonico.md` | Pipeline canônico `conversations→raw_messages→…→embeddings`; legado preservado; não implementar RAW agora |
| V2-002 | `docs/adr/ADR-V2-002-tenant-actor-resource.md` | Modelo Tenant/Actor/Resource/Grant; headers-only identity; resource resolver; RLS requisito congelado, mecanismo aberto |
| V2-003 | `docs/adr/ADR-V2-003-cognitive-prosperfy-boundary.md` | Cognitive = decision/orchestration/state; ProsperfySkill = execution; anti-duplicação; composição determinística |
| V2-004 | `docs/adr/ADR-V2-004-policy-allow-confirm-deny.md` | ALLOW/CONFIRM/DENY; Policy antes Adapter; CONFIRM sem execução; mapeamento CI `REQUIRE_APPROVAL`→CONFIRM |
| V2-005 | `docs/adr/ADR-V2-005-gateway-independente-hermes.md` | FastAPI Gateway; contrato API; execution_id; YAML registry; Docker Compose + testcontainers |
| V2-006 | `docs/adr/ADR-V2-006-secrets-strategy.md` | credential_refs; client credential ≠ integration secret; secret store prod TBD |
| V2-007 | `docs/adr/ADR-V2-007-migracao-raw-legado.md` | Migração 8 passos; legado ativo; zero execução Sprint 0 |
| V2-008 | `docs/adr/ADR-V2-008-finance-source-of-truth.md` | Finance POC intacto; conflito seed vs SQLite documentado; decisões Fase 4 abertas |

Índice: `docs/adr/README.md`

---

## Decisions Frozen

### Arquitetura e princípios

```text
CODE → SQL → RULE → RAG → LLM
```

| Papel | Responsabilidade |
|-------|------------------|
| Hermes | Interface conversacional (futuro **cliente** do Gateway) |
| Prosperfy Cognitive | Core, tenancy, policy, registry, audit, orchestration, state |
| ProsperfySkill/MCP | Integrações e execução externa |

### Gateway API (contrato v1)

**Headers:** `Authorization`, `X-Tenant-Id`, `X-Actor-Id`, `X-Correlation-Id`

**Body execute:**

```json
{ "params": {}, "idempotency_key": "..." }
```

**Response:**

```json
{
  "execution_id": "...",
  "correlation_id": "...",
  "status": "completed | pending_confirmation | failed",
  "data": {},
  "audit_id": "..."
}
```

### Vertical slice futuro (Sprint 0.1)

- Capability: `infra.inspect`
- Input: `{ "resource": "prosperfy-main" }`
- Primitives ProsperfySkill: **confirmar no catálogo antes de implementar** (prefixo `prosperfy_vps_*` evidenciado no MCP)

### Dev environment

- Python + FastAPI (`core/cognitive`)
- Docker Compose (Postgres local)
- testcontainers (CI quando útil)
- **Sem** apply Supabase prod

### Explicitamente congelado como NÃO fazer no Sprint 0

- `core/cognitive` runtime
- migrations executáveis
- Docker runtime de app (só decisão documentada)
- alterações Hermes / Finance / ProsperfySkill / VPS / Supabase prod

---

## Conflicts Found

### CONFLITO 1 — Identity duplicada (plano vs revisão)

| | |
|---|---|
| **Evidência** | `12-FASE-0-PLANO-TECNICO.md` §7.1 original listava `tenant_id`/`actor_id` no body |
| **Impacto** | Duas fontes de verdade; bugs de tenancy |
| **Recomendação** | Headers-only — **corrigido** no plano + **ADR-V2-002/005** |
| **Status** | Resolvido (documentação) |

### CONFLITO 2 — RLS `current_setting` prematuro

| | |
|---|---|
| **Evidência** | Plano §8.1 sugeria `current_setting('app.tenant_id')` como decisão |
| **Impacto** | Pode não servir JWT, workers, admin |
| **Recomendação** | Congelar **requisito** isolamento; mecanismo aberto — **ADR-V2-002** |
| **Status** | Resolvido (documentação) |

### CONFLITO 3 — Registry dual source of truth

| | |
|---|---|
| **Evidência** | Plano propunha `registered_capabilities` no banco + YAML |
| **Impacto** | Drift definição vs runtime |
| **Recomendação** | YAML autoritativo; banco operacional — **ADR-V2-005** |
| **Status** | Resolvido (documentação) |

### CONFLITO 4 — MCPAdapter bypass de policy

| | |
|---|---|
| **Evidência** | `mcp_adapter.py` L115-118: `authorize()` → `authorized=True` sempre |
| **Impacto** | Execução externa sem policy real no CI legado |
| **Recomendação** | Novo Core: Policy→Adapter; CI legado intocado — **ADR-V2-003/004** |
| **Status** | Documentado; correção só Sprint 0.1+ |

### CONFLITO 5 — MCPAdapter ports divergentes

| | |
|---|---|
| **Evidência** | `CatalogPort.resolve()` vs `MCPAdapter.resolve_catalog()`; `result()` vs `get_result()` |
| **Impacto** | Integração MCP real quebrada no plugin CI |
| **Recomendação** | Novo `ProsperfySkillsAdapter` com ports corretos — Sprint 0.1 |
| **Status** | Documentado |

### CONFLITO 6 — Finance dual truth (seed vs SQLite)

| | |
|---|---|
| **Evidência** | `App.tsx` + `finance-seed.ts` fictício; API `/api/finance/*` real não ligada às telas |
| **Impacto** | Confusão sobre fonte da verdade |
| **Recomendação** | Documentar; decidir Fase 4 — **ADR-V2-008** |
| **Status** | Documentado; **DECISÃO HUMANA NECESSÁRIA** Fase 4 |

### CONFLITO 7 — Supabase RAW referenciado mas ausente no repo

| | |
|---|---|
| **Evidência** | `00-README.md`, `follow_up_service.py` SQL; zero migrations Supabase no tree |
| **Impacto** | Plano migração depende inventário externo |
| **Recomendação** | Inventário Supabase fora do repo antes Fase 2 — **ADR-V2-007** |
| **Status** | **NÃO CONFIRMADO** no repo; pendente trabalho externo |

### CONFLITO 8 — Plugin `/capability run` não executa pipeline

| | |
|---|---|
| **Evidência** | `plugin/__init__.py` ~141-145: ecoa intent, não chama `Pipeline.run()` |
| **Impacto** | CI legado não entrega valor MCP via Hermes hoje |
| **Recomendação** | Hermes intocado Sprint 0; Gateway substitui path futuro — **ADR-V2-005** |
| **Status** | Documentado |

### CONFLITO 9 — Policy nomenclature CI vs V2

| | |
|---|---|
| **Evidência** | `policy_engine.py`: `REQUIRE_APPROVAL` vs V2 `CONFIRM` |
| **Impacto** | Fragmentação nomenclatura |
| **Recomendação** | Core usa CONFIRM; CI intocado — **ADR-V2-004** |
| **Status** | Documentado |

---

## Open Questions

### DECISÃO HUMANA NECESSÁRIA

| # | Questão | ADR / Fase |
|---|---------|------------|
| 1 | Mecanismo RLS final (JWT vs current_setting vs híbrido) | V2-002 / Sprint 0.2 |
| 2 | Secret store produção multi-tenant | V2-006 / pré-cliente externo |
| 3 | Inventário Supabase legado/canônico (tabelas, volumes, writers) | V2-007 / pré-Fase 2 |
| 4 | Finance: app separado vs módulo tenant; Postgres vs SQLite | V2-008 / Fase 4 |
| 5 | Lista exata tools `infra.inspect` | V2-003 / Sprint 0.1 |
| 6 | Rate limiting Gateway por tenant | V2-005 |
| 7 | Timeout/expiração pending CONFIRM | V2-004 / Fase 3 |
| 8 | Actor ↔ Member ↔ Supabase Auth mapping | V2-002 |
| 9 | Dedicated Cognitive: DB only vs runtime dedicado | V2-002 |
| 10 | Momento primeiro apply Supabase **staging** (pós gate Foundation) | V2-002 / 0.2 |

---

## Changes to Existing Documentation

| Arquivo | Motivo | Mudança |
|---------|--------|---------|
| `docs/cognitive-v2/12-FASE-0-PLANO-TECNICO.md` | Alinhar ao Sprint 0 aprovado | Status; identity headers-only; response `execution_id`; RLS mecanismo aberto; YAML source of truth; credential naming; Docker Compose explícito; Sprint 0 sem migrations executáveis |
| `docs/cognitive-v2/00-README.md` | Índice incompleto | Links para `12`, `13` e `docs/adr/` |

**Criados:**

- `docs/adr/ADR-V2-001` … `ADR-V2-008`
- `docs/adr/README.md`
- `docs/cognitive-v2/13-SPRINT-0-ADR-REVIEW.md` (este arquivo)

---

## Readiness for Sprint 0.1

### Pronto após aprovação humana deste review

| Item | Status |
|------|--------|
| ADRs Foundation | ✅ |
| Contrato Gateway congelado | ✅ |
| Policy model | ✅ |
| Tenancy/Resource model | ✅ |
| Boundary ProsperfySkill | ✅ |
| Secrets rules | ✅ |
| RAW/Finance/Hermes preservation | ✅ |

### Pré-requisitos antes de codar

1. **Aprovação explícita** deste review e dos 8 ADRs.
2. Branch V2 dedicada (recomendado em `11-PLANO-DE-INICIO.md`).
3. Confirmar lista tools `infra.inspect` no catálogo ProsperfySkill.
4. (Opcional) Inventário Supabase externo — não bloqueia spike com mock MCP.

### Sprint 0.1 escopo (não iniciar automaticamente)

1. Scaffold `core/cognitive/` + FastAPI
2. `ProsperfySkillsAdapter` (mock default)
3. `infra.inspect.yaml` + orchestrator
4. Dev CLI
5. Testes unitários + integration mock

---

## Confirmações de integridade (STOP GATE)

| Verificação | Resultado |
|-------------|-----------|
| Runtime `core/cognitive` criado | ❌ Não |
| FastAPI app implementada | ❌ Não |
| Migrations SQL criadas/executadas | ❌ Não |
| Docker Compose adicionado | ❌ Não |
| Hermes alterado | ❌ Não |
| Finance API/Web alterado | ❌ Não |
| Supabase prod alterado | ❌ Não |
| VPS / ProsperfySkill alterado | ❌ Não |
| Legado removido | ❌ Não |

**Sprint 0 encerrado. Aguardando revisão humana dos ADRs antes de Sprint 0.1.**
