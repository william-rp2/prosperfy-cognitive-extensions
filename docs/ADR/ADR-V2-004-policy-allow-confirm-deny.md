# ADR-V2-004 — Policy ALLOW / CONFIRM / DENY

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Relacionado:** `01-PRINCIPIOS-E-REGRAS.md` (R11), `05-CAPABILITIES-POLICIES-MCP.md`, `10-GATES-E-CRITERIOS-DE-ACEITE.md`

---

## Context

A V2 exige classificação de capabilities como `ALLOW`, `CONFIRM` ou `DENY` (R11). Capability Intelligence usa `PolicyEngine` com `PolicyResult`: `ALLOW`, `DENY`, `REQUIRE_APPROVAL` (`policy_engine.py`). Pipeline CI avalia policy **antes** do Executor em `pipeline.py` — alinhado ao princípio V2.

Porém `MCPAdapter.authorize()` retorna sempre `authorized=True` — **CONFLITO:** bypass potencial se usado como fonte de policy.

## Problem

Sem modelo policy congelado:

- efeitos externos executam sem aprovação;
- CONFIRM pode ser confundido com execução parcial;
- adapter MCP pode executar antes da policy;
- nomenclatura `REQUIRE_APPROVAL` vs `CONFIRM` fragmenta código novo e legado.

## Decision

### Modelo oficial (congelado)

| Veredito | Significado | Execução adapter |
|----------|-------------|------------------|
| **ALLOW** | Operações seguras, read-only ou idempotentes previamente autorizadas | **Permitida** após grants + resource resolution |
| **CONFIRM** | Efeito externo, risco relevante, alteração/destruição | **Proibida** até aprovação explícita |
| **DENY** | Fora de scope, proibida, sem grant | **Proibida** |

### Ordem obrigatória (congelado)

```text
Gateway
  → validate identity (tenant/actor/credential)
  → Registry lookup
  → Resource Resolver (se aplicável)
  → POLICY evaluate
  → (se ALLOW) Adapter
  → Audit + Telemetry
```

**Nunca:**

```text
Adapter → Policy
```

### CONFIRM — comportamento (congelado)

1. Policy retorna `CONFIRM`.
2. Gateway **não** invoca ProsperfySkill adapter para efeito externo.
3. Registra audit com `status: pending_confirmation`, `execution_id`, `audit_id`.
4. Cliente aprova via endpoint futuro (`POST .../executions/{execution_id}/confirm`) — **Sprint 0.3+ / Fase 3**.
5. Só após aprovação: policy reavaliada + adapter executado.

### Mapeamento CI legado → V2

| CI (`policy_engine.py`) | V2 |
|-------------------------|-----|
| `ALLOW` | `ALLOW` |
| `REQUIRE_APPROVAL` | `CONFIRM` |
| `DENY` | `DENY` |

CI legado **não alterado** no Sprint 0. Novo Core usa nomenclatura V2.

### Policy default por capability

Definida na **definição versionada** (YAML — **ADR-V2-005** seção registry): ex. `infra.inspect` → default `ALLOW` (read-only composta). Overrides por tenant via `capability_grants.policy_override` — dados operacionais, não definição.

### Bundles e least privilege (R10)

Profiles recebem bundles curtos (`owner-core`, `infra-read`, `finance`, …). Tools administrativas **não** entram em profile conversacional comum.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| Policy só no ProsperfySkill | Viola boundary; sem audit Cognitive central |
| CONFIRM executa e pede rollback | Risco irreversível |
| `authorize=True` no MCPAdapter | Placeholder inseguro; não replicar no Core |
| Policy pós-execução | Tarde demais para DENY/CONFIRM |

## Consequences

**Positivas:**

- Efeitos externos controlados.
- Gate Foundation testável.
- Alinhamento com compliance.

**Negativas:**

- UX de aprovação a implementar (CONFIRM flow).
- Duas nomenclaturas temporárias (CI vs Core).

## Security Impact

- DENY default para capabilities não grantadas.
- CONFIRM bloqueia envio/publicação/shell/destruição até humano ou workflow.
- Customer Agent: scope mínimo — **03-MULTITENANCY**.

## Multi-Tenant Impact

Policy evaluation **sempre** inclui `tenant_id`, `actor_id`, profile/grants. Cross-tenant grant = DENY.

## Cost/Token Impact

CONFIRM evita execuções caras acidentais (email send, deploy, etc.).

## Migration Impact

Nenhuma alteração em `policy_engine.py` Sprint 0. Core implementará engine equivalente Sprint 0.1+.

## Compatibility

`PolicyEngine` CI reutilizável como **referência de implementação**; ports adaptados a `ActorContext` + `RegisteredCapability`.

## Open Questions

1. Timeout de pending CONFIRM antes de expirar — **DECISÃO HUMANA NECESSÁRIA**.
2. Quem pode aprovar (mesmo actor vs admin vs workflow) — Fase 3.
3. Policy dinâmica por horário (maintenance window) — placeholders existem em CI.

## Acceptance Criteria

- [x] ALLOW/CONFIRM/DENY definidos.
- [x] Ordem Policy→Adapter congelada.
- [x] CONFIRM não executa adapter.
- [x] Mapeamento CI documentado.
- [ ] Endpoint confirm — pendente implementação.
