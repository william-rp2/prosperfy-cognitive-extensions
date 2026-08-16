# SESSION HANDOFF

> **Operacional — mutável.** Atualizar ao pausar, trocar agente ou esgotar contexto.  
> **Não é ADR.** Evidência real (Git, testes, DB) prevalece sobre este arquivo.

---

## Metadata

| Campo | Valor |
|-------|-------|
| **Updated At** | 2026-08-16T23:16 BRT |
| **Agent/Tool** | Antigravity (Gemini) |
| **Execution Mode** | `PHASE_SCOPED` |
| **Requested Scope** | Fase 0 / Sprint 0.1 |

---

## Current Position

| Campo | Valor |
|-------|-------|
| **Phase** | 0 — Foundation |
| **Subphase** | 0.1 — Core in-memory |
| **Status** | `PASS` |

---

## Last Safe Checkpoint

| Campo | Valor |
|-------|-------|
| **Git Commit** | `cb22ffe` |
| **Git Branch** | `master` |
| **Checkpoint Type** | subphase |

---

## Completed

- ✅ Sprint 0 documental (ADRs V2-001 a V2-008)
- ✅ Sprint 0.1 — Core in-memory
  - Gateway FastAPI independente do Hermes
  - Contratos V2 (capability, tenancy, policy, audit, gateway)
  - PolicyEngine ALLOW/CONFIRM/DENY com cross-tenant guard
  - CapabilityRegistry YAML + grants in-memory
  - infra.inspect.yaml (capability spike)
  - ExecutionOrchestrator (ordem inviolável AUTH→TENANT→CAPABILITY→GRANT→POLICY→ADAPTER)
  - MockSkillsAdapter (CI sem MCP real)
  - ProsperfySkillsAdapter real (httpx async — corrige bug sync do legado)
  - AuditWriter in-memory com isolamento cross-tenant
  - AuditRedaction (secrets redigidos antes de audit)
  - TelemetryRecorder in-memory
  - **45 testes passando** (unit + integration + security)
  - **10 gate tests PASS**

---

## In Progress

*(nenhum)*

---

## Not Started

- Phase 0.2 — Persistence + tenancy (Postgres local + migrations)
- Phase 0.3 — ProsperfySkill real opt-in + observabilidade
- Phase 0.4 — Auth/service identities
- Phase 0.5 — Hardening
- Phases 1–6 — conforme `41-MASTER-IMPLEMENTATION-PLAN.md`

---

## Blocked

*(nenhum)*

---

## Files Changed (Sprint 0.1)

- `core/cognitive/pyproject.toml` — pacote Python
- `core/cognitive/cognitive/contracts/` — 5 módulos de contratos
- `core/cognitive/cognitive/gateway/` — FastAPI app + deps + routes
- `core/cognitive/cognitive/tenancy/context.py`
- `core/cognitive/cognitive/registry/` — registry + loader + infra.inspect.yaml
- `core/cognitive/cognitive/policy/engine.py`
- `core/cognitive/cognitive/execution/orchestrator.py`
- `core/cognitive/cognitive/adapters/prosperfy_skills/` — mock + client real
- `core/cognitive/cognitive/audit/` — writer + redaction
- `core/cognitive/cognitive/telemetry/recorder.py`
- `core/cognitive/tests/` — 45 testes (unit + integration + security)

---

## Migrations

| Campo | Valor |
|-------|-------|
| **Created** | Nenhuma (Sprint 0.1 é in-memory) |
| **Applied** | — |
| **Pending** | 000_foundation_tenancy.sql, 001_capability_registry_audit.sql (Sprint 0.2) |
| **Rollback status** | N/A |

---

## Database State

| Campo | Valor |
|-------|-------|
| **Environment** | — (sem DB no Sprint 0.1) |
| **Changes** | Nenhuma |
| **Verification** | — |

---

## Tests

| Campo | Valor |
|-------|-------|
| **Passed** | 45 |
| **Failed** | 0 |
| **Not Run** | — |

---

## External Systems

| Sistema | Touched? | Notes |
|---------|----------|-------|
| Hermes | No | Bit-identical ao commit `7d2b2d3` |
| ProsperfySkill | No | MockSkillsAdapter usado em CI |
| Supabase | No | — |
| Finance | No | Bit-identical (dirty files pré-existentes em apps/) |
| VPS | No | — |

---

## Decisions Made This Session

