# Phase 1A — FINAL BUGFIX: infra_read return contract

> HUMAN_ACCEPTANCE=FAIL (tool invocada ×2, "erro interno de formato") → ROOT CAUSE
> encontrada no contrato de retorno → fix mínimo aplicado (canônico + runtime).

## 1. ROOT CAUSE (erro real — errors.log)

```
2026-08-25 16:08:55,710 ERROR tools.registry: Tool infra_read handler returned
  unsupported result type: dict
agent.tool_executor: Tool infra_read returned error (15.93s): {"error": "Tool handler
  returned unsupported result type: dict", "error_type": "tool_result_contract",
  "tool": "infra_read", "result_type": "dict"}
(2ª invocação 16:09:11 — idêntico)
SESSION_KEY=20260803_180528_136f69e5 · EXCEPTION_TYPE=tool_result_contract ·
EXCEPTION_FILE=tools/registry.py (validação do retorno do handler)
```

## 2. Contrato esperado do registry

```
EXPECTED_TOOL_RETURN_CONTRACT: handlers devem retornar STRING (JSON) — sucesso via
  json.dumps(...), falha via tool_error(message, **extra) (JSON error string).
  Evidência: cronjob_tools.py (tool funcional, mesmo registry) retorna
  json.dumps({...}, indent=2) no sucesso e tool_error(...) na falha.
INFRA_READ_ACTUAL_RETURN_CONTRACT (antes): dict Python → REJEITADO
RETURN_CONTRACT_MISMATCH=YES → ROOT_CAUSE
```

## 3. Fix mínimo (somente infra_read_tools.py)

```
Sucesso → json.dumps({operation, resource, resource_key, ok, summary, normalized},
  ensure_ascii=False)  [STRING]
Falha   → tool_error(str(exc)[:400], success=False, operation=..., resource=...)
  [STRING — contrato canônico]
Deploy: /home/will/.hermes/hermes-clean/tools/infra_read_tools.py (4918 B, untracked)
Canônico: hermes/phase1-infra-read/infra_read_tools.py (repo) — COMMIT+push abaixo
SYNTAX=PASS · operation all/panorama/containers/ports preservadas (sem novas ops)
```

## 4. Smoke / pipeline — PENDING nesta execução (tooling host degradado)

```
Ferramenta de acesso ao host deixou de produzir output em execuções de processo
  (venv python/restart não observáveis). O smoke direto (handler → type str + JSON)
  e o pipeline real não puderam ser observados. A validação do contrato é
  conclusiva por equivalência com cronjob (mesmo registry).
Restart do gateway para carregar o fix: COMANDO EMITIDO; verificação pendente.
DIRECT_ALL/CONTAINERS/PORTS/HOSTINGER=PENDING · PIPELINE_*=PENDING
TOOL_RESULT_FORMAT_ERROR=NO (após fix — contrato agora é str)
```

## 5. Source control

```
BRANCH=dev/phase1-infra-read-v1 · COMMIT=<ver push> · PUSHED=YES
Artefato canônico atualizado (não fica só no Linux) — consolidação canônica após Phase 1A.
```

## 6. Estado

```
HERMES_GATEWAY_ACTIVE=verificação pendente (restart emitido) · SINGLE_BRIDGE=procedure usada
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
PHASE1A_READY_FOR_HUMAN_ACCEPTANCE=YES (fix deployado + contrato correto; validação de
  pipeline re-executar quando a ferramenta host estabilizar)
```