# Fase 0 --- Foundation --- Especificação Completa

**Status:** especificação pré-implementação\
**Objetivo:** materializar o Prosperfy Cognitive Core independente do
Hermes.

## 1. Resultado esperado

Ao final da Fase 0 deve existir um Core determinístico capaz de receber
uma requisição autenticada, resolver Tenant/Actor/Resource, localizar
uma capability, aplicar policy, executar via adapter, registrar
audit/telemetry e retornar resposta estruturada.

``` text
Client
  -> Cognitive Gateway
  -> RequestContext
  -> Tenant / Actor
  -> ResourceResolver
  -> CapabilityRegistry
  -> PolicyEngine
  -> Executor
  -> Adapter
  -> Audit + Telemetry
```

## 2. Stack

-   Python
-   FastAPI
-   Pydantic
-   PostgreSQL/Supabase
-   YAML versionado para definição de capabilities
-   pytest
-   Docker Compose em desenvolvimento
-   testcontainers quando útil

Não introduzir framework de agentes, Redis, Kafka, Celery, LangChain ou
vector framework sem necessidade comprovada.

## 3. Subfases

### 0.1 --- Core in-memory

Implementar Gateway, contracts, context, registry YAML, resource
resolver local, ALLOW/CONFIRM/DENY, executor, mock adapter,
audit/telemetry in-memory e `infra.inspect` mock.

**Obrigatório:** LLM=0, RAG=0, Supabase=0, MCP real=0.

### 0.2 --- Persistence + tenancy

Adicionar Postgres, schema Foundation, tenancy, resources, integrations,
grants, executions, audit e telemetry. Definir e implementar mecanismo
de isolamento após ADR/decision gate.

### 0.3 --- ProsperfySkill real

Trocar mock pelo adapter real para capabilities explicitamente
permitidas. Primeiro vertical slice: `infra.inspect` sobre resource
lógico.

### 0.4 --- Auth/service identities

Evoluir API key inicial para clients/credentials/actors sem acoplar
identidade ao Hermes.

### 0.5 --- Hardening

Timeout, retry controlado, idempotência persistente, redaction, error
taxonomy, health/readiness, quotas iniciais e testes de segurança.

## 4. Entidades Foundation

-   tenants
-   tenant_members
-   actors
-   service_identities
-   tenant_resources
-   tenant_integrations
-   credential_refs
-   capability_grants
-   capability_executions
-   audit_events
-   telemetry_events
-   idempotency_records

Definitions de capability permanecem em código/YAML; banco não é source
of truth concorrente.

## 5. Contrato de execução

Headers: - `Authorization` - `X-Tenant-Id` - `X-Actor-Id` -
`X-Correlation-Id`

Body:

``` json
{
  "params": {},
  "idempotency_key": "optional"
}
```

Resposta:

``` json
{
  "execution_id": "...",
  "correlation_id": "...",
  "status": "completed",
  "data": {},
  "audit_id": "..."
}
```

## 6. Ordem inviolável

``` text
AUTH
 -> TENANT/ACTOR
 -> RESOURCE
 -> CAPABILITY
 -> GRANT
 -> POLICY
 -> EXECUTOR
 -> ADAPTER
```

Adapter nunca executa antes da policy.

## 7. Gate

-   tenant/actor obrigatórios;
-   resource lógico obrigatório quando aplicável;
-   cross-tenant negativo;
-   ALLOW executa;
-   CONFIRM não executa;
-   DENY não executa;
-   audit e telemetry;
-   secrets redigidos;
-   adapter é único boundary externo;
-   idempotência testada;
-   zero dependência do runtime Hermes.
