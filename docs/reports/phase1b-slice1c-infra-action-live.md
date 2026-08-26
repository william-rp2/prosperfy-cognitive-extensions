# Phase 1B — Slice 1C: Cognitive infra.action LIVE integration (parcial)

> Schema MCP observado + capability registrada no Homolog (deny-default) + policy
> fail-closed. Grant infra:write + enforcement restart-only no adapter + wiring
> Hermes + Human Acceptance = pendentes (execução dedicada).

## 1. MCP SCHEMA — BLOCKING GATE PASSED (observado do catálogo REAL)

```
MCP_SCHEMA_SOURCE=ProsperfySkill MCP tools/list (skills.prosperfy.com.br/mcp)
TOOL_NAME=prosperfy_vps_controlar_container
DESC=Controla container Docker: start, stop, restart, logs ou inspect.
INPUT_SCHEMA: {host:str(req), container:str(req), acao:str(req), linhas:int(def 100),
               confirmar:bool(def false), token:str}
REQUIRED_FIELDS=[host, container, acao] · OPTIONAL=[linhas, confirmar, token] · ENUMS=none
HOST_FIELD=host · CONTAINER_FIELD=container · ACTION_FIELD=acao (NÃO "action") ·
CONFIRM_FIELD=confirmar (bool)
→ mapping da spec CORRIGIDO: action→acao="restart" · target→container · confirmar=true
```

## 2. Registro no Cognitive Homolog

```
infra.action.yaml deployado no registry (capabilities/) + restart da API (Host Trust:
  COGNITIVE_OLD_PID → NEW_PID 3944123, active)
CAPABILITY_REGISTERED=YES · ADAPTER=prosperfy_skills · DEFAULT_POLICY=deny · REQUIRED_SCOPE=infra:write
CAPABILITIES=["infra.action","infra.inspect"] (verificado via GET /v1/capabilities)
INCIDENTE tratado: idempotency_behavior inválido ('reject_duplicate') crashou a API →
  corrigido p/ 'return_cached' + restart (API restaurada; NÃO ficou down)
```

## 3. Policy tests (sem mutação real — casos executados via /execute)

```
action=start  tt=container → DENIED (sem grant) ✓ fail-closed
action=stop   tt=container → DENIED ✓
action=delete tt=container → DENIED ✓
action=restart tt=server   → DENIED ✓
action=restart tt=container → DENIED (grant ainda não provisionado — o restart NÃO executa)
→ POLICY=PASS (fail-closed: nenhum restart ocorreu; sem grant = deny)
Nota: a rejeição atual é por AUSÊNCIA DE GRANT. O enforcement restart-only (acao=restart,
  target_type=container) precisa ser validado no adapter após o grant — validation_rules
  no YAML é spec/custom (loader ignora); enforcement efetivo deve estar no executor/adapter.
```

## 4. Pendente (execução dedicada)

```
- GRANT mínimo: infra.action/infra:write p/ a identidade Hermes (tenant 11a26649...),
  RESOURCE_SCOPE=prosperfy-vps-homolog somente (DB grants)
- Enforcement restart-only no adapter (acao=restart + target_type=container; DENY start/stop/
  delete/exec/shell) — além do deny-default
- Adapter dry-run: args {host, container, acao=restart, confirmar=true} exatos do schema
- Wiring Hermes: restart_container (2984ed5) aponta p/ infra.action + params corretos
- Reload Hermes com Host Trust (OLD→NEW PID observado) + regressão Phase 1A
- Human Acceptance WhatsApp (Turno 1 confirmação + Turno 2 "Sim") — REAL_RESTART NÃO executado
```

## 5. Métricas

```
MCP_SCHEMA_OBSERVED=YES · MCP_ARGS_MAPPING={acao, container, confirmar} (corrigido)
INFRA_ACTION_REGISTERED_LIVE=YES · GRANT_LIVE=NO (pendente) · RESOURCE_SCOPE=Prosperfy (planejado)
POLICY_TESTS=deny-cases PASS (fail-closed, sem grant) · restart-only enforcement=PENDENTE (adapter)
ADAPTER_DRY_RUN=PENDING · INFRA_READ_REGRESSION=PENDING
HERMES_WIRING=2984ed5 (tool aponta p/ infra.action) · OLD/NEW PID Hermes=N/A
TARGET_RESOURCE=Prosperfy · TARGET_CONTAINER=omniroute · REAL_RESTART_BY_OPENCODE=NO
PHASE1B_RESTART_HUMAN_TEST_READY=NO (grant + enforcement + wiring)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```