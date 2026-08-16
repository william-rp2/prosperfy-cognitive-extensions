# ADR-V2-002 — Tenant, Actor, Resource e Isolamento

**Status:** Aprovado (Sprint 0)  
**Data:** 2026-08-16  
**Relacionado:** `03-MULTITENANCY-E-SEGURANCA.md`, `ADR-V2-003`, `ADR-V2-005`, `ADR-V2-006`

---

## Context

Multi-tenancy é requisito estrutural da V2 (R9). O código atual possui apenas `tenant_id: str = ""` em `ContextEnvelope` (`context_envelope.py`) **sem enforcement**. Finance SQLite não possui `tenant_id`. Nenhum RLS existe neste repositório.

A V2 deve suportar Prosperfy + múltiplos clientes, em modos **Shared** (isolamento lógico) e **Dedicated** (isolamento físico opcional) com o **mesmo desenho lógico**.

## Problem

Sem modelo congelado de identidade e recursos:

- clientes podem bypassar tenancy passando hosts/contas arbitrários;
- RLS pode ser implementado de forma incompatível com workers e MCP;
- `actor` e `user` são confundidos;
- duas fontes de verdade para identidade (headers vs body).

## Decision

### 1. Modelo de entidades (congelado)

```text
Tenant
  │
  ├── TenantMembers ( vínculo humano/sistema ↔ tenant )
  │     └── Actor ( identidade que executa no Cognitive )
  │
  ├── TenantResources ( recursos lógicos: vps, mailbox, supabase-project, … )
  │
  ├── TenantIntegrations ( estado de integração por tenant )
  │
  ├── CredentialRefs ( referências a secrets — nunca valor em claro )
  │
  └── CapabilityGrants ( profile/actor → capability + policy override )
```

**Definições:**

| Entidade | Significado |
|----------|-------------|
| **Tenant** | Unidade de isolamento de dados, policies, recursos e billing. Ex.: `prosperfy`, `cliente-a`. |
| **TenantMember** | Associação de um principal (user/service) ao tenant com role/profile. |
| **Actor** | Identidade **que executa** uma operação no Gateway. Pode ser humano, Hermes, bot, worker, integration. **Actor ≠ user necessariamente.** |
| **Service Identity** | Credencial/autenticação do **cliente** que chama o Gateway (Hermes, Finance App, worker…). Resolve para tenant + actor permitidos. |
| **Profile** | Bundle lógico de grants (ex.: `owner-core`, `infra-read`, `finance`). |
| **Resource** | Identificador **lógico** tenant-scoped (ex.: `prosperfy-main`). **Nunca** IP/host arbitrário do cliente. |
| **Integration** | Configuração de conexão externa (Pluggy, mailbox, VPS target) ligada a tenant + credential_ref. |
| **CredentialRef** | Ponteiro para secret store (`secret_ref`); sem valor persistido no Cognitive. |
| **CapabilityGrant** | Autorização tenant-scoped: quem pode invocar qual capability com qual policy default/override. |

### 2. Identidade na API Gateway (congelado)

**Uma única fonte de verdade por request — headers + Authorization:**

```text
Authorization: Bearer <credential>
X-Tenant-Id: <tenant_id>
X-Actor-Id: <actor_id>
X-Correlation-Id: <opcional; gerado se ausente>
```

**Body (capability.execute):**

```json
{
  "params": {},
  "idempotency_key": "..."
}
```

**Proibido:** repetir `tenant_id` / `actor_id` no body. Futuro JWT/claims pode **derivar** tenant/actor sem mudar contrato de `params`.

### 3. Resource Resolution (congelado — obrigatório)

Capabilities externas **não** recebem infraestrutura arbitrária quando isso permitir bypass de tenancy.

```text
ERRADO:  { "host": "192.168.1.100" }
CORRETO: { "resource": "prosperfy-main" }
```

Fluxo:

```text
Client params.resource
  → Gateway valida grant + tenant
  → Resource Resolver (tenant_resources + credential_refs)
  → parâmetros concretos para ProsperfySkill (host, project ref, etc.)
  → Adapter MCP
```

