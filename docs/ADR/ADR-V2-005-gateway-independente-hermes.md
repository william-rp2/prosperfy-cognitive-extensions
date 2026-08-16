# ADR-V2-005 — Gateway Independente do Hermes

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Relacionado:** `02-ARQUITETURA-ALVO.md`, `11-PLANO-DE-INICIO.md`, `ADR-V2-002`, `ADR-V2-003`

---

## Context

Hoje Capability Intelligence roda como **plugin Hermes** (`hermes/capability-intelligence/plugin/__init__.py`). Comando `/capability run` **não** executa `Pipeline.run()` — apenas ecoa intent. Cognitive **depende** do runtime Hermes — invertido em relação à V2 (R7, R15).

Plano Fase 0 aprovado: **Python + FastAPI** para `core/cognitive`.

## Problem

Sem Gateway independente:

- Hermes carrega tool surface e contexto excessivos;
- não há API estável multi-cliente;
- tenancy/audit não centralizam;
- Finance, bots e workers não compartilham mesmo Core.

## Decision

### Arquitetura congelada

```text
Clients                    Cognitive Gateway              Core
────────                   ─────────────────              ────
Hermes (futuro)     ──┐
Finance App (futuro)├──→  FastAPI REST /v1      ──→  Registry
Customer Bot        │         │                      Policy
WhatsApp adapters   │         │                      Resource Resolver
Workers             │         │                      Orchestrator
Agify / outros      ──┘         │                      Audit / Telemetry
                                ▼
                         ProsperfySkills Adapter
                                ▼
                         ProsperfySkill MCP
```

**Gateway:** Python + FastAPI em `core/cognitive/` (implementação Sprint 0.1+). Sprint 0: **somente contrato congelado neste ADR**.

### Clientes (congelado)

Gateway serve **múltiplos clientes** — Hermes é **um** cliente, não identidade do Gateway.

| Cliente | Fase |
|---------|------|
| Dev CLI / test harness | Sprint 0.1 spike |
| Hermes | Pós-Foundation |
| Finance App | Fase 4+ |
| Customer Bot / WhatsApp | Fase 5+ |
| Workers internos | Fase 3+ |

### Superfície API estável (congelado)

Interfaces V2 mapeadas:

| Interface | Endpoint (conceitual) | Sprint |
|-----------|----------------------|--------|
| `status.get` | `GET /v1/status` | 0.1 |
| `capability.execute` | `POST /v1/capabilities/{id}/execute` | 0.1 |
| `capability.describe` | `GET /v1/capabilities/{id}` | 0.1 |
| `data.query` | stub 501 | Fase 1 |
| `task.manage` | stub 501 | Fase 1 |
| `workflow.execute` | stub 501 | Fase 3 |
| `knowledge.search` | stub 501 | Fase 2 |

Contrato REST **independente** do Hermes; MCP interno opcional depois.

### Request / Response (congelado)

**Headers:**

```text
Authorization: Bearer <credential>
X-Tenant-Id: <tenant_id>
X-Actor-Id: <actor_id>
X-Correlation-Id: <optional>
```

**Body (`capability.execute`):**

```json
{
  "params": {},
  "idempotency_key": "optional-string"
}
```

**Response (sucesso ou pending):**

```json
{
  "execution_id": "uuid",
  "correlation_id": "string",
  "status": "completed | pending_confirmation | failed",
  "data": {},
  "audit_id": "uuid"
}
```

| Campo | Propósito |
|-------|-----------|
| `execution_id` | Uma execução concreta (retries, compostas, async) |
| `correlation_id` | Agrupa operações relacionadas |
| `audit_id` | Registro append-only de auditoria |

### Autenticação (congelado — evoluível)

Fase 0.1: credential service-to-service simples (`Authorization: Bearer`).

**Não modelar** como "token do Hermes". Modelo conceitual:

```text
Cognitive Client
  → Credential (API key / futuro JWT / mTLS)
  → Service Identity
  → Tenant + Actor permitidos
```

Variável de ambiente **provisória** (Sprint 0.1+): `COGNITIVE_GATEWAY_CREDENTIAL` ou similar — **não** `HERMES_TOKEN`. Múltiplas credentials por client futuramente.

Headers `X-Tenant-Id` / `X-Actor-Id` permanecem mesmo se JWT passar a derivá-los.

### Capability Registry — source of truth (congelado)

**Definição da capability:** código/YAML versionado no repositório.

```text
core/cognitive/registry/capabilities/infra.inspect.yaml
```

**Banco guarda (operacional, não autoritativo para definição):**

- grants, bundles, tenant overrides;
- runtime config;
- executions, audit, telemetry, idempotency;
- projeções/cache **derivadas** se necessário — nunca concorrentes ao YAML.

Campos conceituais por capability (contrato ADR):

`id`, `version`, `domain`, `description`, `input_schema`, `output_schema`, `adapter`, `required_scopes`, `default_policy`, `idempotency_behavior`, `timeout`, `retry_policy`, `cost_class`, `tenant_support`, `audit_rules`, `redaction_rules`

Nem todos implementados Sprint 0.1; contrato congelado agora.

### Vertical slice `infra.inspect` (congelado)

Input:

```json
{ "resource": "prosperfy-main" }
```

Proibido input com host/IP arbitrário (**ADR-V2-002**).

### Ambiente de desenvolvimento (congelado)

- **Docker Compose** para Postgres local.
- **testcontainers** quando útil em CI.
- **Nenhuma** migration aplicada Supabase prod nesta fase.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| Gateway dentro do Hermes | Viola R7/R15; acoplamento |
| Node/Fastify Gateway | Perde reuso Python CI |
| Definição capability só no banco | Duas fontes de verdade |
| tenant/actor no body | Rejeitado na revisão |

## Consequences

**Positivas:**

- API vendável; Hermes vira cliente fino.
- Registry versionado em Git (reviewable).

**Negativas:**

- Dois entry points temporários (plugin + Gateway) até migração Hermes.

## Security Impact

Gateway é trust boundary: valida credential, tenant, actor, grants antes de qualquer adapter.

## Multi-Tenant Impact

Todo request valida tenant/actor; sem match → 401/403.

## Cost/Token Impact

Superfície `capability.describe` curta vs 186 MCP schemas — redução de tokens Hermes futuro.

## Migration Impact

- Hermes plugin: **intocado** Sprint 0.
- `12-FASE-0-PLANO-TECNICO.md` atualizado para refletir decisões revisadas.

## Compatibility

Reuso CI: `models.py`, `executor.py`, `resolver.py`, `policy_engine.py` — port Sprint 0.1.

## Open Questions

1. OpenAPI publicado em repo ou gerado — Sprint 0.1.
2. Versionamento URL `/v1` vs capability `version` field.
3. Rate limiting por tenant no Gateway — **DECISÃO HUMANA NECESSÁRIA**.

## Acceptance Criteria

- [x] FastAPI + Python congelado.
- [x] Gateway independente Hermes.
- [x] Contrato headers/body/response congelado.
- [x] YAML source of truth para definitions.
- [x] execution_id no response.
- [x] Docker Compose + testcontainers congelado.
- [ ] Implementação FastAPI — Sprint 0.1.
