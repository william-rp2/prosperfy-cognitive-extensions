# Phase 1B — Slice 1M: Exact Pre-Orchestrator Diagnosis

> Baselin: `dev/phase1b-restart-container` @ `2b99514`. READ-ONLY. Nenhuma mutação.
> Suplantação da hipótese do 1L ("pre-orchestrator transport"): a causa exata é o
> **roteamento do turno de confirmação**.

## 1. Timeline exata (logs brutos, 20:37:30–20:40:30 America/Sao_Paulo)

| TIME (local) | TURN | EVENT | TOOL | CONFIRMED | RESOURCE | CONTAINER | RESULT |
|---|---|---|---|---|---|---|---|
| 20:38:06 | 1 | inbound "Reinicie o omniroute no Prosperfy." | — | — | — | — | — |
| 20:38:06 | 1 | CAPABILITY_ROUTE=INFRA_ACTION FINAL_TOOL_NAMES=['restart_container'] | — | — | — | — | — |
| 20:38:09 | 1 | tool_search completed (429 chars) | tool_search | — | — | — | ok |
| 20:38:11 | 1 | tool_describe completed (780 chars) + tool_call error "infra_read not available" | tool_describe/tool_call | — | — | — | err |
| 20:38:14 | 1 | tool_search completed (416 chars) | tool_search | — | — | — | ok |
| 20:38:19 | 1 | **restart_container completed (2.87s, 226 chars)** | restart_container | **false** | Prosperfy→prosperfy-vps-homolog | omniroute | pending criado + "confirmação necessária" |
| 20:38:20 | 1 | Turn ended (response_len=101) | — | — | — | — | pediu confirmação (PASS) |
| 20:39:31 | 2 | inbound "Sim" | — | — | — | — | — |
| 20:39:31 | 2 | **CAPABILITY_ROUTE=NORMAL ENABLED_TOOLSETS=[] FINAL_TOOL_NAMES=[]** | — | — | — | — | **nenhuma tool** |
| 20:39:31 | 2 | conversation turn (history=25) | — | — | — | — | — |
| 20:39:46 | 2 | Turn ended: api_calls=1, **tool_turns=9 (inalterado), NENHUM tool event** | — | — | — | — | response_len=185 (narrativa sem execução) |

```
TURN1_RESTART_CONTAINER_CALLS=1 (executor) · TURN1_CONFIRMED_VALUES=[false]
TURN2_RESTART_CONTAINER_CALLS=0 (executor) · TURN2_CONFIRMED_VALUES=[—] (nenhuma chamada passou;
  LLM não tinha a tool — FINAL_TOOL_NAMES=[])
```

