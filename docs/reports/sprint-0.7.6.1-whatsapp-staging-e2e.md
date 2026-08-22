# Sprint 0.7.6.1 — WhatsApp Staging E2E

> Resultado: root cause REFINADO com evidência real; canary staging BLOQUEADO por ausência de
> sessão/número WhatsApp staging (§3). Live intocado.

## 1. Baseline staging (candidate e47c7f77, sessão própria + porta 3001)

```
STAGING_HERMES_HOME=/tmp/wa-staging-home (sessao nova /tmp/wa-staging-session)
STAGING_BRIDGE_PORT=3001 (live 3000 intacto) · PATH com node v22.23.1
bridge deps do candidate ja presentes (scripts/whatsapp-bridge/node_modules, 119 modulos —
  instaladas pelo npm do cutover 0.7.5) → MISSING_BRIDGE_DEPS=NO

OBSERVADO (log real do candidate gateway):
  "[Whatsapp] WhatsApp is enabled but not paired (no creds.json at /tmp/wa-staging-session/creds.json)"
  "whatsapp failed to connect"
  "Gateway hit a non-retryable startup conflict: whatsapp: WhatsApp enabled but not paired"
  "Gateway exiting cleanly: ..."  → STAGING_RC=78
```

## 2. ROOT CAUSE REFINED (evidencia, nao hipotese)

```
BRIDGE_ROOT_CAUSE =
  1) PARING GATE (novo): candidate b6bcb3e7 REQUER sessao pareada (creds.json); se whatsapp
     enabled e nao pareado → conflito de startup NAO-retryable → gateway EXIT 78 limpo.
     (0.7.5 usou a sessao live → passou nesse gate; o exit 1 de 0.7.5 foi o caminho
     stranded após o bridge node morrer no readiness.)
  2) STARTUP_RACE/READINESS (confirmado 0.7.5): com sessao pareada, bridge node sobe mas
     nao aceitou no 1o poll → processo saiu → fatal retryable → handler upstream encerrou
     gateway (platform stranded).

REFUTADO (evidencia): BRIDGE_ENV hipotese de 0.7.6 — o candidate carrega ~/.hermes/.env
  (leitura de WHATSAPP_ENABLED confirmada no staging) e o subprocesso bridge herda os.environ;
  secret-scope/multiplexing NAO sao necessarios p/ sessao unica. SECRET_SCOPE_REQUIRED=NO,
  MULTIPLEXING_REQUIRED=NO.

BRIDGE_ROOT_CAUSE_IDENTIFIED=YES (classes: PARING_GATE + STARTUP_RACE/READINESS;
  causa exata do crash do node bridge requer sessao staging pareada p/ observacao E2E)
```

## 3. Bridge env / deps parity

```
WHATSAPP_ENV_KEYS: candidate le via os.getenv (env herdado + .env carregado) → OK single-profile
MISSING_BRIDGE_ENV=NO (single-profile) · MISSING_BRIDGE_DEPS=NO (119 modulos no candidate)
SECRET_SCOPE_REQUIRED_FOR_SINGLE_STAGING_SESSION=NO
MULTIPLEXING_REQUIRED_FOR_SINGLE_STAGING_SESSION=NO
```

## 4. Staging E2E — BLOQUEADO (§3)

```
Nao existe sessao/número WhatsApp staging no host (somente a sessao live).
Baseline staging confirmou que o bridge precisa de creds.json pareado para subir.
Usar a sessao live em staging = proibido (logout/conflito). 
STAGING_WHATSAPP_ACCOUNT_REQUIRED=YES
BASELINE_STAGING_BRIDGE_START=BLOCKED (pairing gate exit 78)
REAL_STAGING_E2E=BLOCKED · BRIDGE_READY/POLLER/GATEWAY_STABLE = NAO OBSERVAVEIS sem sessao staging
```

## 5. Live runtime (intocado)

```
LIVE_SHA=b54140f3 · LIVE_GATEWAY_ACTIVE=YES (PID 3331995, NRestarts=0)
LIVE_WHATSAPP_SESSION_UNTOUCHED=YES (creds.json presente) · LIVE_BRIDGE_PORT_UNTOUCHED=YES (3000)
verify_slim=PASS (0 tools, fail-closed) · CUTOVER_EXECUTED=NO · LIVE_WHATSAPP_OPERATIONAL=YES
CANARY_CLEANUP=PASS (staging home/session removidos)
```

## 6. Gate

```
SPRINT_0_7_6_1_FINAL_GATE=BLOCKED
RECUTOVER_READY=NO (falta: sessao staging pareada + E2E real + contract tests B1-B5)
RECOMMENDED_NEXT_ACTION:
  1) provisionar número/sessao WhatsApp staging (novo device, QR p/ staging somente);
  2) com sessao pareada: baseline staging → observar o crash do node bridge no readiness
     (se reproduz) → portar fix minimo (bounded readiness / retry conforme causa real);
  3) contract tests B1-B5 (mock bridge HTTP);
  4) E2E staging (bridge ready + poller + gateway stable + inbound/outbound 'Oi');
  5) so entao re-cutover (gate 0.7.6/0.7.6.1).
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
```