# Fase D — Validacao Funcional: Autorizacao (A1-A8)

**Data:** 2026-07-24  
**Responsavel:** Hermes Agent (Fase D)  
**Arquivo de teste:** `tests/test_fase_d.py`  
**Total de cenarios:** 8 (A1-A8)  
**Total de testes:** 20 (17 + 3 do A8)  
**Status:** ✅ **20/20 PASS**

---

## Sumario

| Cenário | Perfil | Acao | Ambiente | Decisao Esperada | Resultado |
|---------|--------|------|----------|-----------------|-----------|
| A1 | observer | `list_containers` | — | ✅ ALLOW | ✅ PASS |
| A2 | observer | `deploy_evolution_api` | — | ❌ DENY | ✅ PASS |
| A3 | operator | `deploy_evolution_api` | staging | ✅ ALLOW | ✅ PASS |
| A4 | operator | `deploy_evolution_api` | production | ⚠️ REQUIRE_APPROVAL | ✅ PASS |
| A5 | admin | qualquer acao | — | ✅ ALLOW | ✅ PASS |
| A6 | operator | `delete_database` | — | ❌ DENY | ✅ PASS |
| A7 | sem perfil | qualquer acao | — | ❌ DENY | ✅ PASS |
| **A8** | **admin** | **capability inexistente** | — | **⚠️ erro sem mascarar** | **✅ PASS** |

---

## Cenario A8 — Admin + Capability Inexistente

**Objetivo:** Validar que autorizacao nao mascara erro de capability inexistente.

**Pre-condicao:**
- Perfil: admin (autorizado para qualquer acao)
- Catalog: `MockCatalogEmpty` — retorna `matches=[]` (simula capability removida ou nome invalido)

**Mock:** `MockCatalogEmpty` — implementa CatalogPort, AuthorizationPort e ExecutionPort.

**Pipeline:** `Pipeline.run("nonexistent_capability_v2", "infrastructure")`

**Verificacoes:**
- `result.error is not None` — erro informado
- `"not authorized" not in result.error.lower()` — autorizacao **nao mascara** o erro
- `result.success is False`
- `result.success is False` para `"malicious_intent"` — **nenhum bypass de seguranca**
- Gap registrado em `GapProposalStore` para auditoria

**Testes:** 3
1. `test_a8_capability_not_found` — erro, sem "Not authorized"
2. `test_a8_no_security_bypass` — nao executa capability inexistente
3. `test_a8_gap_registered_for_audit` — gap registrado

---

## Detalhamento dos Cenarios

### A1 — observer em `list_containers` → ALLOW

O perfil **observer** tem permissao para operacoes seguras (leitura).

- **Mock:** `MockObserverProfile` — autoriza `list_containers`, nega `deploy_evolution_api`
- **Pipeline:** `Pipeline.run("list containers", "infrastructure")`
- **Verificacao:**
  - `result.success is True`
  - `result.capability_id == "list_containers"`
  - `result.error is None`
  - Mensagem "Not authorized" **nao** aparece
- **Testes:** 2

### A2 — observer em `deploy_evolution_api` → DENY

O perfil **observer** nao tem permissao para operacoes de deploy.

- **Mock:** `MockObserverProfile` — nega `deploy_evolution_api`
- **Pipeline:** `Pipeline.run("deploy evolution api", "infrastructure")`
- **Verificacao:**
  - `result.success is False`
  - `result.error` contem "Not authorized"
  - `result.error` menciona "observer"
- **Testes:** 2

### A3 — operator em `deploy_evolution_api` em staging → ALLOW

O perfil **operator** pode executar deploy no ambiente **staging**.

- **Mock:** `MockOperatorProfile` — autoriza `deploy_evolution_api`
- **Policy:** `policy_environment_allowed` — staging e permitido
- **Pipeline:** `Pipeline.run("deploy evolution api", "infrastructure", environment="staging")`
- **Verificacao:**
  - `result.success is True`
  - `result.capability_id == "deploy_evolution_api"`
  - `result.error is None`
  - `result.requires_approval is False`
- **Testes:** 2

### A4 — operator em `deploy_evolution_api` em production → REQUIRE_APPROVAL

O perfil **operator** precisa de aprovacao explicita para deploy em **production**.

