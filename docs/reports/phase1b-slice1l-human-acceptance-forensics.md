# Phase 1B — Slice 1L: Human Acceptance Forensics (resultado: CASE_A)

> Incidente ~20:38-20:39 local (23:38 UTC). READ-ONLY. Nenhuma mutação executada
> durante a forense. Conclusão: o restart NUNCA chegou ao MCP (evidência: audit
> vazio + journal Cognitive vazio + omniroute up 2 semanas).

## 1. Hermes logs (janela 20:38)

```
20:38:06 inbound "Reinicie o omniroute no Prosperfy." (Turn 1)
20:38:06 CAPABILITY_ROUTE=INFRA_ACTION ENABLED_TOOLSETS=['restart_container']
         FINAL_TOOL_NAMES=['restart_container'] SOURCE=WHATSAPP
20:38:19 tool restart_container completed (2.87s, 226 chars)   ← 1ª chamada confirmada
Turn 2 ("Sim") tool activity: tool_search (20:38:09/20:38:14), tool_describe,
  tool_call error "'infra_read' is not available" — o LLM tentou múltiplas ferramentas
HERMES_RESTART_TOOL_CALL_COUNT=1 (executor; o LLM requisitou ~5, mas só 1 passou)
CONFIRMED_CALLS_THAT_PASSED_PENDING=1 (a 1ª consumiu o pending; as demais → fail-closed)
```

## 2. Cognitive audit (RLS, janela 23:30–23:45 UTC)

```
WINDOW_ROWS=0 — NENHUMA execução infra.action no incidente
INFRA_ACTION_TODAY=6 (todas ANTES do incidente — testes/dry-run)
COGNITIVE_INFRA_ACTION_EXECUTIONS=0 · POLICY_VERDICT=N/A (não executou) ·
ADAPTER_INVOKED=NO (orquestrador nunca rodou)
```

## 3. Cognitive journal (janela)

```
-- No entries -- (nenhum request chegou ao serviço na janela)
```

## 4. MCP / container

```
MCP_RESTART_CALL_COUNT=0
OMNIROUTE_STATUS="Up 2 weeks (healthy)" · state=running · health=healthy
OMNIROUTE_STARTED_AT≈2 semanas antes do incidente · RESTART_OBSERVED=NO
POST_INSPECT_CALLED=NO (nenhum infra.inspect na janela — a post-condition do tool
  não chegou a rodar após uma execução válida)
```

## 5. Interpretação

```
A 1ª chamada confirmada (20:38:19) consumiu o pending + tentou _cognitive_restart →
  a requisição NÃO chegou ao orquestrador do Cognitive (audit vazio + journal vazio —
  falha de transporte/client ou request rejeitado fora do caminho auditado).
O LLM repetiu o restart_container (~5×) mas sem pending (fail-closed) → resposta final
  "não consegui concluir o reinício" (honesto — nada foi reiniciado).
OMNIROUTE_SELF_RESTART_INTERRUPTED_HERMES=NO (omniroute não reiniciou — uptime 2 semanas)
```

## 6. Classificação

```
CLASSIFICATION=CASE_A (restart NÃO chegou ao MCP)
ROOT_CAUSE=_cognitive_restart falhou ANTES do orquestrador do Cognitive (sem execução
  auditada nem request no journal). O pending foi consumido pela 1ª chamada; as demais
  foram retries fail-closed. Container intacto.
  (Causa exata do não-request: a investigar — possível falha de transporte do adapter
   em processo gateway, ou request rejeitado fora do caminho auditado — em execução
   dedicada, sem risco de mutação.)
```

## 7. Métricas

```
HERMES_RESTART_TOOL_CALL_COUNT=1 (executor) · CONFIRMED_PASSING_PENDING=1
COGNITIVE_INFRA_ACTION_EXECUTIONS=0 · ADAPTER_INVOKED=NO · MCP_RESTART_CALL_COUNT=0
OMNIROUTE_STATUS=Up 2 weeks (healthy) · RESTART_OBSERVED=NO
AUDIT_FOUND=NO (janela) · POST_INSPECT_CALLED=NO
OMNIROUTE_SELF_RESTART_INTERRUPTED_HERMES=NO · ROOT_CAUSE=_cognitive_restart pre-orchestrator
REAL_MUTATIONS_DURING_FORENSICS=0 · DB_CHANGED=NO · CODE_CHANGED=NO · DEPLOY_DONE=NO
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```