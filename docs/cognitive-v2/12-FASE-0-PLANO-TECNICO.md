# Fase 0 — Plano Técnico (Foundation)

**Status:** aprovado com ajustes (Sprint 0 congelado)  
**Data:** 2026-08-16  
**Base:** `docs/cognitive-v2/*`, `PROSPERFY_COGNITIVE_CURRENT_STATE_AUDIT.md`, `docs/adr/ADR-V2-*`  
**Restrições desta fase:** não alterar Hermes/VPS/Supabase prod; não executar migrations em Supabase; não remover legado

> **Nota:** decisões revisadas e congeladas nos ADRs V2. Este plano foi alinhado ao Sprint 0; divergências anteriores (identity no body, RLS `current_setting`, registry no banco) foram corrigidas abaixo.

---

## 1. Objetivo da Fase 0

Criar a **fundação do Prosperfy Cognitive Core** independente do Hermes, com boundary claro para ProsperfySkill/MCP, tenancy/actor/policy/audit obrigatórios antes de qualquer capability externa.

**Vertical slice de validação (spike):**

```text
dev client (curl/CLI/test harness)
  → Cognitive Gateway
  → tenant + actor validation
  → capability `infra.inspect` (composta)
  → Policy ALLOW
  → ProsperfySkill adapter
  → audit + telemetry
  → resposta estruturada
```

**Gate Foundation** (`10-GATES-E-CRITERIOS-DE-ACEITE.md`):

- [ ] tenant/actor obrigatório em toda execução externa
- [ ] testes cross-tenant negativos passando
- [ ] policy ALLOW / CONFIRM / DENY operacional
- [ ] audit trail completo (inputs redigidos)
- [ ] ProsperfySkill chamado somente via adapter
- [ ] nenhum secret em logs/prompts
- [ ] telemetry de custo/latência ativa

---

## 2. Análise código atual × arquitetura V2

### 2.1 O que já alinha

| V2 | Evidência no repo |
|----|-------------------|
| Princípio CODE→SQL→RAG→LLM | Pipeline CI determinístico; Finance sync sem LLM |
| Policy antes de execução | `policy_engine.py` |
| Contratos capability | `models.py` (IntentQuery, CatalogMatch, Authorization*, Execution*) |
| Isolamento de contexto | `context_envelope.py` (base para ActorContext) |
| Idempotência/dedup | `deduplication.py` |
| RAW-first financeiro | `financial_*` + `raw_data` + `financial_transaction_enrichment` separado |
| ProsperfySkill como execution | `mcp_adapter.py` (conceito correto, implementação incompleta) |
| Não duplicar integrações | 186 capabilities MCP externas (email, VPS, etc.) |

### 2.2 O que conflita ou falta

| Problema | Evidência | Ação Fase 0 |
|----------|-----------|-------------|
| Cognitive acoplado ao Hermes | `hermes/capability-intelligence/plugin/` | Criar Core novo; **não tocar plugin** |
| MCPAdapter ≠ Ports | `resolve_catalog` vs `resolve`; `get_result` vs `result` | Corrigir no **novo adapter** em `core/` |
| `/capability run` não executa pipeline | `plugin/__init__.py` | Fora do escopo Fase 0 (Hermes intocado) |
| Sem Gateway/API Cognitive | — | **Criar** `core/cognitive-service` |
| Sem tenancy/RLS no repo | SQLite finance sem `tenant_id` | **Criar** migrations SQL versionadas (não aplicar Supabase) |
| Memória fragmentada | FeedbackStore/GapStore RAM, Register mock | **Criar** audit persistente; demais migram depois |
| RAW canônico ausente no repo | Doc V2 cita Supabase externo | Fase 0: **estratégia + contratos**; ingestão na Fase 2 |

---

## 3. O que será REUTILIZADO

