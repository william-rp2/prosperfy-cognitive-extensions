# Human Acceptance 0.7.8 — Log Audit

> Auditoria APENAS (sem alteração de código). Correlação pelas mensagens/timestamps
> reais do WhatsApp nos logs existentes (agent.log / gateway.log).

## 1. Interações reais encontradas (inbound confirmado nos logs)

| TS | MESSAGE | ROUTE (runtime) | EVIDÊNCIA |
|---|---|---|---|
| 00:29:51 | "Oi" | NORMAL | API call #1 in=59078 · tool_turns=103 · stop |
| 00:30:08 | "Lembre que meu código de teste é ORION-78." | NORMAL (runtime) | API #2 in=59110 (≈base+32) · tool_turns=103 · stop |
| 00:30:27 | "O que decidimos antes sobre o Browser Harness?" | NORMAL (runtime) | API #3 in=59189 · tool_turns=103 · stop |
| 00:30:55 | "Obrigado" | NORMAL | API #4 in=59263 · tool_turns=103 · stop |
| 00:34:56 | "Qual código de teste do Hermes eu pedi para você lembrar?" | NORMAL | API #5 in=59288 · tool_turns=103 · stop |
| 00:35:07 | "Quais skills você tem disponíveis?" | NORMAL (runtime) | (mesmo padrão; ver agent.log) |

## 2. Evidência de NENHUMA tool no runtime

```
TODOS os turnos: api_calls=1 · finish_reason=stop · tool_turns=103 INALTERADO
  (contador cumulativo da sessão — nunca incrementou).
Input tokens ≈ base (59078 → 59110/59189/59263/59288 — + apenas o comprimento da
  mensagem). Se uma tool estivesse no request, o input subiria pelo schema:
  memory≈3181B (~+800 tok), session_search≈7052B, skills≈5664B. NÃO subiu.
→ NENHUMA tool foi enviada ao modelo em NENHUM turno (FINAL_TOOL_NAMES=[] runtime).
```

## 3. Roteamento lógico (host) vs runtime

```
Router (capability_router, deployado) classifica corretamente as mensagens do usuário:
  "Lembre que meu código de teste é ORION-78."         → MEMORY
  "O que decidimos antes sobre o Browser Harness?"      → SESSION_SEARCH
  "Quais skills você tem disponíveis?"                  → SKILLS
  "Obrigado" / "Oi"                                     → NORMAL
MAS no runtime o router retornou NORMAL (sem tools na API).
ROOT CAUSE (evidência de código): o caller do gateway passa `channel_prompt or
  context_prompt` como "message" — no caminho WhatsApp isso NÃO é o texto cru do
  usuário (provavelmente vazio/formatado) → o router recebe ""/texto errado → NORMAL.
→ o texto do turno não está chegando ao gate pré-LLM no caminho WhatsApp.
```

## 4. Gap adicional de routing (phrasing)

```
"Qual código de teste do Hermes eu pedi para você lembrar?" → NORMAL (deveria ser
  MEMORY read). _MEMORY_READ não cobre "pedi para você lembrar" (só "você lembra"/
  "você se lembra"/"o que você sabe sobre"). FALSO NEGATIVO de memory-read.
```

## 5. Resultado por campo

```
"Oi"                      → ROUTE=NORMAL · FINAL_TOOL_NAMES=[] · TOOL_INVOKED=none · result=NONE
Memory write ORION-78      → ROUTE=?? runtime NORMAL · FINAL_TOOL_NAMES=[] · TOOL_INVOKED=none
                            (MEMORY esperado; memória NÃO persistiu — sem tool)
Session Search Browser Harness → runtime NORMAL · FINAL_TOOL_NAMES=[] · TOOL_INVOKED=none
Skills                     → runtime NORMAL · FINAL_TOOL_NAMES=[] · TOOL_INVOKED=none
"Obrigado"                 → ROUTE=NORMAL · FINAL_TOOL_NAMES=[] · TOOL_INVOKED=none
RESPONSE: lengths reais 34/37/99/8/55 chars — texto NÃO presente nos logs do gateway
  (apenas tamanho) → INTERNAL_NAMES_EXPOSED_TO_USER=NOT_OBSERVABLE_FROM_EXISTING_LOGS
ROUTE por turno: NOT_OBSERVABLE diretamente (router silencioso) — INFERIDO NORMAL pela
  ausência de schemas na API.
CARRIED_OVER: N/A (nenhuma tool foi ativada em turno algum; normais seguem sem tools).
NORMAL_CHAT_TOOL_COUNT=0 · SCHEMA_BYTES=0: CONFIRMADO (sem schemas na API dos turnos).
```

## 6. Veredito

```
HUMAN_ACCEPTANCE_LOG_AUDIT=PARTIAL
  ROUTING LÓGICO = PASS (router classifica corretamente as mensagens do usuário)
  ATIVAÇÃO DE TOOL NO LIVE = FAIL (mensagem não chega ao router no caminho WhatsApp →
    FINAL_TOOL_NAMES=[] em todos os turnos especialistas)
  + 1 falso negativo de MEMORY read (phrasing "eu pedi para você lembrar")
Evidência que falta para PASS: (a) turnos com tool schemas na API; (b) tool_turns
  incrementando; (c) persistência/resultado real da memory/session/skills tool.
PRÓXIMO PASSO (fora do escopo do audit, sem tocar nada agora): corrigir o wiring do
  gateway p/ passar o TEXTO CRU da mensagem (event.text) ao router no caminho WhatsApp,
  e ampliar _MEMORY_READ p/ "pedi para você lembrar"/"eu pedi para você lembrar".
```

## 7. Estado runtime (durante o audit)

```
HERMES_GATEWAY_ACTIVE=YES (PID 3355346 · NRestarts=0) · bridge :3000 · sem alteração
PRODUCTION_UNTOUCHED=YES · SECRET_EXPOSED=NO · MASTER_UNTOUCHED=YES
```