O **cliente** escolhe resource lógico; o **Cognitive** resolve o destino real.

### 4. Isolamento cross-tenant (requisito congelado; mecanismo aberto)

**Congelamos o requisito:**

- Nenhum dado de tenant A acessível por tenant B.
- Testes negativos cross-tenant obrigatórios antes de produção multi-cliente.
- RPC/vector search filtra tenant.
- Service role não é caminho genérico da aplicação.

**NÃO congelamos ainda** o mecanismo único de implementação RLS. Opções a avaliar na implementação (Sprint 0.2+):

| Mecanismo | Uso provável |
|-----------|--------------|
| Supabase Auth + JWT claims | Usuários humanos / apps com JWT |
| Service-to-service credential | Hermes, workers, bots |
| `SET LOCAL app.tenant_id` + RLS | Queries via pool com contexto |
| `current_setting('app.tenant_id')` | Variante Postgres; **não decisão definitiva** |
| Row filters no application layer | Complemento; não substituto de RLS em dados expostos |
| Workers com tenant explícito | Jobs assíncronos, outbox |
| Admin/migrations | Bypass controlado, auditado, fora do path conversacional |

**DECISÃO HUMANA NECESSÁRIA:** escolha final do stack RLS por ambiente (shared Supabase vs dedicated Postgres) — após spike Sprint 0.2 e inventário Supabase externo.

### 5. Modos Shared vs Dedicated

| Modo | Isolamento | Mesmo modelo lógico |
|------|------------|---------------------|
| **Shared** | RLS + namespaces + policies; DB compartilhado | Sim |
| **Dedicated** | DB/runtime/secrets dedicados por cliente | Sim (mesmas entidades e API) |

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|-------------|-------------------|
| `tenant_id` no body e headers | Duas fontes de verdade; rejeitado na revisão |
| Cliente passa host/IP direto | Bypass de tenancy e ACL |
| RLS só via application code | Insuficiente para Supabase exposto e vetores |
| Congelar `current_setting` agora | Prematuro; workers/JWT podem exigir híbrido |

## Consequences

**Positivas:**

- Modelo vendável multi-cliente.
- Resource resolver centraliza risco de infra/email/finance.
- Actor desacoplado de user humano.

**Negativas:**

- Resource catalog exige cadastro operacional por tenant.
- Implementação RLS exige spike dedicado.

## Security Impact

- Resource resolution reduz superfície de ataque (sem hosts arbitrários).
- CredentialRefs evitam secrets em DB (**ADR-V2-006**).
- Cross-tenant failure = incidente crítico; testes obrigatórios.

## Multi-Tenant Impact

**Central.** Este ADR é a base de toda Fase 0+.

## Cost/Token Impact

Neutro. Isolamento evita vazamento de contexto entre tenants em RAG futuro.

## Migration Impact

Entidades-base previstas para migrations futuras (Sprint 0.2+):

`tenants`, `tenant_members`, `tenant_resources`, `tenant_integrations`, `credential_refs`, `capability_grants`

**Sprint 0:** nenhuma migration executada. Supabase prod intocado.

## Compatibility

- `ContextEnvelope.tenant_id` (CI legado): campo compatível; CI permanece intocado.
- Finance POC: sem tenant até Fase 4 (**ADR-V2-008**).

## Open Questions

1. Mapeamento Actor ↔ Member ↔ Supabase Auth user — **DECISÃO HUMANA NECESSÁRIA**.
2. Naming convention de `resource_key` (slug global vs tenant-prefixed).
3. Dedicated: um cluster Cognitive por cliente ou só DB dedicado?

## Acceptance Criteria

- [x] Entidades Tenant/Actor/Resource/Grant definidas.
- [x] Headers-only identity congelada.
- [x] Resource resolution obrigatória documentada.
- [x] Requisito RLS congelado; mecanismo explicitamente aberto.
- [ ] Mecanismo RLS escolhido — pendente Sprint 0.2.
