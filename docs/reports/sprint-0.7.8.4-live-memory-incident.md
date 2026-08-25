# Sprint 0.7.8.4 — LIVE MEMORY INCIDENT (diagnóstico + rollback)

> Usuário recebeu "Sorry, I encountered an unexpected error" após "Lembre que MEMORY_TEST_0782
> = SIRIUS." imediatamente após o deploy 0.7.8.4. ROOT CAUSE encontrada + rollback executado.

## 1. Localização da interação (logs reais)

```
MESSAGE_TIMESTAMP=2026-08-25 14:45:14 (agent.log:16953 inbound 'Lembre que MEMORY_TEST_0782 = SIRIUS.')
SESSION_KEY=20260803_180528_136f69e5
GATEWAY_PID (pós-deploy)=3887977 → pós-rollback 3891249
MEMORY_WRITE_DETERMINISTIC=True content='MEMORY_TEST_0782 = SIRIUS.' result_success=True
  (agent.log:16958 — o WRITE FUNCIONOU ANTES do erro)
MEMORY_TEST_0782_FOUND=YES (grep SIRIUS/MEMORY_TEST_0782 em MEMORY.md = 1)
MEMORY_CHARS: 1917 → 1946 (o write do SIRIUS persistiu conteúdo)
```

## 2. Stack trace real (errors.log 8897-8919)

```
TypeError: AIAgent.__init__() got an unexpected keyword argument 'skip_memory_snapshot_in_prompt'
  gateway/run.py:20167 _handle_message_with_agent → _run_agent → _run_agent_inner
  → run.py:5753 `agent = ctx.AIAgent(...)` (construção do agente do turno)
EXCEPTION_TYPE=TypeError · EXCEPTION_FILE=gateway/run.py · EXCEPTION_LINE=5753
```

## 3. Classificação

```
CAPABILITY_ROUTE=MEMORY (deterministic write executado) · FINAL_TOOL_NAMES=N/A (erro antes do run)
FAILURE_BOUNDARY=D (AIAgent init — construção do agente do turno)
ROOT_CAUSE: patch 0784 adicionou skip_memory_snapshot_in_prompt=True às construções de
  agente no run.py, incluindo uma chamada DIRETA `ctx.AIAgent(...)` (run.py:5753).
  AIAgent.__init__ NÃO aceita esse kwarg — o patch adicionou o parâmetro apenas ao
  `init_agent` (agent/agent_init.py), não ao construtor do AIAgent.
FAILURE_INTRODUCED_BY_0784=YES (regressão do patch — comprovada pelo TypeError)
```

## 4. Rollback (autorizado §8 — runtime quebrado por 0784)

```
Restaurado de /home/will/.hermes/backup-0784-deploy (timestamp 20260825_142634):
  agent/agent_init.py · agent/system_prompt.py · gateway/run.py
Confirmado pós-rollback: _skip_memory_snapshot_in_prompt=0 (agent_init) ·
  skip_memory_snapshot_in_prompt=0 (run.py) · _maybe_execute_memory_write=2 (0.7.8.2 PRESERVADO)
Restart single-bridge: stop → old bridge 0 → :3000 livre → start
HERMES_GATEWAY_ACTIVE=YES (MainPID 3891249) · BRIDGE_CONNECTED=YES (:3000, node 3891311)
SINGLE_BRIDGE=YES · NRESTARTS=0 · VERIFY_SLIM=PASS (0 tools · 0 bytes · fail-closed)
```

## 5. Estado final

```
ROLLBACK_REQUIRED=YES · ROLLBACK_EXECUTED=YES
MEMORY_CHANGED_MANUALLY=NO (SIRIUS persistiu via write determinístico do Hermes — não toquei)
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
FINAL_STATUS=ROLLED_BACK
MINIMAL_FIX (para re-aplicar 0784 no futuro): mover o flag para AIAgent.__init__ aceitar
  skip_memory_snapshot_in_prompt (e definir agent._skip_memory_snapshot_in_prompt), ou
  NÃO passar o kwarg em ctx.AIAgent(...) e garantir que todas as construções passem por
  init_agent — a validar em ambiente antes de re-deploy.
```