| Componente | Origem | Destino proposto | Notas |
|------------|--------|------------------|-------|
| Contratos públicos capability | `hermes/.../models.py` | `core/cognitive/contracts/capability.py` | Extrair tipos estáveis; manter original intacto |
| PolicyEngine + verdicts | `policy_engine.py` | `core/cognitive/policy/` | Mapear `REQUIRE_APPROVAL` → `CONFIRM` |
| Executor (ports) | `executor.py` | `core/cognitive/execution/executor.py` | Agnóstico de domínio |
| Resolver pattern | `resolver.py` | `core/cognitive/registry/resolver.py` | Resolver consulta **Registry local**, não MCP direto |
| Deduplication model | `deduplication.py` | `core/cognitive/shared/dedup.py` | RAM na Fase 0; persistência Fase 2/3 |
| ContextEnvelope campos | `context_envelope.py` | `core/cognitive/tenancy/actor_context.py` | `tenant_id`, `user_id`, `correlation_id` obrigatórios |
| ToolGate heurístico | `tool_gate.py` | `core/cognitive/policy/tool_surface.py` | Reduzir surface exposta ao cliente |
| Testes CI (~247) | `hermes/.../tests/` | Referência; novos testes em `core/cognitive/tests/` | Não mover testes Hermes |
| Finance Pluggy sync | `apps/financeiro-pessoal-api/src/finance/*` | **Intocado** Fase 0 | ADR de fronteira apenas |
| Scripts plugin Hermes | `scripts/*.sh` | **Intocados** | |

---

## 4. O que será ADAPTADO

| Item | De → Para | Mudança |
|------|-----------|---------|
| Pipeline CI | `pipeline.py` (6 etapas Hermes-centric) | `ExecutionOrchestrator` no Gateway: auth context → registry → policy → adapter → audit |
| MCPAdapter | `mcp_adapter.py` | `ProsperfySkillsAdapter` implementando ports unificados + `httpx` async |
| Policy enum | `PolicyResult.REQUIRE_APPROVAL` | Alias/documentação `CONFIRM` (V2 nomenclatura) |
| Capability discovery | substring score em MCP | Registry declarativo + `prosperfy_discover_capabilities` sob demanda |
| GapProposal | lacunas de capability | **Não** entra Fase 0; manter no CI legado |
| Interpreter | CognitiveRegister mock | Substituído por `AuditWriter` + `TelemetryRecorder` na Fase 0 |
| FollowUpService | SQL string Supabase | **Não portar** Fase 0; contrato `workflow.execute` stub |

### Capability composta `infra.inspect` (spike)

Mapeamento determinístico (sem LLM escolhendo primitives):

```text
infra.inspect
  → prosperfy_vps_panorama
  → prosperfy_vps_listar_containers
  → prosperfy_vps_status_servico (por serviço configurado)
  → prosperfy_vps_verificar_portas
```

Definido em YAML/JSON no Registry; adapter executa sequência com timeout/retry.

---

## 5. O que será CRIADO

### 5.1 Serviços e módulos

| Módulo | Responsabilidade |
|--------|------------------|
| **Cognitive Gateway** | HTTP API: auth inicial, tenant/actor, routing, correlation id |
| **Tenancy Service** | Resolução tenant/member/profile; validação de grants |
| **Actor Context** | Imutável por request; propagação para policy/audit/adapter |
| **Capability Registry** | Catálogo de capabilities de negócio (id, schema, adapter, policy default, cost class) |
| **Policy Layer** | ALLOW/CONFIRM/DENY + bundles (`owner-core`, `infra-read`, …) |
| **Execution Orchestrator** | Orquestra registry → policy → adapter → audit |
| **ProsperfySkills Adapter** | Único ponto MCP externo |
| **Audit Service** | Persistência append-only de execuções |
| **Telemetry Service** | Métricas por request (route, latency, tool calls, cost estimate) |
| **Dev CLI / test client** | Substituto do Hermes no spike |
| **ADRs Fase 0** | 8 decisões do `11-PLANO-DE-INICIO.md` |

### 5.2 O que explicitamente NÃO entra na Fase 0

- Projects/Tasks CRUD (Fase 1)
- Collector/RAW/RAG ingestão (Fase 2)
- Workflow scheduler durável (Fase 3)
- Alterações Finance API/Web (Fase 4)
- Email/Customer/Proposal (Fase 5)
- Aplicação de migrations no Supabase prod
- Alteração do plugin Hermes

---

## 6. Estrutura de diretórios proposta

