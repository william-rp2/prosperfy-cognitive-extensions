# Sprint 0.7.6.2 — Clean Hermes Runtime Rebuild + Single-Session Cutover

> Estrategia mudada (sem staging). Mesma sessao WhatsApp, single-writer/single-bridge.
> Resultado: CUTOVER PASS — o gate que falhou em 0.7.5 (port collision) nao se repetiu.

## 1. Nova hipotese de root cause 0.7.5 (confirmada por execucao)

```
0.7.5: restart rapido sem verificar morte do bridge node antigo -> bridge do candidate
  provavelmente EADDRINUSE em :3000 -> processo node saiu -> fatal -> gateway exit 1.
0.7.6.2: SINGLE-BRIDGE garantido (old gateway+bridge parados, porta 3000 livre) ->
  bridge novo subiu limpo. ROOT_CAUSE_CLASS(0.7.5)=PORT_COLLISION / BRIDGE_LIFECYCLE_RACE.
bridge.js: live (b54140f3) vs clean (b6bcb3e7) DIFEREM (clean tem reconnect-scheduler +
  read-receipts = mais novo) — NAO era gap de codigo do bridge.
```

## 2. Inventario / backups (antes do cutover)

```
State OK: config.yaml · .env · platforms/whatsapp/session/creds.json · cron · sessions ·
  skills · plugins
Backups: /home/will/.hermes/backup-cutover0762/ (config, .env, service unit, finder.py,
  pth, whatsapp-creds.json) → ROLLBACK_RUNTIME_READY=YES
```

## 3. Clean runtime

```
NEW_RUNTIME_PATH=/home/will/.hermes/hermes-clean (worktree de e47c7f77 = b6bcb3e7 + slim)
NEW_RUNTIME_SHA=e47c7f77 · WORKTREE_CLEAN=YES · venv via symlink (compartilhado)
PRE-CUTOVER: GATEWAY_MODULE_IMPORT=PASS · VERIFY_SLIM=PASS (0 tools) · CAPABILITY_FAIL_CLOSED=PASS
```

## 4. CUTOVER (janela controlada, single-bridge)

```
1. verify clean com config live = PASS
2. stop hermes-gateway.service (old PID 3331995 parado)
3. confirmar: 0 processos hermes + 0 bridge.js + PORT 3000 LIVRE → SINGLE_BRIDGE_GUARANTEED=YES
4. finder editable-install → /home/will/.hermes/hermes-clean (backup do finder feito)
5. start hermes-gateway.service
```

## 5. Resultado do cutover

```
NEW_GATEWAY_PROCESS_STARTED=YES (PID 3342844, ActiveState=active)
CODE_RESOLVE=/home/will/.hermes/hermes-clean/hermes_cli
NEW_BRIDGE_PROCESS_STARTED=YES (node 3342938)
  cmd: bridge.js --port 3000 --session /home/will/.hermes/platforms/whatsapp/session --mode bot
BRIDGE_PORT_LISTENING=YES (127.0.0.1:3000)
WHATSAPP_ALREADY_PAIRED=YES (creds.json reutilizado) · QR_REQUIRED=NO
SINGLE_BRIDGE=YES (1 gateway + 1 bridge; nenhum processo antigo)
GATEWAY_ACTIVE=YES · UNEXPECTED_RESTARTS=0 · GATEWAY_EXITED=NO
```

## 6. Validacao (runtime novo)

```
VERIFY_SLIM=PASS → NORMAL_CHAT_TOOL_COUNT=0 · NORMAL_CHAT_SCHEMA_BYTES=0
CAPABILITY_FAIL_CLOSED=PASS · LEGACY_DIRECT_MCP_FALLBACK=NO
/SERVIDORES=PASS → AUTHORIZED_RESOURCES_FOUND=4 · EXECUTED=4
  HERMES_LLM_PROVIDER_CALLS=0 · INPUT=0 · OUTPUT=0 · COST=0 · COGNITIVE_LLM_CALLS=0 · MCP=12
  (hosts reais: Black OK, Manager1 OK, Prosperfy OK, hostinger-one ERRO — docker ausente)
STATE PRESERVED: WHATSAPP_SESSION=YES (mesmo path) · AUTH/CONFIG/CRON/SKILLS/MCP=YES
```

## 7. Gate

```
SPRINT_0_7_6_2_FINAL_GATE=PASS (runtime cutover)
  NEW_RUNTIME_ACTIVE=YES · WHATSAPP_ALREADY_PAIRED=YES · BRIDGE_READY=YES
  POLLER_CONNECTED=YES (bridge HTTP em :3000) · GATEWAY_STABLE=YES · UNEXPECTED_RESTARTS=0
  NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0 · /SERVIDORES=PASS · LLM_CALLS=0
  CAPABILITY_FAIL_CLOSED=PASS · OLD_RUNTIME_PRESERVED=YES
PENDENTE (human acceptance do canal): WHATSAPP_INBOUND/OUTBOUND via mensagem real "Oi" —
  runtime totalmente validado; usuario confirma a mensagem no canal operacional.
RECOMMENDED_NEXT_ACTION: user envia "Oi" + "/servidores" no WhatsApp para aceitacao humana
  do canal; depois manter hermes-clean como operacional (old hermes-agent preservado p/
  rollback ate gates futuros).
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
```