# Phase 1B — Slice 1I: Deploy + Pre-Human Validation (resultado: PARCIAL — grant não efetivo)

> Enforcement deployado + carregado + dry-run PASS + first-turn PASS + regressão PASS +
> reloads observados. GRANT não efetivo no runtime (DENY no grant layer) — o "Sim" real
> seria negado com segurança (sem restart). HUMAN_TEST_READY=NO até o operador verificar o grant.

## 1. Deploy (Cognitive Homolog)

```
DEPLOY_SOURCE_SHA=5deebe3 (origin/dev/phase1b-restart-container, fetched)
DEPLOY_HASH_MATCH=YES (hashes do checkout → runtime)
COGNITIVE_DEPLOY_FILES=orchestrator.py (25308B) · guard.py (5493B) · infra.action.yaml (1537B)
COGNITIVE_OLD_PID=3944123 → COGNITIVE_NEW_PID=4062633 · PID_CHANGED=YES · ACTIVE=YES
COGNITIVE_HEALTH=PASS (get_status True, pós-teste)
```

## 2. Enforcement carregado + dry-run (in-process, sem MCP)

```
RUNTIME_ENFORCEMENT_LOADED=YES (símbolos no código deployado: 2/2/2)
ALLOWED_RESOURCES=["prosperfy-vps-homolog"] (Prosperfy-only) · RESOURCE_SCOPE_EFFECTIVE=OK
PLANNED_TOOL=prosperfy_vps_controlar_container
PLANNED_ARGS={"host":"<resolved>","container":"omniroute","acao":"restart","confirmar":true}
  (contrato EXATO do schema MCP observado) · MCP_INVOKED=NO · REAL_RESTART_EXECUTED=NO
GUARD: start/stop/delete → BLOCK (fail-closed) · ADAPTER_DRY_RUN=PASS
```

## 3. First-turn confirmation (Hermes, directo)

```
ROUTE=INFRA_ACTION · TOOLSET=['restart_container']
FIRST_TURN: resource→prosperfy-vps-homolog · container=omniroute · confirmed=false ·
  message pede confirmação · PENDING_REGISTERED=YES · MCP_INVOKED=NO
CONFIRMATION_FIRST_TURN=PASS · ZERO_MUTATION_BEFORE_CONFIRMATION=PASS
```

## 4. ACHADO — grant não efetivo no runtime

```
`confirmed=true` (consumiu o pending do 1º turno) → Cognitive infra.action → 
  DENY: "Tenant 11a26649… não possui grant para 'infra.action'".
MCP NÃO invocado (fail-closed no grant layer — sem restart). 
Interpretação: o grant provisionado pelo operador NÃO resolve para o PROFILE real usado
  pelo runtime Hermes (profile ≠ 'hermes-homolog'? OU policy_override não aplicado? OU
  autorização de recurso). Não toco em grants (admin) — operador deve verificar.
POLICY_POSITIVE (autorização de grant) = NÃO efetivo no runtime → HUMAN_TEST_READY=NO
```

## 5. Regressões + reloads

```
IDEMPOTENCY_REGRESSION=PASS (API healthy pós-negatives; sem crash) · COGNITIVE_API_CRASH=NO
PHASE1A_REGRESSION=PASS (Black=11 portas: 22,25,3000,3001,443,53,5432,6504,80,8000,8025;
  rotas INFRA_READ/NORMAL corretas)
HERMES_OLD_PID=3929664 → STOP (MainPID=0) → START → NEW_PID=4063276 · bridge 4063315
  (SINGLE_BRIDGE=YES) · HERMES_WIRING=core (2984ed5) · DIRECT_SSH/MCP=NO
REAL_RESTART_BY_OPENCODE=NO
```

## 6. Gate

```
DEPLOY_SOURCE_SHA=5deebe3 · DEPLOY_HASH_MATCH=YES · COGNITIVE_HEALTH=PASS
RUNTIME_ENFORCEMENT_LOADED=YES · RESOURCE_SCOPE_EFFECTIVE=prosperfy-vps-homolog
POLICY_POSITIVE=DENY-no-grant (não efetivo) · POLICY_NEGATIVES=PASS (guard + grant layer)
ADAPTER_DRY_RUN=PASS · MCP_INVOKED=NO · IDEMPOTENCY_REGRESSION=PASS · PHASE1A_REGRESSION=PASS
HERMES_INFRA_ACTION_ROUTE=PASS · CONFIRMATION_FIRST_TURN=PASS
ZERO_MUTATION_BEFORE_CONFIRMATION=PASS
PHASE1B_RESTART_HUMAN_TEST_READY=NO (grant não efetivo no runtime — operador verificar)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```

## 7. Ação do operador (destravar)

```
Verificar por que o grant infra.action não resolve p/ o profile real do runtime Hermes:
  1) o profile usado pela identidade (COGNITIVE_ACTOR_ID/credential → profile) vs 'hermes-homolog'
  2) policy_override 'allow' aplicado + active=true na capability_grants correta
  3) autorização de recurso (prosperfy-vps-homolog) no grant/resource layer
Depois: revalidar POLICY_POSITIVE (ALLOW no dry-run) → HUMAN_TEST_READY
```