```text
prosperfy-cognitive-extensions/
├── core/
│   └── cognitive/
│       ├── README.md
│       ├── pyproject.toml              # pacote Python independente
│       ├── contracts/
│       │   ├── gateway.py              # request/response estáveis
│       │   ├── capability.py           # ports + DTOs (de models.py)
│       │   ├── tenancy.py              # TenantContext, ActorContext
│       │   ├── policy.py               # PolicyDecision, CapabilityGrant
│       │   └── audit.py                # AuditEvent, ExecutionTrace
│       ├── gateway/
│       │   ├── app.py                  # FastAPI
│       │   ├── routes/
│       │   │   ├── health.py
│       │   │   ├── status.py           # status.get
│       │   │   └── capability.py       # capability.execute
│       │   └── middleware/
│       │       ├── tenant_actor.py
│       │       └── correlation.py
│       ├── tenancy/
│       │   ├── context.py
│       │   ├── grants.py
│       │   └── repository.py           # interface + impl local/test
│       ├── registry/
│       │   ├── registry.py
│       │   ├── loader.py               # YAML/JSON capabilities
│       │   └── capabilities/
│       │       └── infra.inspect.yaml
│       ├── policy/
│       │   ├── engine.py               # adaptado de policy_engine.py
│       │   ├── bundles.py
│       │   └── rules/
│       ├── execution/
│       │   ├── orchestrator.py
│       │   └── executor.py
│       ├── adapters/
│       │   └── prosperfy_skills/
│       │       ├── client.py           # MCP JSON-RPC async
│       │       └── mapper.py
│       ├── audit/
│       │   ├── writer.py
│       │   └── redaction.py
│       ├── telemetry/
│       │   └── recorder.py
│       ├── shared/
│       │   └── dedup.py
│       └── tests/
│           ├── unit/
│           ├── integration/            # MCP mock + adapter
│           └── security/
│               └── cross_tenant_test.py
├── core/migrations/                    # SQL versionado — NÃO aplicar Supabase prod
│   ├── 000_foundation_tenancy.sql
│   ├── 001_capability_registry_audit.sql
│   └── README.md                       # regras de aplicação
├── docs/
│   ├── cognitive-v2/                   # já existente
│   └── adr/
│       ├── ADR-V2-001-pipeline-raw-canonico.md
│       ├── ADR-V2-002-tenant-actor-resource.md
│       ├── ADR-V2-003-cognitive-prosperfy-boundary.md
│       ├── ADR-V2-004-policy-allow-confirm-deny.md
│       ├── ADR-V2-005-gateway-independente-hermes.md
│       ├── ADR-V2-006-secrets-strategy.md
│       ├── ADR-V2-007-migracao-raw-legado.md
│       └── ADR-V2-008-finance-source-of-truth.md
├── apps/
│   ├── financeiro-pessoal-api/         # INTOCADO Fase 0
│   └── financeiro-pessoal-web/         # INTOCADO Fase 0
├── hermes/
│   └── capability-intelligence/        # INTOCADO Fase 0 (legado operacional)
└── scripts/
    └── cognitive-dev.sh                # sobe gateway local + seed tenant teste
```

**Decisão de runtime:** Python para `core/cognitive` (reuso direto do CI, pytest maduro). Gateway expõe REST JSON; MCP interno opcional na Fase 0.2.

---

## 7. Contratos / interfaces

### 7.1 Gateway API (superfície estável — independente do Hermes)

| Operação | Método | Input mínimo | Output |
|----------|--------|--------------|--------|
| `status.get` | GET `/v1/status` | headers tenant/actor | health, version, tenant resolved |
| `capability.execute` | POST `/v1/capabilities/{id}/execute` | `{ params, idempotency_key? }` — tenant/actor **somente headers** | `{ execution_id, correlation_id, status, data, audit_id }` |
| `capability.describe` | GET `/v1/capabilities/{id}` | tenant/actor | schema resumido (não 186 tools) |

**Headers obrigatórios:**

- `X-Tenant-Id`
- `X-Actor-Id`
- `X-Correlation-Id` (opcional; gerado se ausente)
- `Authorization: Bearer <client_credential>` — credential do **cliente Cognitive** (Hermes, app, bot, worker); **não** modelar como token exclusivo do Hermes

### 7.2 Ports internos (Python Protocol)

```python
# contracts/capability.py — derivado de models.py + executor.py

class CatalogPort(Protocol):
    async def resolve(self, query: IntentQuery) -> CatalogResult: ...

class ExecutionPort(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionReference: ...
    async def result(self, ref: ExecutionReference) -> CapabilityResult: ...
    async def status(self, ref: ExecutionReference | None = None) -> StatusResult: ...

class CapabilityRegistryPort(Protocol):
    def get(self, capability_id: str, tenant_id: str) -> RegisteredCapability | None: ...
    def list_for_actor(self, tenant_id: str, actor_id: str) -> list[RegisteredCapability]: ...

class PolicyPort(Protocol):
    async def evaluate(self, ctx: ActorContext, capability: RegisteredCapability, params: dict) -> PolicyDecision: ...

class AuditPort(Protocol):
    async def record(self, event: AuditEvent) -> str: ...

class SkillsAdapterPort(Protocol):
    async def invoke_tool(self, tool_name: str, arguments: dict, ctx: ActorContext) -> dict: ...
```

