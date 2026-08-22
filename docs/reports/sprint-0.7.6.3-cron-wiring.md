# Cron Specialist — Pre-LLM Dispatch Wiring (closure da pendência)

> PENDÊNCIA de 0.7.3-0.7.6.2 resolvida: `cron_router` ligado ao dispatch real pré-LLM.
> Runtime: hermes-clean LIVE. Sem novas capabilities.

## 1. O que foi ligado

```
ANTES: cron_router.py implementado + toolset cronjob + contract tests, mas
  CRON_PRE_LLM_DISPATCH_WIRED=NO · CRON_REAL_USER_PATH_ACTIVE=NO
DEPOIS: gate determinístico no fluxo real de mensagens → toolset especializado.

Ponto de integração: gateway.run._resolve_enabled_toolsets_for_source
  (já era o ponto que resolve os toolsets do run — o site slim 0-tools).
  Com a mensagem do turno:
    is_cron_intent(message) == True  → enabled_toolsets = ["cronjob"] (specialist)
    senão                            → enabled_toolsets = [] (normal chat slim)
  2 chamadores (background task + main message path) passam a mensagem.
```

## 2. Descobertas durante o wiring

```
- cron_router.py NÃO estava no package capability_intelligence do runtime
  (gate-0.5/src — deploy antigo) → DEPLOYADO (3048 B) + importável.
- Resolução via _get_platform_tools com platform_key adicionava kanban/bfl
  (recovery nativa da plataforma) — violaria o contrato "somente cronjob".
  → specialist retorna ["cronjob"] DIRETO (toolset registrado, resolve 1 tool).
- /cron (native built-in) continua determinístico, independente deste gate.
```

## 3. Validação (processo novo + live)

```
CRON_TOOLSETS=['cronjob'] · CRON_TOOLS=['cronjob'] (1 tool)   [contrato OK]
NORMAL_TOOLSETS=[] · NORMAL_TOOL_COUNT=0 · NORMAL_SCHEMA_BYTES=0  [slim OK]
Gate: "Todo dia as 8h me lembre de verificar as tarefas" → cron
      "oi" → normal
CANDIDATE_SHA (hermes-clean, branch prosperfy-cron-wiring)=d5ddcc63
Gateway restarted (single-bridge): PID 3351940 · NRestarts=0 · bridge :3000 (sessão reutilizada)
VERIFY_SLIM=PASS (NORMAL_CHAT_TOOLS=0, SCHEMA_BYTES=0, CAPABILITY_FAIL_CLOSED=PASS)
```

## 4. Estado Cron final

```
CRON_ROUTER_IMPLEMENTED=YES
CRON_SPECIALIST_IMPLEMENTED=YES
CRON_PRE_LLM_DISPATCH_WIRED=YES   ← fechado nesta execução
CRON_REAL_USER_PATH_ACTIVE=YES    (gate no dispatch real; mensagens temporais →
  sessão com toolset cronjob; /cron built-in; conceituais → normal 0 tools)
NORMAL_CHAT_ROUTER_LLM_CALLS=0 (gate determinístico, SEM classifier LLM)
FALSE_POSITIVE_CRON_LOW (V1 conservadora)
```

## 5. Notas

```
- O gate é pré-LLM e determinístico: nenhuma chamada LLM extra por turno.
- normal chat permanece 0 tools / 0 bytes (medido).
- Conversa cron (toolset cronjob) NÃO vaza tools legados/MCP (só o tool 'cronjob').
- Sem migration/DB/write capability. PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO.
- Repos: wiring em /home/will/.hermes/hermes-clean (branch prosperfy-cron-wiring,
  commit d5ddcc63); cron_router.py deploy no package do runtime (gate-0.5/src).
```