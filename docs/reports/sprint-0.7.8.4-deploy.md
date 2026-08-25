# Sprint 0.7.8.4 — DEPLOY (autorizado) — RESULTADO: PASS

> Patch memory-on-demand aplicado no runtime hermes-clean + restart single-bridge + validação.

## 1. Aplicação

```
Backup timestamped (20260825_142634): agent_init.py, system_prompt.py, gateway/run.py
  → /home/will/.hermes/backup-0784-deploy/ (3 arquivos)
PATCH_SHA256=be25a32d... (confirmado antes do apply)
git apply /tmp/0784.patch → APPLY_RC=0 (PASS)
git status pós-apply: 3 modificados (agent_init/system_prompt/gateway run) + .bak untracked
```

## 2. Pré-restart (validado)

```
SYNTAX_OK: agent/agent_init.py · agent/system_prompt.py · gateway/run.py (ast.parse)
RAW_MESSAGE_ROUTING_PRESENT=YES (9× 'message or ')
CAPABILITY_ROUTE_LOGGING_PRESENT=YES (CAPABILITY_ROUTE)
DETERMINISTIC_MEMORY_WRITE_PRESENT=YES (_maybe_execute_memory_write 2× + call 2×)
SNAPSHOT_FLAG=YES (_skip_memory_snapshot_in_prompt em agent_init)
IMPORT: agent.agent_init / agent.system_prompt / gateway.run importam (IMPORT_OK)
```

## 3. Restart single-bridge

```
stop hermes-gateway → bridge antigo 0 → start
HERMES_GATEWAY_ACTIVE=YES (MainPID 3887977) · NRESTARTS=0
BRIDGE_CONNECTED=YES (node 3888013, :3000) · SINGLE_BRIDGE=YES · QR_REQUIRED=NO (sessão reutilizada)
VERIFY_SLIM=PASS (NORMAL_CHAT_TOOLS=0 · SCHEMA_BYTES=0 · CAPABILITY_FAIL_CLOSED=PASS)
```

## 4. Memory snapshot fora do prompt (prova no código aplicado)

```
gateway/run.py: skip_memory_snapshot_in_prompt=True (3× — todas as construções de agente)
                skip_memory=True (3×) · invalidate_system_prompt (2× — bust de cache)
agent/system_prompt.py: gate `_memory_enabled and not _skip_memory_snapshot_in_prompt`
  → MEMORY.md OMITIDO do system-prompt volátil em TODAS as rotas de gateway:
  NORMAL_MEMORY_SNAPSHOT_IN_PROMPT=NO · CRON=NO · SESSION=NO · SKILLS=NO
  (a memória passa a ser acessada via a TOOL memory no turno MEMORY)
MEMORY_ROUTE_STORE_AVAILABLE=YES (memory toolset/ store carregam quando a rota MEMORY
  seleciona o toolset; skip_memory só desliga sync externo/snapshot)
NORMAL_CHAT_TOOL_COUNT=0 · NORMAL_CHAT_SCHEMA_BYTES=0 (preservado — verify PASS)
```

## 5. Gate final

```
DEPLOY_GATE=PASS
CODE_CHANGED=YES (patch aplicado) · GATEWAY_RESTARTED=YES (single-bridge)
MEMORY_CHANGED=NO (MEMORY.md intacto, 1917 chars — não consolidado) · LIMIT não alterado
ROUTING inalterado · DETERMINISTIC_MEMORY_WRITE inalterado
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
Nota: o apply_memory_on_demand.sh/verify_memory_on_demand.py não puderam ser extraídos do
  repo (clone git sem working-tree + flakiness do git show/cat-file no host); o deploy foi
  executado manualmente replicando os passos do script (backup + git apply + verify + restart).
  A validação equivalente foi feita (syntax, markers, verify_slim, prova de código do flag).
```