### 7.3 Mapeamento V2 interfaces sugeridas → Fase 0

| Interface V2 (`02-ARQUITETURA-ALVO.md`) | Fase 0 |
|----------------------------------------|--------|
| `capability.execute` | **Implementar** |
| `status.get` | **Implementar** |
| `data.query` | Stub 501 (Fase 1) |
| `task.manage` | Stub 501 (Fase 1) |
| `workflow.execute` | Stub 501 (Fase 3) |
| `knowledge.search` | Stub 501 (Fase 2) |

### 7.4 PolicyDecision

```python
class PolicyDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"   # ex-REQUIRE_APPROVAL
    DENY = "deny"
```

CONFIRM na Fase 0: retorna `status: pending_confirmation` + `audit_id`; execução real exige segundo endpoint (Fase 0.3 ou Fase 3).

---

## 8. Migrations necessárias (arquivos apenas — sem executar Supabase prod)

### 8.1 `000_foundation_tenancy.sql`

Tabelas base (`03-MULTITENANCY-E-SEGURANCA.md`):

| Tabela | Campos principais |
|--------|-------------------|
| `tenants` | `id`, `slug`, `name`, `status`, `plan`, `created_at` |
| `tenant_members` | `tenant_id`, `user_id`, `role`, `profile`, `created_at` |
| `tenant_resources` | `tenant_id`, `resource_type`, `resource_key`, `metadata` |
| `tenant_integrations` | `tenant_id`, `integration_type`, `status`, `credential_ref_id` |
| `credential_refs` | `id`, `tenant_id`, `provider`, `secret_ref`, `rotated_at` |
| `capability_grants` | `tenant_id`, `profile`, `capability_id`, `policy_override` |

**RLS:** requisito de isolamento cross-tenant **congelado**; mecanismo específico (**JWT claims**, `current_setting`, app-layer, workers) **não congelado** — ver **ADR-V2-002**.

**Ambiente dev (aprovado):** Docker Compose para Postgres local + testcontainers em CI quando útil.

**Nota:** arquivos versionados em `core/migrations/` (Sprint 0.2+); **Sprint 0 não cria migrations executáveis**. Aplicação apenas em dev/CI local — **nunca** Supabase prod nesta fase.

### 8.2 `001_capability_registry_audit.sql`

**Source of truth da definição:** YAML versionado em `registry/capabilities/*.yaml` (**ADR-V2-005**). Banco **não** replica definição autoritativa.

| Tabela | Finalidade |
|--------|------------|
| `capability_bundles` | profile → lista capability ids |
| `audit_events` | append-only: tenant, actor, capability, policy, inputs_redacted, result, duration_ms, correlation_id |
| `execution_traces` | steps de capability composta (parent execution_id, tool_name, status) |
| `cost_telemetry` | tenant, route, tokens_in/out nullable, tool_calls, latency_ms, cost_estimate |
| `idempotency_keys` | tenant, key, capability_id, response_hash, expires_at |

### 8.3 RAW legado

**Nenhuma migration RAW canônica na Fase 0.** Apenas:

- ADR-V2-007 documentando dual-read strategy
- contrato congelado (`conversations` → `raw_messages` → …)
- **não** alterar `owner_raw_inbox/raw_items` no Supabase

---

## 9. Impacto no Finance atual

| Aspecto | Fase 0 | Fase futura (ADR-V2-008) |
|---------|--------|--------------------------|
| Código `apps/financeiro-pessoal-*` | **Zero alterações** | Fase 4 |
| SQLite `financial_*` | Continua operacional POC William | Adicionar `tenant_id` + RLS ou app dedicado |
| JSON store Pluggy | Preservado | Migrar auditoria para audit_events |
| Rotas GET sem auth | Documentar risco; **não corrigir** Fase 0 | Gateway/proxy com tenant |
| `financial_transaction_enrichment` | DDL órfão permanece | Writer na Fase 4 |
| Fonte da verdade | ADR registra: **SQLite POC = pessoal William; Supabase = operacional futuro** | Decisão humana antes Fase 4 |

**Integração Fase 0:** nenhuma. Finance permanece app paralelo. Gateway não roteia finance ainda.

