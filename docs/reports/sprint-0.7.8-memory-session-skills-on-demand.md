# Sprint 0.7.8 — Memory + Session Search + Skills On-Demand

> Hermes Slim continuity: routing determinístico pré-LLM de capabilities.
> Normal chat continua 0 tools. Sem classifier LLM. Sem novas capabilities externas.

## 1. Router consolidado (capability_router.py)

```
resolve_specialist_route(message) -> NORMAL | CRON | SESSION_SEARCH | MEMORY | SKILLS
Precedência: slash explícito > CRON(scheduling temporal) > SESSION_SEARCH > MEMORY > SKILLS > NORMAL
CAPABILITY_ROUTER_LLM_CALLS=0 (gate 100% determinístico)
Colisão resolvida:
  "Me lembre amanhã às 9h de enviar o relatório." → CRON
  "Me lembre o que decidimos sobre o Hermes."     → SESSION_SEARCH (recall, sem scheduling)
cron_router: temporais de scheduling adicionados (em X minutos/horas/dias, hoje às,
  dias da semana, às Nh) — gate conservador mantido.
Rotas explícitas: /cron /memory /memoria /session /historico /skills
```

## 2. Tool availability (aprendizado do Cron aplicado ANTES do live)

```
Audit com HERMES_GATEWAY_SESSION=1:
  MEMORY: resolve ['memory'] → FINAL_DEFS=['memory'] · 1 tool · 3181 B
  SESSION_SEARCH: resolve ['session_search'] → FINAL_DEFS=['session_search'] · 1 tool · 7052 B
  SKILLS: resolve ['skill_manage','skill_view','skills_list'] → FINAL_DEFS iguais · 3 tools · 5664 B
  (toolset SKILLS usa o NOME do toolset 'skills' — nomes de tool individuais não resolvem;
   corrigido na validação)
MEMORY_RUNTIME_AVAILABLE=YES · SESSION_SEARCH_RUNTIME_AVAILABLE=YES · SKILLS_RUNTIME_AVAILABLE=YES
```

## 3. Pipeline real (gateway + get_tool_definitions) — 10/10 PASS

```
MEMORY      'O que você lembra sobre meu código de teste?' → tools=['memory']
NORMAL      'Obrigado'                                    → tools=[]
SESSION     'O que conversamos ontem sobre o Cognitive?'   → tools=['session_search']
NORMAL      'Ok'                                          → tools=[]
SKILLS      'Quais skills você possui?'                    → tools=[skill_manage,skill_view,skills_list]
NORMAL      'Oi'                                          → tools=[]
CRON        'Me lembre daqui a 5 minutos...'               → tools=['cronjob']
NORMAL      'Tudo bem?'                                   → tools=[]
COLLISION   'Me lembre o que decidimos sobre o Hermes.'    → tools=['session_search']  ✓ recall
NORMAL      'valeu'                                       → tools=[]
Isolamento por turno: MEMORY_TOOL_CARRIED_OVER=NO · SESSION=NO · SKILLS=NO · CRON=NO
```

## 4. Contract tests

```
test_capability_router.py: 22 casos (NORMAL/CRON/SESSION_SEARCH/MEMORY/SKILLS + colisão)
CONTRACT=PASS (22/22)
test_cron_router.py: mantido (19) — regressão cron coberta
```

## 5. Deploy + live

```
Deploy: capability_router.py + cron_router.py no package do runtime (gate-0.5/src)
        gateway/run.py router-wired no hermes-clean
HERMES_CLEAN_SHA_AFTER=b58c8589 (branch prosperfy-cron-wiring)
Deploy single-bridge: stop → old bridge 0 → start
  GW=MainPID 3355346 · NRestarts=0 · bridge node :3000 (sessão reutilizada)
VERIFY_SLIM=PASS (NORMAL_CHAT_TOOLS=0 · SCHEMA_BYTES=0 · CAPABILITY_FAIL_CLOSED=PASS)
```

## 6. Pendente (Human Acceptance pelo usuário, WhatsApp)

```
Teste A: "Oi" → 0 tools
Teste B: "Lembre que meu código de teste do Hermes é ORION-78." → Memory write;
         "Qual código de teste do Hermes eu pedi para você lembrar?" → Memory read
Teste C: "O que decidimos anteriormente sobre o Browser Harness?" → Session Search
Teste D: "Quais skills você tem disponíveis?" → Skills route
E2E de dados (MEMORY_TEST_078=ORION / TEST_SKILL_078) quando o usuário validar o canal.
SKILLS_AUTOMATIC_LEARNING=NO · AUTO_MEMORY_GLOBAL=NO
```

## 7. Métricas

```
SPRINT078_CHECKPOINT=<pos push>
NORMAL_FINAL_TOOLS=[] · CRON=['cronjob'] · MEMORY=['memory'] · SESSION=['session_search'] · SKILLS=[3]
NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0
/SERVIDORES: pipeline inalterado (não re-executado; código intacto) · LLM_CALLS=0 · MCP=12
CAPABILITY_FAIL_CLOSED=PASS · LEGACY_FALLBACK=NO/NO · WHATSAPP_BRIDGE_READY=YES
SINGLE_BRIDGE=YES · UNEXPECTED_RESTARTS=0
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES · WORKTREE_CLEAN=YES
SPRINT_0_7_8_FINAL_GATE=PASS (routing + tool availability + isolamento provados no
  pipeline real; aguarda Human Acceptance do canal WhatsApp)
```