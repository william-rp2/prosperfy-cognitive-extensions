# Phase 1B — Slice 1B: Cognitive infra.action (restart container)

> Spec canônica da capability `infra.action` criada (restart-only, deny-default,
> governada). Integração completa no Cognitive Homolog (adapter mapping + grant +
> deploy + testes controlados) NÃO concluída nesta sessão — inspeção do schema MCP
> de `prosperfy_vps_controlar_container` bloqueada por truncamento do canal host.

## 1. Entregue (canônico)

```
INFRA_ACTION_CAPABILITY_SPEC=YES (hermes/phase1-infra-read/infra.action.yaml)
  id=infra.action · version=1.0.0 · adapter=prosperfy_skills · default_policy=deny
  required_scopes=infra:write
  input: resource · action(enum=[restart]) · target_type(const=container) · target
  output: success/resource/action/target_type/target/execution_result/post_condition
  tools: prosperfy_vps_controlar_container (args: action=${action}, container=${target})
  validation_rules: action=restart · target_type=container · resource autorizado
  confirmation: pending_action_resolved_by_hermes (2 turnos, não confia em texto livre)
  audit_fields: tenant/actor/resource/action/target_type/target/authorization_decision
RESTART_ONLY=YES · DENY para start/stop/delete/prune/exec/shell/reboot (enum/spec)
BRANCH=dev/phase1b-restart-container · CHECKPOINT=c4cdbf8
```

## 2. Inspeção MCP — BLOQUEADA nesta sessão (honestidade)

```
MCP_TOOL=prosperfy_vps_controlar_container (confirmado no catálogo ProsperfySkill — 190 tools)
MCP_SCHEMA/REQUIRED_ARGS: NÃO extraído — o registry do hermes não expõe o schema dos
  tools MCP em processo novo (requer conexão MCP do gateway), e o adapter do Cognitive
  (fastmcp) exige o venv gate-0.3 + construtor (env) que o canal host truncou.
ARG_MAPPING (spec): resource→binding MCP · container=${target} · action=${action}
  (padrão args_from_resource do infra.inspect — a validar contra o schema real do MCP
  na execução dedicada)
```

## 3. Pendente (execução dedicada)

```
- Inspecionar o schema REAL de prosperfy_vps_controlar_container (venv gate-0.3,
  fastmcp client, via Cognitive)
- Registrar infra.action.yaml no registry do Cognitive (Homolog)
- Provisionar grant infra:write p/ a identidade Hermes (SERVICE_IDENTITY/PROFILE)
- Adapter: confirmar args mapping no ProsperfySkillsAdapter
- Deploy (restart prosperfy-cognitive-homolog-api.service)
- Testes controlados A-G (mock/sem restart real) + regressão Phase 1A
- Wiring Hermes: restart_container já aponta p/ infra.action (2984ed5) — validar
- Reload Hermes com Host Execution Trust (OLD_PID→NEW_PID observado)
- Human Acceptance (WhatsApp): "Reinicie o omniroute no Prosperfy." → confirmação →
  "Sim" → restart real → post-condition
```

## 4. Métricas

```
INFRA_ACTION_CAPABILITY=SPEC_READY (integração Cognitive pendente)
RESTART_ONLY=YES · POLICY=DENY-default (spec) · FAIL_CLOSED=YES (spec)
SERVICE_IDENTITY/CAPABILITY_GRANTED/RESOURCE_SCOPE=PENDING (provisioning)
COGNITIVE_TESTS=PENDING · PHASE1A_REGRESSION=PENDING (não executados)
HERMES_CHECKPOINT=2984ed5 (tool/rota prontas) · OLD/NEW_PID=N/A (sem reload nesta sessão)
TARGET_RESOURCE=Prosperfy · TARGET_CONTAINER=omniroute
PHASE1B_RESTART_HUMAN_TEST_READY=NO
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```