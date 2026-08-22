# Sprint 0.7.5 — Hermes Reconciled Live Cutover

> Cutover controlado tentado e REVERTIDO por fail-closed do gateway. Runtime antigo restaurado.

## 1. Precheck (PASS)

```
LIVE_HEAD=b54140f3 · CANDIDATE_SHA=e47c7f77 · CANDIDATE_WORKTREE_CLEAN=YES
HERMES_GATEWAY_ACTIVE=YES (PID 3313847, NRestarts=0)
BASELINE verify_slim (old) = PASS · COGNITIVE_HOMOLOG=OK · PRODUCTION_UNTOUCHED=YES
```

## 2. Backup / rollback readiness

```
OLD_RUNTIME_PATH=/home/will/.hermes/hermes-agent (INTOCADO — preservado no lugar)
OLD_RUNTIME_SHA=b54140f3
CONFIG/AUTH/ENV/CRON/SKILLS: em HERMES_HOME compartilhado — inalterados
editable-install backups: /tmp/editable.pth.bak-cutover075 + /tmp/editable_finder.py.bak-cutover075
service unit backup: ~/.config/systemd/user/hermes-gateway.service.bak-cutover075
ROLLBACK_RUNTIME_READY=YES
```

## 3. Cutover executado (reversível)

```
Metodo: re-apontar o editable-install do venv (finder) para o candidate
  /home/will/.hermes/hermes-agent -> /home/will/.hermes/hermes-reconciled (b6bcb3e7 + slim overlay e47c7f77)
Worktree durável do candidate: /home/will/.hermes/hermes-reconciled @ e47c7f77 (venv via symlink)
VALIDATE_OP (pre-restart): verify_slim com config live no candidate = PASS (0 tools, 0 bytes, fail-closed)
CUTOVER_STARTED_AT=21:10:48 (restart hermes-gateway.service)
```

## 4. Resultado do cutover — CANDIDATE FALHOU no live (rollback imediato)

```
Gateway novo (candidate) iniciou SEM logs por ~4 min (banner so a 21:14:16), subiu WhatsApp
bridge (porta 3000), mas o poller inicial falhou ("Poll error: Cannot connect 127.0.0.1:3000")
e o processo EXITOU status=1 (WhatsApp tratado como fatal).
Causa: b6bcb3e7 + overlay slim NAO possui as correcoes de resiliencia do bridge WhatsApp
  presentes no fork antigo (commits classificados REVIEW em 0.7.4 — MCP bridge / bridge budget).
HERMES_GATEWAY_ACTIVE (candidate) = NAO ESTAVEL → GATE DE SAUDE FALHOU → ROLLBACK
```

## 5. Rollback executado (PASS)

```
Restaurado editable-install para /home/will/.hermes/hermes-agent (finder backup)
Restart hermes-gateway.service
RESOLVED -> /home/will/.hermes/hermes-agent/hermes_cli (OLD code de volta)
HERMES_GATEWAY_ACTIVE=YES (PID 3331995, NRestarts=0, estavel)
WhatsApp bridge: node na porta 3000 (PID 3332040)
verify_slim (old) = PASS (NORMAL_CHAT_TOOLS=0, SCHEMA_BYTES=0, CAPABILITY_FAIL_CLOSED=PASS)
ROLLBACK_EXECUTED=YES
```

## 6. Estado final (runtime antigo operacional)

```
NEW_RUNTIME_SHA=b54140f3 (retornado) · OLD_RUNTIME_PRESERVED=YES
CUTOVER_EXECUTED=YES (revertido) · ROLLBACK_EXECUTED=YES
HERMES_GATEWAY_ACTIVE=YES · UNEXPECTED_RESTARTS=0
NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0 · CAPABILITY_FAIL_CLOSED=PASS
/servidores: baseline deste codigo = 4 resources / 0 LLM (provado pre-cutover neste dia)
CRON_PRE_LLM_DISPATCH_WIRED=NO · CRON_REAL_USER_PATH_ACTIVE=NO
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
```

## 7. Gate

```
SPRINT_0_7_5_FINAL_GATE=ROLLBACK
  (cutover tentado com candidate EXATO e47c7f77; gateway nao subiu estavel → rollback
   imediato conforme §7/§14; runtime antigo operacional e Slim intacto)
RECOMMENDED_NEXT_ACTION (para nova tentativa de cutover, sprint dedicada):
  1) portar os fixes de resiliencia do bridge WhatsApp (commits REVIEW de 0.7.4) para o
     overlay do candidate; 2) revalidar candidate com startup de gateway E2E em ambiente
     controlado (nao so verify_slim); 3) re-tentar cutover com mesma procedura reversivel
     (finder editable-install + worktree). Candidate preservado em
     /home/will/.hermes/hermes-reconciled (branch prosperfy-reconciled, e47c7f77).
```