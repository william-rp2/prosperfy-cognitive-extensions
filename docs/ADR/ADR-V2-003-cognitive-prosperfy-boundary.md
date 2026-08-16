# ADR-V2-003 — Boundary Cognitive ↔ ProsperfySkill

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Relacionado:** `05-CAPABILITIES-POLICIES-MCP.md`, `08-MIGRACAO-E-REAPROVEITAMENTO.md`, `ADR-V2-002`, `ADR-V2-004`

---

## Context

ProsperfySkill/MCP expõe ~186 capabilities (email, VPS, mercado, NotebookLM, Supabase admin, etc.) em `skills.prosperfy.com.br/mcp`. Capability Intelligence (`hermes/capability-intelligence/`) já consome MCP via `MCPAdapter`, mas:

- acoplado ao runtime Hermes (plugin);
- `MCPAdapter.authorize()` retorna `authorized=True` sempre (placeholder);
- ports divergentes (`resolve_catalog` vs `resolve`; `get_result` vs `result`);
- catálogo MCP exposto como centenas de tools — viola R7/R8.

## Problem

Sem boundary claro:

- Cognitive duplica integrações (VPS, email, Supabase admin);
- Hermes escolhe primitives de baixo nível via LLM;
- policy pode ser bypassada se adapter executar antes da policy;
- tenancy não é enforced na execution layer.

## Decision

### Papéis congelados

```text
┌─────────────────────────────────────────────────────────┐
│ PROSPERFY COGNITIVE                                     │
│  Gateway · Tenancy · Resource Resolver · Registry       │
│  Policy (ALLOW/CONFIRM/DENY) · Orchestration · Audit      │
│  State (SQL) · RAW/RAG (fases futuras) · Workflows        │
│  DECISION · POLICY · ORCHESTRATION · STATE              │
└───────────────────────────┬─────────────────────────────┘
                            │ adapter controlado
                            ▼
┌─────────────────────────────────────────────────────────┐
│ PROSPERFYSKILL / MCP                                    │
│  Tools · Integrações · Execução externa                 │
│  EXECUTION · INTEGRATION                                │
└─────────────────────────────────────────────────────────┘
```

**ProsperfySkill:**

- executa integrações (VPS, email, notify, etc.);
- **não** decide regra de negócio do tenant;
- **não** resolve resource lógico → destino (Cognitive faz);
- **não** substitui policy/audit do Cognitive.

**Cognitive:**

- único ponto de entrada para clients (Hermes, apps, bots, workers);
- decide **se** e **como** chamar ProsperfySkill;
- compõe capabilities de negócio deterministicamente;
- registra audit/telemetry;
- **não** reimplementa primitives já maduras no ProsperfySkill.

### Regra de reutilização (R1/R8) — ordem congelada

1. Cognitive atual (Core V2)
2. ProsperfySkill/MCP
3. MCP de mercado maduro
4. API/SDK oficial
5. Adapter fino
6. Integração própria **somente se necessário**

**Proibido duplicar:** VPS, email IMAP/SMTP, Supabase admin ops, notifications, social — consumir ProsperfySkill.

### Capability composta (congelado)

A LLM **não** escolhe primitives. O Registry/Executor define sequência.

Exemplo vertical slice `infra.inspect`:

```text
infra.inspect (capability de negócio)
  → Policy ALLOW (read-only composta)
  → Resource Resolver: "prosperfy-main" → metadados tenant_resources
  → ProsperfySkillsAdapter (sequência determinística)
       → tools VPS confirmadas no catálogo ProsperfySkill*
  → Audit + Telemetry
```

\*Lista exata de tool names: **confirmar no catálogo ProsperfySkill antes do Sprint 0.1** — não inventar nomes no Sprint 0. Evidência parcial do catálogo: prefixo `prosperfy_vps_*` (panorama, containers, serviços, logs, portas, etc.).

### Adapter único

Um **ProsperfySkillsAdapter** no Core (futuro `core/cognitive/adapters/prosperfy_skills/`) será o **único** cliente MCP para execução externa no Cognitive V2. CI legado `MCPAdapter` permanece intocado até depreciação explícita.

### Ordem de execução (congelado — ver ADR-V2-004)

```text
Gateway → Registry → Resource Resolver → POLICY → Adapter → Audit
```

Nunca: `Adapter → Policy`.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| Hermes chama MCP direto (status quo) | Tool surface enorme; sem tenancy/audit central |
| Reimplementar VPS/email no Cognitive | Duplica ProsperfySkill; viola R8 |
| ProsperfySkill decide tenant policy | Mistura execution com decision |
| Múltiplos adapters MCP por domínio | Complexidade; um adapter com routing interno |

## Consequences

**Positivas:**

- Superfície curta para Hermes (capabilities de negócio).
- Reuso de ~186 tools existentes.
- Audit trail centralizado.

**Negativas:**

- Latência extra (hop Cognitive).
- Adapter deve mapear erros/timeouts/retry de forma uniforme.

## Security Impact

- Resource resolver impede execução em hosts não cadastrados (**ADR-V2-002**).
- Adapter recebe apenas parâmetros já resolvidos e autorizados.
- MCP API key via `credential_ref`, não hardcoded em prompts.

## Multi-Tenant Impact

Cada execução MCP carrega contexto tenant/actor; ProsperfySkill invocado **no contexto** resolvido pelo Cognitive (resource + credential do tenant). Detalhes de credential por tenant — **ADR-V2-006**.

## Cost/Token Impact

Capabilities compostas reduzem tool schema exposto ao Hermes. Orquestração determinística evita LLM escolhendo N tools.

## Migration Impact

- Plugin Hermes `/capability`: **intocado** Sprint 0; futuro cliente do Gateway.
- `MCPAdapter` bugs documentados; correção só no novo adapter (Sprint 0.1+).

## Compatibility

Reaproveitar **conceitos** de CI (`PolicyEngine`, `Executor`, `Resolver`, `ContextEnvelope`, `ToolGate`, dedup) no Core — sem acoplamento obrigatório ao runtime Hermes (**08-MIGRACAO**).

## Open Questions

1. ProsperfySkill suporta tenant context nativo ou só via params resolvidos? — **Investigar Sprint 0.1**.
2. Rate limits MCP por tenant — **DECISÃO HUMANA NECESSÁRIA**.
3. Capabilities composta async (long-running) — execution_id + polling (**ADR-V2-005**).

## Acceptance Criteria

- [x] Papéis Cognitive vs ProsperfySkill explícitos.
- [x] Regra anti-duplicação documentada.
- [x] Resource resolution antes do adapter.
- [x] Composição determinística congelada.
- [ ] Lista exata tools `infra.inspect` — pendente Sprint 0.1.
