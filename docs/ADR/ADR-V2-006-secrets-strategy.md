# ADR-V2-006 — Estratégia de Secrets

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Relacionado:** `01-PRINCIPIOS-E-REGRAS.md` (R14), `03-MULTITENANCY-E-SEGURANCA.md`, `ADR-V2-002`

---

## Context

Secrets hoje no repo:

| Local | Variáveis | Risco |
|-------|-----------|-------|
| Finance API `.env` | `PLUGGY_*`, `FINANCE_API_TOKEN` | OK local; não commitar |
| CI plugin | `MCP_PROSPERFYSKILLS_API_KEY` | Global processo; sem tenant |
| Gateway futuro | TBD | Deve ser multi-client |

R14: secrets fora de prompt/RAG. V2 exige `credential_refs`.

## Problem

Sem boundary de secrets:

- MCP keys globais quebram multi-tenant;
- audit/logs podem vazar tokens;
- RAG indexa credenciais;
- LLM recebe secrets em contexto.

## Decision

### Regras congeladas (R14 expandido)

Secrets **nunca**:

- entram em prompt ou contexto LLM;
- entram em RAG / embeddings;
- aparecem em `audit_events`, `execution_traces`, `cost_telemetry`;
- aparecem em responses API;
- são persistidos como texto claro em tabelas Cognitive.

**Sempre:**

- referência via `credential_refs` (`id`, `tenant_id`, `provider`, `secret_ref`, `rotated_at`);
- resolução em runtime por secret store;
- redaction em audit (**redaction_rules** por capability).

### Modelo conceitual

```text
Tenant
  └── credential_refs
        secret_ref → Secret Store (env / vault / Supabase Vault / VPS — TBD)
        provider   → pluggy | prosperfy_mcp | smtp | ...
```

Gateway credential (client auth) **≠** integration credential (ProsperfySkill, Pluggy).

```text
Client Credential          → autentica quem chama o Gateway
Integration CredentialRef  → autentica execução externa por tenant
```

### Boundary por camada

| Camada | Secrets |
|--------|---------|
| Gateway | Valida client credential; nunca loga Bearer |
| Resource Resolver | Lê `credential_ref_id` de `tenant_integrations`; não expõe valor |
| ProsperfySkills Adapter | Injeta MCP key resolvida server-side |
| Audit | Campos sensíveis substituídos por `[REDACTED]` |
| Finance POC (legado) | Permanece `.env` local; **intocado** Sprint 0 |

### Secret store definitivo

**Não congelado** neste ADR. Opções futuras:

- variáveis ambiente por deployment (dev/single-tenant);
- Supabase Vault / secrets manager;
- VPS-local env (Prosperfy infra);
- credential service dedicado.

**DECISÃO HUMANA NECESSÁRIA:** secret store produção multi-tenant — antes de Fase 4 ou primeiro cliente externo.

### Sprint 0 / 0.1 (provisório)

- Client credential: env `COGNITIVE_GATEWAY_CREDENTIALS` (formato TBD: map client_id→hash) ou single dev key — **documentar no README Core Sprint 0.1**.
- Integration MCP: env `MCP_PROSPERFYSKILLS_API_KEY` **apenas dev** até `credential_refs` populado.
- Nenhuma secret em YAML de capabilities.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| Secrets no YAML capability | Vazamento Git; viola R14 |
| MCP key única global prod | Sem isolamento tenant |
| Secrets em audit para debug | Viola R14 e compliance |
| Hermes carrega todas keys | Viola R7 |

## Consequences

**Positivas:**

- Compliance e venda multi-tenant.
- RAG seguro por design.

**Negativas:**

- Operação de rotação de secrets.
- Secret store TBD adia prod multi-tenant completo.

## Security Impact

**Alto.** Este ADR é guardrail para todo Core.

## Multi-Tenant Impact

Cada tenant integration aponta para `credential_ref` próprio ou compartilhado explicitamente (Prosperfy internal).

## Cost/Token Impact

Redaction evita vazamento acidental em logs indexados (custo indireto).

## Migration Impact

Finance `.env` intacto. CI `MCP_PROSPERFYSKILLS_API_KEY` intacto. Novo Core adota modelo ref desde Sprint 0.1.

## Compatibility

Finance `maskSensitive()` (`safe.ts`, `api.ts`) — padrão compatível para respostas; estender ao audit Core.

## Open Questions

1. Secret store produção — **DECISÃO HUMANA NECESSÁRIA**.
2. Rotação automática MCP keys por tenant.
3. Pluggy secrets: por tenant vs app-level Open Finance.

## Acceptance Criteria

- [x] Proibições R14 documentadas.
- [x] credential_refs modelo congelado.
- [x] Separação client vs integration credential.
- [ ] Secret store prod escolhido — pendente.
