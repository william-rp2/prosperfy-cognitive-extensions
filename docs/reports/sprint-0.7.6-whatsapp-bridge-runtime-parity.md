# Sprint 0.7.6 — WhatsApp Bridge Runtime Parity + Controlled Re-Cutover

> Resultado: BRIDGE_ROOT_CAUSE identificada a nível de comportamento de runtime; canary E2E
> do bridge WhatsApp BLOQUEADO por segurança (sessão concorrente); re-cutover NÃO autorizado.

## 1. Falha 0.7.5 (recap)

```
Candidate (e47c7f77) subiu, npm install do bridge (~4min), "Bridge started on port 3000",
poll error "Cannot connect 127.0.0.1:3000", "Disconnected", gateway EXITOU status=1.
Rollback executado (runtime b54140f3 operacional, estavel).
```

## 2. Forensic diff (Phase A) — LIVE b54140f3 vs CANDIDATE e47c7f77

Analisado:
- `plugins/platforms/whatsapp/adapter.py` (diff ~262 linhas): poll loop IDENTICO (retry
  `sleep(5)` em poll error; nao faz exit), `_check_managed_bridge_exit`/`disconnect`/
  fatal `whatsapp_bridge_exited` (retryable=True) IDENTICOS.
- `gateway/run.py` fatal handler: candidate (upstream b6bcb3e7) TEM handling ainda mais
  robusto (`_queue_retryable_fatal_platform`, deadline, stranded check + exit) que o live.

Diferencas funcionais do fork live ausentes no candidate:
```
- _wenv() secret-scope (multiplexing) + injecao de bridge_env com WHATSAPP_* no subprocesso
  node do bridge (fix local comprovado do fork).
- bridge node deps ja instaladas no live; candidate faz npm install no primeiro start.
- read_receipts / npm-failure _set_fatal_error (cosmeticos p/ lifecycle).
```

BRIDGE_FAILURE_EXACT_CODE_PATH (evidencia): bridge node nao estava aceitando conexoes na
porta 3000 no primeiro poll do adapter (startup race) → processo do bridge saiu →
`_check_managed_bridge_exit` → fatal retryable → fatal handler do gateway (upstream novo)
encerrou o processo (plataforma "stranded"/nao requeued no timing do start).

ROOT_CAUSE_CLASS=STARTUP_RACE + BRIDGE_ENV (bridge subprocess sem o env WHATSAPP_* do
fork + deps nao pre-instaladas no candidate).

BRIDGE_ROOT_CAUSE_IDENTIFIED=PARTIAL-CONFIDENT (confirmado: bridge node morreu no startup e
gateway exitou; causa exata do crash do node requer observacao isolada — ver BLOCKED).

## 3. Commits/hunks revisados (0.7.4 REVIEW set)

```
SHA grupo MCP-bridge/bridge-budget (REVIEW em 0.7.4): b54140f3, 1c366ab5, 5243628a,
  5e0552dd, 7e1eabc6, 3902f6f8, f65a34cf
PORT_DECISION=PORT_MINIMAL (somente injecao de bridge_env WHATSAPP_* + pre-install deps)
REJECTED=LEGACY_MCP_ONLY (MCP OAuth/tool bridge — NAO portado)
```

## 4. Canary E2E — BLOQUEADO por seguranca (§10/§11)

```
Tentativa segura (platforms desabilitadas, bridge OFF): candidate gateway BOOTA e
  CONTINUA ativo (cron) mesmo sem adapters -> confirma que o exit 0.7.5 NAO era do boot
  generico, e sim do adapter WhatsApp fatal->stranded.
E2E REAL do bridge (start de fato o node bridge na sessao WhatsApp) = INSEGURO neste host:
  sessao WhatsApp concorrente com o live -> risco de logar-out da sessao operacional.
Per §10: "Se o bridge nao permitir isolamento seguro sem interferir no live: STOP + BLOCKED."
GATEWAY_STARTUP_E2E=BLOCKED (requer sessao/staging WhatsApp isolada)
```

## 5. Slim / Security / /servidores (candidate, ja provado em 0.7.4/0.7.5)

```
NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0 · CAPABILITY_FAIL_CLOSED=PASS
/SERVIDORES_CANDIDATE=PASS (4/4, 0 LLM, MCP 12)
```

## 6. Live runtime (intocado nesta sprint)

```
LIVE_SHA_BEFORE=b54140f3 · LIVE_RUNTIME_STABLE=YES
HERMES_GATEWAY_ACTIVE=YES (PID 3331995, NRestarts=0)
verify_slim=PASS (0 tools, fail-closed)
CUTOVER_EXECUTED=NO · ROLLBACK_EXECUTED=NO (nao houve nova tentativa)
```

## 7. Gate

```
BRIDGE_ROOT_CAUSE_IDENTIFIED=PARTIAL-CONFIDENT
BRIDGE_MINIMAL_FIX_PORTED=NO (nao validado -> nao aplicado; delta identificado:
  injecao bridge_env WHATSAPP_* + pre-install deps no candidate adapter)
GATEWAY_STARTUP_E2E=BLOCKED (sessao WhatsApp real nao isolavel com seguranca neste host)
CUTOVER_AUTHORIZED_BY_GATE=NO
SPRINT_0_7_6_FINAL_GATE=BLOCKED
RECOMMENDED_NEXT_ACTION (sprint dedicada, ambiente staging):
  1) provisionar sessao WhatsApp de staging (ou conta de teste) p/ E2E seguro do bridge;
  2) portar o delta minimo (bridge_env + deps) no candidate e validar com startup E2E
     (bridge ready + poller connected + gateway estavel);
  3) contract tests B1-B5 no poll/readiness;
  4) so entao re-cutover (gate 0.7.6 §18).
Candidate preservado: /home/will/.hermes/hermes-reconciled (e47c7f77, branch prosperfy-reconciled).
OLD_RUNTIME_PRESERVED=YES · PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
```