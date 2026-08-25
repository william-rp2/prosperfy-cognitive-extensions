# Phase 1A — Corrected Live Validation (resultado: ROUTER PASS · registry/pipeline PENDING)

> Validação por conteúdo/runtime behavior (repos diferentes). Router runtime
> confirmado. Registry gate + pipeline real + /servidores + Browser Harness +
> write inventory NÃO observáveis nesta execução (ferramenta de acesso ao host
> degradou — execuções de processo retornam sem output).

## 1. Repo checkpoint

```
git cat-file -e d85172975b44e0d4ef7b327c3a8f2818bd52005c^{commit} → NÃO resolvido local
  (ref local sem o commit; fetch não completou antes da degradação)
PHASE1_CHECKPOINT_PRESENT=UNCONFIRMED (commit existe no GitHub; fetch pendente)
```

## 2. Router RUNTIME (validado — observado)

```
RUNTIME_CAPABILITY_ROUTER_PATH=/home/will/projetos/prosperfy-cognitive-gate-0.5/
  hermes/capability-intelligence/src/capability_intelligence/capability_router.py
  (path real importado pelo gateway — via inspect)
resolve_specialist_route:
  "Como estão meus servidores?" → INFRA_READ ✓
  "Quais containers estão rodando no Prosperfy?" → INFRA_READ ✓
  "Quais portas estão abertas no Black?" → INFRA_READ ✓
  "O que significa servidor web?" → NORMAL ✓
  "Obrigado" → NORMAL ✓
route_toolsets("INFRA_READ")=["infra_read"] ✓ · HAS_INFRA_READ=True ✓
INFRA_ROUTER_RUNTIME=PASS
```

## 3. Infra tool file

```
/home/will/.hermes/hermes-clean/tools/infra_read_tools.py — PRESENT (4860 B, untracked)
SYNTAX=PASS (local ast.parse; deploy confirmado)
Arquitetura: usa InfraService/CognitiveApiAdapter (capability_intelligence.infra_service);
  SEM paramiko/SSH; SEM chamada MCP direta; SEM docker direto (handler → Cognitive).
INFRA_READ_TOOL_FILE=PASS · INFRA_USES_COGNITIVE=YES
INFRA_DIRECT_SSH_FROM_HERMES=NO · INFRA_DIRECT_MCP_FROM_HERMES=NO
```

## 4. Registry gate / pipeline — PENDING (tooling host)

```
Ferramenta de acesso ao host passou a retornar sem output em execuções de processo
  (venv python não observável). NÃO foi possível confirmar de forma confiável:
  INFRA_REGISTRATION / INFRA_READ_RUNTIME_AVAILABLE / INFRA_READ_FINAL_TOOL_NAMES /
  TOOL_COUNT / check_fn / invocação real / pipeline A–D / /servidores regression /
  Browser Harness / AVAILABLE_INFRA_WRITE_OPERATIONS.
Passo imediato: re-executar o gate de registry (resolve_toolset + get_tool_definitions
  com HERMES_GATEWAY_SESSION) quando a ferramenta host estiver estável; se a tool não
  for registrada, o missing import/registration é o model_tools discovery de tools/*.py
  (a tool file é auto-importada — um restart single-bridge carrega o registro).
```

## 5. Métricas

```
PHASE1A_LIVE_CHECKPOINT=<pos push>
INFRA_ROUTER_RUNTIME=PASS
INFRA_READ_TOOL_FILE=PASS · INFRA_USES_COGNITIVE=YES · NO SSH · NO direct MCP
INFRA_READ_RUNTIME_AVAILABLE=PENDING · INFRA_READ_FINAL_TOOL_NAMES=PENDING
ALL_SERVERS/PROSPERFY/BLACK/HOSTINGER_QUERY=PENDING (pipeline real)
NORMAL_CHAT_TOOL_COUNT=0 (router NORMAL) · INFRA_TOOL_CARRIED_OVER=PENDING
/SERVIDORES_REGRESSION=PENDING · HERMES_GATEWAY_ACTIVE=YES (anterior: PID 3891249)
LIVE_HERMES_BRANCH=prosperfy-cron-wiring · LIVE_HERMES_HEAD=b58c8589
HERMES_BRANCH_MISMATCH_WITH_PHASE1_REPO=N/A_DIFFERENT_REPOSITORIES
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
PHASE1A_LIVE_GATE=PARTIAL (router runtime PASS; registry/pipeline pending tooling)
```