- **Mock:** `MockOperatorProfile` — autoriza `deploy_evolution_api`
- **Policies:** `policy_environment_allowed` + `policy_requires_approval_for_production` (custom)
- **Pipeline:** `Pipeline.run("deploy evolution api", "infrastructure", environment="production")`
- **Verificacao:**
  - `result.requires_approval is True`
  - `result.success is False` (pipeline nao executa quando requer aprovacao)
  - `result.capability_id == "deploy_evolution_api"`
  - `result.execution_ref is None` (nao executou)
- **Testes:** 2

### A5 — admin → qualquer acao → ALLOW

O perfil **admin** tem permissao total sobre qualquer Capability.

- **Mock:** `MockAdminProfile` — autoriza tudo
- **Pipeline:** Executado com 3 acoes diferentes
- **Verificacao:**
  - `result.success is True` para `list_containers`, `deploy_evolution_api` e `delete_database`
- **Testes:** 3

### A6 — operator em `delete_database` → DENY (requer admin)

O perfil **operator** nao pode executar `delete_database` — operacao restrita a admin.

- **Mock:** `MockOperatorProfile` — nega `delete_database`
- **Pipeline:** `Pipeline.run("delete database", "infrastructure")`
- **Verificacao:**
  - `result.success is False`
  - `result.error` contem "Not authorized"
  - `result.error` menciona "admin"
- **Testes:** 2

### A7 — sem perfil (nao autenticado) → qualquer acao → DENY

Usuarios **nao autenticados** (sem perfil) tem todas as acoes negadas.

- **Mock:** `MockNoProfile` — nega tudo com motivo "unauthenticated: no profile assigned"
- **Pipeline:** Executado com 3 acoes diferentes
- **Verificacao:**
  - `result.success is False` para `list_containers`, `deploy_evolution_api` e `delete_database`
  - `result.error` contem "Not authorized"
  - `result.error` menciona "unauthenticated" ou "no profile"
- **Testes:** 4

---

## Estrutura dos Mocks

### Perfis de Autorizacao (implementam `AuthorizationPort`)

| Mock | `authorize()` para `list_containers` | `authorize()` para `deploy_evolution_api` | `authorize()` para `delete_database` |
|------|--------------------------------------|------------------------------------------|--------------------------------------|
| `MockObserverProfile` | ✅ `authorized=True` | ❌ `authorized=False` | ❌ `authorized=False` |
| `MockOperatorProfile` | ✅ `authorized=True` | ✅ `authorized=True` | ❌ `authorized=False` |
| `MockAdminProfile` | ✅ `authorized=True` | ✅ `authorized=True` | ✅ `authorized=True` |
| `MockNoProfile` | ❌ `authorized=False` | ❌ `authorized=False` | ❌ `authorized=False` |

### Outros Mocks

- **`MockCatalog`** — `CatalogPort` que retorna a Capability solicitada
- **`MockCatalogEmpty`** — `CatalogPort` que retorna `matches=[]` (para A8)
- **`MockExecutionSuccess`** — `ExecutionPort` que sempre executa com sucesso
- **`policy_requires_approval_for_production`** — politica customizada que retorna `REQUIRE_APPROVAL` quando `capability_id == "deploy_evolution_api"` e `environment == "production"`

---

## Fluxo de Autorizacao no Pipeline

```
Pipeline.run()
  ├── Resolver.resolve()          → CatalogPort
  ├── Negotiator.select()         → melhor Capability
  ├── PolicyEngine.evaluate()     → politicas (ambiente, aprovacao)
  │   ├── policy_environment_allowed
  │   └── policy_requires_approval_for_production
  ├── Executor.run()              → AuthorizationPort.authorize()
  │   ├── authorized=True         → executa
  │   └── authorized=False        → retorna erro "Not authorized"
  ├── Interpreter.process()
  └── FeedbackStore.record()
```

A autorizacao ocorre em **dois niveis**:
1. **PolicyEngine** (antes da execucao) — verifica politicas de ambiente e aprovacao
2. **AuthorizationPort** (dentro do Executor) — verifica permissao do perfil do usuario

---

## Resultado da Suite Completa

```
87 passed in 10.15s
```

- Testes pre-existentes: **67** (Fase B, Fase C, models, negotiator, policy_engine, interpreter, feedback_store, gap_proposal)
- Testes novos (Fase D): **20** (17 A1-A7 + 3 A8)
- **Regressao:** ✅ Nenhuma — todos os testes anteriores continuam passando

## Decisao Final

✅ **Aprovada**

Fase D concluida. Todos os 8 cenarios de autorizacao validados com mocks.
A8 adicional validado: admin + capability inexistente → erro sem mascarar autorizacao, gap registrado para auditoria.