---

## 10. Impacto no Capability Intelligence

| Aspecto | Ação Fase 0 |
|---------|-------------|
| `hermes/capability-intelligence/` | **Intocado** — continua plugin instalável |
| Testes existentes (247) | Continuam passando; CI Hermes não quebra |
| Código reutilizado | **Port** para `core/cognitive/` (cópia/adaptação) |
| Plugin `/capability` | Permanece diagnóstico legado |
| Relação futura | Hermes vira **cliente** do Gateway (`capability.execute`) — migração gradual pós-Fase 0 |
| `MCPAdapter` bugs | Corrigidos só no **novo** adapter; legado documentado como deprecated path |

**Risco de divergência:** dois pipelines paralelos (CI legado vs Core novo) até migração explícita. Mitigação: contratos compartilhados em `core/cognitive/contracts/` + testes de paridade mínima.

---

## 11. Dependências

### 11.1 Novas (pacote `core/cognitive`)

| Dependência | Motivo | Fase |
|-------------|--------|------|
| `httpx` | MCP async (substituir `HTTPSConnection`) | 0.1 spike |
| `pydantic` v2 | validação Gateway DTOs | 0.1 |
| `pyyaml` | registry YAML capabilities | 0.1 |
| `psycopg[binary]` ou `asyncpg` | testes tenancy/RLS locais | 0.2 |
| `testcontainers[postgres]` | CI cross-tenant | 0.2 |
| `uvicorn` | servir Gateway dev | 0.1 |

**Manter:** stdlib-first onde possível; **não** adicionar LLM SDK.

### 11.2 Variáveis de ambiente (novo Gateway)

| Variável | Uso |
|----------|-----|
| `COGNITIVE_HOST`, `COGNITIVE_PORT` | bind |
| `COGNITIVE_GATEWAY_CREDENTIAL` (ou mapa de credentials) | auth client→Gateway — **não** token do Hermes |
| `COGNITIVE_DATABASE_URL` | Postgres **local/test only** Fase 0 |
| `MCP_PROSPERFYSKILLS_API_KEY` | adapter (mesmo nome CI) |
| `MCP_PROSPERFYSKILLS_HOST` | default `skills.prosperfy.com.br` |
| `COGNITIVE_LOG_REDACT_FIELDS` | audit redaction |

**Não usar:** secrets Supabase prod na Fase 0.

### 11.3 Dependências externas (somente leitura)

- ProsperfySkill MCP (`prosperfy_vps_*`, `prosperfy_discover_capabilities`)
- Supabase prod: **somente documentação/referência**; zero writes

---

## 12. Testes

### 12.1 Pirâmide Fase 0

| Camada | Casos |
|--------|-------|
| **Unit** | PolicyEngine (ALLOW/CONFIRM/DENY); Registry loader; redaction audit; ActorContext validation |
| **Integration** | Gateway → orchestrator → mock MCP; `infra.inspect` composta com MCP stub |
| **Security** | Cross-tenant: tenant A não lê audit/grants de tenant B; capability negada sem grant |
| **Contract** | OpenAPI snapshot `/v1/capabilities/*`; paridade mínima com `models.py` |
| **Performance** | baseline latência spike (sem SLO ainda — `09-OBSERVABILIDADE`) |

### 12.2 Gate tests obrigatórios

```text
test_cross_tenant_audit_isolation
test_cross_tenant_capability_grant_denied
test_capability_execute_without_tenant_returns_401
test_capability_execute_without_actor_returns_401
test_policy_deny_blocks_adapter_call
test_policy_confirm_does_not_call_adapter
test_infra_inspect_allow_writes_audit_and_telemetry
test_secrets_redacted_in_audit_payload
test_idempotency_key_prevents_duplicate_execution
test_prosperfy_skills_adapter_mocked_no_real_vps_in_ci
```

### 12.3 O que NÃO testar na Fase 0

- Integração Hermes plugin
- Supabase prod / RLS real remoto
- Finance Pluggy sync
- RAW ingestion

---

## 13. Riscos