**Fato-chave:** o `restart_container completed @20:38:19` foi o **TURNO 1** (confirmed=false → cria
pending → pede confirmação). O Turno 2 NÃO executou nenhuma tool (api_calls=1, sem eventos de tool;
o `tool_turns=9` ficou inalterado). A resposta 185 chars ("a chamada de execução não retornou
resultado do servidor") foi narrativa do LLM SEM execução subjacente.

## 2. Pending

```
PENDING_CREATED_AT=2026-08-26 20:38:19 (Turno 1, restart_container confirmed=false)
PENDING_KEY=actor|resource|container (formato do tool: _pending_key(actor, resource_key, container));
  actor=hermes-homolog (svc._adapter._actor_id), resource=prosperfy-vps-homolog, container=omniroute
PENDING_PRESENT_BEFORE_TURN2=YES (processo gateway não reiniciou; nenhum confirmed=true jamais popou)
PENDING_POPPED_AT=NOT_OBSERVABLE (nunca houve confirmed=true no handler)
PENDING_POPPED_BY_CONFIRMED=NO · PENDING_POP_PROVEN=NO (nenhum confirmed=true chegou; pop nunca ocorreu;
  pending segue em memória até TTL — estado in-memory, não auditável sem instrumentação)
```

## 3. Raw result do Turno 2

```
TURN2_TOOL_RAW_RESULT=NOT_OBSERVABLE (nenhuma tool executou no Turno 2)
TURN2_RAW_RESULT_OBSERVABLE=NO · TURN2_EXCEPTION_TYPE=N/A · TURN2_EXCEPTION_MESSAGE_SANITIZED=N/A
```

## 4. Transporte (adapter REAL, env runtime, read-only)

```
READ_CAPABILITIES=N/A (CognitiveApiAdapter não expõe list_capabilities; não é falha de transporte)
READ_RESOURCES=PASS (n=4)
READ_INFRA_INSPECT=PASS (success=True; audit infra.inspect pol=allow out=completed tool_calls=3)
```

## 5. POST /infra.action negativo (action=start — fail-closed comprovado no orquestrador LIVE)

```
HTTP_POST_REACHED_COGNITIVE=YES
POST_NEGATIVE_RESULT=RuntimeError "Capability 'infra.action' falhou: action 'start' não permitida -
  somente 'restart'." (ForbiddenArgumentError do _build_infra_action_restart_plan, orchestrator.py:86)
COGNITIVE_EXECUTION_OR_AUDIT_CREATED=YES (audit: pol=allow out=failed res=erro 'start')
MCP_INVOKED=NO (bloqueio no plan builder — nenhuma tool_calls no audit)
REAL_RESTART_EXECUTED=NO
```

## 6. Process context

```
TOOL_EXECUTION_THREAD=worker thread (ThreadPoolExecutor; registry.py:1152 chama handler sync)
RUNNING_EVENT_LOOP=NO (worker thread, handler síncrono — sem loop ativo)
ASYNCIO_RUN_SAFE=YES (asyncio.run em _cognitive_restart cria loop novo no worker thread)
```

## 7. Decisão

```
ROOT_CAUSE=O Turno 2 ("Sim") foi roteado CAPABILITY_ROUTE=NORMAL com FINAL_TOOL_NAMES=[]
  — a toolset INFRA_ACTION/restart_container NÃO foi habilitada no turno de confirmação.
  O router casa keywords na MENSAGEM CORRENTE; "Sim." não casa nenhuma keyword → sem tools →
  confirmed=true nunca chegou ao handler → zero request ao Cognitive/MCP.
ROOT_CLASSIFICATION=ROOT_A (confirmed=true não chegou ao handler real)
  [causa exata comprovada: roteamento do turno de confirmação; NÃO é transporte, NÃO é pending-match,
   NÃO é asyncio, NÃO é Cognitive, NÃO é MCP — todos descartados pelas evidências acima]
```

## 9. Fix (proposto — NÃO implementado nesta slice)

```
FIX_LOCATION=hermes/capability_router.py (routing do turno de confirmação)
FIX_SCOPE=hermes-side apenas (Cognitive/MCP/guard provados OK — sem alteração fora do router);
  mínimo: herdar toolset do turno anterior quando a sessão tem intenção/pending ativo.
FIX_DESCRIPTION=No turno seguinte da MESMA sessão, se o texto for confirmação (sim/sim./confirmo/
  pode/ok/confirma) e existir intenção/pending de restart na sessão, reaplicar a rota INFRA_ACTION
  (FINAL_TOOL_NAMES=['restart_container']) em vez de NORMAL. Assim o confirmed=true chega ao handler
  e o fluxo executa normalmente (transporte+guard provados OK no teste negativo).
```

## 11. Métricas finais

```
TURN1_RESTART_CONTAINER_CALLS=1 · TURN1_CONFIRMED_VALUES=[false]
TURN2_RESTART_CONTAINER_CALLS=0 · TURN2_CONFIRMED_VALUES=[—]
PENDING_CREATED_AT=20:38:19 · PENDING_PRESENT_BEFORE_TURN2=YES · PENDING_POP_PROVEN=NO
TURN2_TOOL_RAW_RESULT=NOT_OBSERVABLE · TURN2_EXCEPTION_TYPE=N/A
READ_CAPABILITIES=N/A · READ_RESOURCES=PASS · READ_INFRA_INSPECT=PASS
HTTP_POST_REACHED_COGNITIVE=YES · POST_NEGATIVE_RESULT=ForbiddenArgumentError(start) · MCP_INVOKED=NO
REAL_RESTART_EXECUTED=NO
TOOL_EXECUTION_THREAD=worker-thread(sync) · RUNNING_EVENT_LOOP=NO · ASYNCIO_RUN_SAFE=YES
ROOT_CAUSE=roteamento NORMAL no turno de confirmação (FINAL_TOOL_NAMES=[]) · ROOT_CLASSIFICATION=ROOT_A
FIX_LOCATION=hermes/capability_router.py · FIX_SCOPE=hermes-side (routing) · FIX_DESCRIPTION=acima
REAL_MUTATIONS=0 · CODE_CHANGED=NO · DB_CHANGED=NO · DEPLOY_DONE=NO
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
STOP.
```