- Estrutura do pacote: `core/cognitive/cognitive/` (flat layout com setuptools)
- Adapter: MockSkillsAdapter default; `COGNITIVE_LIVE_MCP=1` para real
- Credenciais: estáticas in-memory via `COGNITIVE_GATEWAY_CREDENTIAL` (Sprint 0.4: service_identities)
- Pacote Python: setuptools (não hatchling) — compatibilidade com Python 3.13

---

## Decision Gates Pending

- DG-001 RLS — antes de 0.2 production-ready (**próximo bloqueante**)
- DG-002 Secret store — antes de credenciais multi-tenant reais
- *(ver `44-DECISION-GATES.md`)*

---

## Known Risks

- `asyncio.get_event_loop()` nos testes cross-tenant com Python 3.13 (DeprecationWarning) — corrigir em próxima iteração dos testes
- Dois pipelines paralelos (CI Hermes legado + Core V2) até migração explícita

---

## Known Errors

*(nenhum)*

---

## Important Commands / Evidence

```bash
# Rodar testes
cd core/cognitive && python -m pytest tests/ -v --tb=short

# Iniciar Gateway
cd core/cognitive && COGNITIVE_GATEWAY_CREDENTIAL=dev-secret \
  COGNITIVE_DEV_TENANT_ID=prosperfy \
  COGNITIVE_DEV_ACTOR_ID=william \
  uvicorn cognitive.gateway.app:app --port 8800 --reload

# Commit safe checkpoint
# cb22ffe feat: Sprint 0.1 — Cognitive Core in-memory
```

---

## Exact Next Action

1. **Aguardar aprovação humana** para Sprint 0.2 (Persistence + Tenancy).
2. Antes de iniciar 0.2: resolver **DG-001** (mecanismo RLS — Postgres local Docker Compose ou testcontainers-only).
3. Sprint 0.2 criará migrations SQL em `core/migrations/` — **nunca aplicar no Supabase prod**.


---

## Metadata

| Campo | Valor |
|-------|-------|
| **Updated At** | — |
| **Agent/Tool** | — |
| **Execution Mode** | `PHASE_SCOPED` \| `CONTINUOUS` \| `RESUME` |
| **Requested Scope** | — |

---

## Current Position

| Campo | Valor |
|-------|-------|
| **Phase** | — |
| **Subphase** | — |
| **Status** | `NOT_STARTED` \| `IN_PROGRESS` \| `PASS` \| `BLOCKED` \| `FAILED` |

---

## Last Safe Checkpoint

| Campo | Valor |
|-------|-------|
| **Git Commit** | — |
| **Git Branch** | — |
| **Checkpoint Type** | subphase \| migration \| deploy \| pause \| agent-change \| context-exhaustion |

---

## Completed

- *(nenhum — implementação V2 ainda não iniciada)*

---

## In Progress

- *(nenhum)*

---

## Not Started

- Phase 0 (0.1–0.5) — aguardando aprovação pós-Sprint 0 documental
- Phases 1–6 — conforme `41-MASTER-IMPLEMENTATION-PLAN.md`

---

## Blocked

- *(nenhum)*

---

## Files Changed

- *(nenhum desde template inicial)*

---

## Migrations

| Campo | Valor |
|-------|-------|
| **Created** | — |
| **Applied** | — |
| **Pending** | — |
| **Rollback status** | — |

---

## Database State

| Campo | Valor |
|-------|-------|
| **Environment** | — |
| **Changes** | — |
| **Verification** | — |

---

## Tests

| Campo | Valor |
|-------|-------|
| **Passed** | — |
| **Failed** | — |
| **Not Run** | — |

---

## External Systems

| Sistema | Touched? | Notes |
|---------|----------|-------|
| Hermes | No | — |
| ProsperfySkill | No | — |
| Supabase | No | — |
| Finance | No | — |
| VPS | No | — |

---

## Decisions Made This Session

- *(nenhum)*

---

## Decision Gates Pending

- DG-001 RLS — antes de 0.2 production-ready
- DG-002 Secret store — antes de credenciais multi-tenant reais
- *(ver `44-DECISION-GATES.md`)*

---

## Known Risks

- *(nenhum registrado)*

---

## Known Errors

- *(nenhum)*

---

## Important Commands / Evidence

*(Registrar somente comandos/referências úteis. NUNCA secrets.)*

---

## Exact Next Action

1. Aguardar revisão humana dos ADRs Sprint 0 e protocolo de execução (`47-EXECUTION-PROTOCOL-REVIEW.md`).

---

## Resume Verification Required

- [ ] Ler `43-MASTER-DEV-PROMPT.md` e instrução de escopo do usuário
- [ ] Verificar Git status vs claims acima
- [ ] Confirmar nenhuma implementação iniciada sem aprovação explícita