| Risco | Prob. | Impacto | Mitigação |
|-------|-------|---------|-----------|
| Divergência CI legado vs Core novo | Alta | Médio | Contratos compartilhados; ADR boundary |
| Aplicar migration Supabase por engano | Média | Alto | README migrations + CI guard; **proibido** em Fase 0 |
| MCPAdapter legado confundir implementação | Média | Médio | Novo pacote `core/`; legado congelado |
| RLS só testada localmente ≠ Supabase prod | Alta | Alto | Spike local; validação Supabase **fase posterior com aprovação** |
| Scope creep (Tasks/RAW na Fase 0) | Média | Alto | Stubs 501; gate checklist rígido |
| `infra.inspect` chamar VPS real em dev | Média | Médio | Mock default CI; flag `COGNITIVE_LIVE_MCP=1` opt-in |
| Secrets em audit | Baixa | Alto | `redaction.py` + testes |
| Dois pacotes Python (CI + core) | Média | Baixo | Extrair contracts; depreciar duplicação depois |

---

## 14. Ordem de implementação

### Sprint 0 — Documentação (sem runtime)

1. Criar ADRs V2-001 a V2-008 em `docs/adr/`
2. Congelar contratos Gateway (`contracts/gateway.py` spec em markdown)
3. Registrar capability `infra.inspect` (YAML spec)
4. **Gate:** ADRs revisados humanamente

### Sprint 0.1 — Scaffold Core (sem banco)

5. Criar `core/cognitive/` + `pyproject.toml` + pytest
6. Portar `contracts/capability.py`, `policy/engine.py`, `execution/executor.py`
7. Implementar `ProsperfySkillsAdapter` (httpx + ports corretos) com **mock MCP**
8. Implementar `ExecutionOrchestrator` in-memory (audit/telemetry RAM)
9. Gateway mínimo: `GET /health`, `POST /v1/capabilities/infra.inspect/execute`
10. Dev CLI `scripts/cognitive-dev.sh`
11. **Gate:** spike end-to-end com mock; testes unitários verdes

### Sprint 0.2 — Tenancy + Policy + Registry persistente (Postgres local only)

12. Escrever `000_foundation_tenancy.sql`, `001_capability_registry_audit.sql`
13. Repository Postgres local + seed tenant/actor teste
14. Grants + bundles (`infra-read`)
15. Policy CONFIRM/DENY wired
16. Audit + telemetry persistidos
17. Testes cross-tenant
18. **Gate Foundation parcial**

### Sprint 0.3 — Live MCP opt-in + observabilidade

19. Integração real MCP (`infra.inspect`) behind flag
20. Medir latência/tool calls vs chamada Hermes direta (doc comparativo)
21. Idempotency keys
22. **Gate Foundation completo**

### Sprint 0.4 — Handoff Fase 1

23. Relatório gate (`docs/cognitive-v2/13-FASE-0-GATE-REPORT.md` — futuro)
24. Aprovação humana antes de Projects/Tasks

---

## 15. Critérios de pronto (Definition of Done Fase 0)

- [ ] `core/cognitive` roda localmente sem Hermes
- [ ] `infra.inspect` executa via Gateway com tenant/actor/policy/audit
- [ ] Migrations SQL existem em `core/migrations/`; **nenhuma** aplicada Supabase prod
- [ ] Hermes plugin **bit-identical** ao início da fase
- [ ] Finance apps **bit-identical** ao início da fase
- [ ] Testes cross-tenant passam em Postgres local
- [ ] Documentação ADR completa
- [ ] Relatório comparativo custo/superfície (baseline Hermes direto vs Gateway)

---

## 16. Perguntas abertas (decisão humana antes de codar Sprint 0.1)

1. Gateway em Python puro vs FastAPI — confirmar preferência do time
2. Postgres local: Docker Compose no repo vs testcontainers-only
3. `COGNITIVE_API_TOKEN` compartilhado com Hermes futuro ou PKI por cliente
4. Capability composta `infra.inspect`: lista exata de tools VPS e ordem
5. Momento de primeiro apply Supabase staging (explicitamente **pós** Fase 0 gate)

---

## 17. Referências

- `docs/cognitive-v2/07-FASES-IMPLEMENTACAO.md` — escopo Fase 0
- `docs/cognitive-v2/11-PLANO-DE-INICIO.md` — spike infra.inspect
- `docs/cognitive-v2/10-GATES-E-CRITERIOS-DE-ACEITE.md` — checklist
- `PROSPERFY_COGNITIVE_CURRENT_STATE_AUDIT.md` — estado atual
- `hermes/capability-intelligence/src/capability_intelligence/models.py`
- `hermes/capability-intelligence/src/capability_intelligence/policy_engine.py`
- `hermes/capability-intelligence/src/capability_intelligence/transport/adapters/mcp_adapter.py`
