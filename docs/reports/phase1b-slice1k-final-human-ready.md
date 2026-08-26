# Phase 1B — Slice 1K: Final Human-Ready Gate (resultado: HUMAN_TEST_READY=YES)

> Payload fix 3009b7b deployado no Hermes + grant real resolvido (infra-read/allow) +
> payload provado + first-turn ZERO mutation + regressões PASS. NENHUM restart real.

## 1. Deploy (Hermes payload fix 3009b7b)

```
CHECKPOINT=3009b7b (origin/dev/phase1b-restart-container, fetched)
SOURCE_RUNTIME_HASH_MATCH=YES (source 9b3c48ea == runtime 9b3c48ea; RUNTIME_BEFORE 1378a9ca)
HERMES_OLD_PID=4063276 → STOP → START → HERMES_NEW_PID=4081779 · PID_CHANGED=YES · ACTIVE=YES
bridge node presente (SINGLE_BRIDGE=YES) · sem EADDRINUSE
```

## 2. Payload do runtime (provado com fake adapter — sem Cognitive live)

```
_cognitive_restart (3009b7b) constrói ExecutionRequest:
  capability_id=infra.action
  params={resource:"prosperfy-vps-homolog", action:"restart", target_type:"container",
          target:"omniroute"}
PAYLOAD_CAPTURED (fake execute) → PAYLOAD_MATCH=YES · NO_LEAK=YES (sem host/acao/confirmar/
  token/linhas) · LIVE_COGNITIVE_POSITIVE_CALLED=NO · MCP_INVOKED=NO
CAPTURED #2 = infra.inspect (post-condition read — correto)
```

## 3. Grant real do runtime (RLS — sem admin)

```
RUNTIME_GRANT_RESOLUTION=PASS · PROFILE=infra-read · POLICY=allow · CAP=infra.action
GrantRepository.get_grant(tenant 11a26649…, infra-read, infra.action) via app pool (RLS)
POLICY_POSITIVE=ALLOW (grant resolve + fluxo interceptado antes do MCP)
```

## 4. First-turn + negatives

```
FIRST_TURN: route=INFRA_ACTION · resource=prosperfy-vps-homolog · container=omniroute ·
  confirmed=false · pending criada · pedido de confirmação · MCP_RESTART_CALLS=0
CONFIRMATION_FIRST_TURN=PASS · ZERO_MUTATION_BEFORE_CONFIRMATION=PASS
SIM_WITHOUT_PENDING=PASS (fail-closed) · CANCEL_TEST=coberto (não enviei "Sim" válido)
REAL_RESTART_BY_OPENCODE=NO
```

## 5. Regressão Phase 1A

```
PHASE1A_QUICK_REGRESSION=PASS: Black=11 portas (22,25,3000,3001,443,53,5432,6504,80,8000,8025);
  rotas INFRA_READ/NORMAL corretas · COGNITIVE_HEALTH=True
IDEMPOTENCY: API healthy (sem crash)
```

## 6. Final gate

```
CHECKPOINT=3009b7b · SOURCE_RUNTIME_HASH_MATCH=YES · HERMES_ACTIVE=YES · SINGLE_BRIDGE=YES
RUNTIME_HERMES_PAYLOAD_MATCH=YES · RUNTIME_GRANT_RESOLUTION=PASS (infra-read/allow)
POLICY_POSITIVE=ALLOW · PLANNED_TOOL=prosperfy_vps_controlar_container · PLANNED_ARGS_EXACT=YES
REAL_ADAPTER_USED=NO · MCP_INVOKED=NO · REAL_RESTART_EXECUTED=NO
CONFIRMATION_FIRST_TURN=PASS · ZERO_MUTATION_BEFORE_CONFIRMATION=PASS · SIM_WITHOUT_PENDING=PASS
PHASE1A_QUICK_REGRESSION=PASS
PHASE1B_RESTART_HUMAN_TEST_READY=YES
REAL_RESTART_BY_OPENCODE=NO · PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```

## 7. Human Acceptance (usuário, WhatsApp)

```
Turno 1: "Reinicie o omniroute no Prosperfy." → confirmação (ZERO restart)
Turno 2: "Sim." → infra.action → MCP restart → nova infra.inspect → post-condition
A execução real é do usuário no canal — NÃO do OpenCode.
```