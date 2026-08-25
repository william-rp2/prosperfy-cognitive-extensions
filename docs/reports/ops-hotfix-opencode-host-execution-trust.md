# OPS HOTFIX — OpenCode Host Execution Trust (resultado: PASS)

> Canal de execução srv1631152 diagnosticado + corrigido. Root cause da perda de
> confiança encontrada e prova observada de reload real.

## 1. ROOT CAUSE (evidência)

```
O tool `prosperfy_vps_executar` (ProsperfySkills MCP) REJEITA comandos destrutivos/
de sistema SEM `confirmar:true`:
  → TOOL_ERROR: "Comando destrutivo requer confirmação ... chame novamente com confirmar=true."
  → o comando NÃO executa (ex.: `systemctl --user stop` sem confirmar = gateway continuou ativo).
O helper de parse (mcp_call.ps1) lia APENAS `structuredContent.data.stdout` → o TOOL_ERROR
  era DESCARTADO → "(no output)" → interpretado como "canal quebrado" quando na verdade
  era "comando rejeitado".
Efeito colateral: chains com pipes (`|`) ou multi-propriedade podem truncar o stdout à
  primeira linha → usar comandos simples/separados p/ pós-condições.
```

## 2. Canal documentado

```
OPENCODE_HOST_TOOL=ProsperfySkills MCP `prosperfy_vps_executar`
EXECUTION_PATH=OpenCode → mcp_call.ps1 (curl, SSE) → skills.prosperfy.com.br/mcp →
  VPS adapter → srv1631152 (user will, uid 1000, /bin/bash, /home/will)
XDG_RUNTIME_DIR=/run/user/1000 · DBUS=unix:path=/run/user/1000/bus · Linger=yes
```

## 3. FIX aplicado

```
mcp_call.ps1 reescrito p/ SEMPRE expor NORM_STATUS / NORM_STDOUT / NORM_STDERR / NORM_ERR
  (fail-closed — nunca "(no output)" silencioso).
Regra operacional: TODO comando de estado → `confirmar:true`; pós-condição observada em
  comando SEPARADO após o efeito (STALE_EVIDENCE_GUARD).
```

## 4. Prova observada (somente evidência pós-comando)

```
READ_ONLY_SMOKE=PASS (date/hostname/whoami/id/pwd/env/systemd/loginctl/gateway — stdout real)
FILE_MUTATION_SMOKE=PASS (create+read /tmp → FILE_OBSERVED; rm confirmar → FILE_REMOVED)
USER_SYSTEMD_SMOKE=PASS (systemd-run --user --wait opencode-exec-smoke → Result=success)
HERMES_OLD_PID=3921079 (antes)
HERMES_STOP_OBSERVED=YES (stop confirmar:true → MainPID=0)
PORT_3000_FREE_AFTER_STOP=YES (ss sem listeners)
HERMES_NEW_PID=3927862 (≠ OLD — reload real) · ActiveState=active · SubState=running
PORT_3000_LISTEN_AFTER_START=YES (bridge node 3927897) · SINGLE_BRIDGE=YES
STALE_EVIDENCE_GUARD=PASS (todas as pós-condições observadas DEPOIS do comando respectivo)
```

## 5. Decisão

```
OPENCODE_HOST_EXECUTION_TRUST=PASS
  (canal funciona; o gap era parse que descartava TOOL_ERROR + confirmar:true ausente;
   corrigido e provado com reload real do Hermes observado).
Próximo passo autorizado: retomar Phase 1A (RAW do Black) — agora com observação confiável
  (confirmar:true + NORM parse + pós-condições separadas).
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```