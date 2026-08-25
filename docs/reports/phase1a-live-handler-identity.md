# Phase 1A — LIVE HANDLER IDENTITY (resultado: READY_FOR_USER_TEST=NO)

> 16:23 ainda retorna tool_result_contract. Prova: o fix está no disco, mas o
> processo live NÃO foi recarregado. Observação de registry/executor impossível
> nesta sessão (ferramenta de acesso ao host sem output para execução).

## 1. Erro 16:23 (errors.log — atual)

```
8971: 2026-08-25 16:23:28,895 ERROR tools.registry: Tool infra_read handler
  returned unsupported result type: dict
8972: WARNING agent.tool_executor: Tool infra_read returned error (13.47s):
  {"error": "Tool handler returned unsupported result type: dict",
   "error_type": "tool_result_contract", "tool": "infra_read", "result_type": "dict"}
CURRENT_1623_ERROR=tool_result_contract (dict) — MESMO boundary do 16:08.
```

## 2. Handler no disco (runtime) — CORRETO (file ops observáveis)

```
/home/will/.hermes/hermes-clean/tools/infra_read_tools.py:
  def infra_read(...) -> str
  success → return json.dumps({...}) (linhas 94/103)
  failure → return tool_error(...) (linha 111)
  handler=lambda args, **kw: infra_read(...) (linha 134)
Só UMA cópia do arquivo (find em hermes-clean/gate-0.3/0.4/0.5) → DUPLICATE_HANDLER=NO
WRONG_MODULE_LOADED=N/A (uma única fonte em disco)
```

## 3. Por que o live AINDA retorna dict — PROVA

```
MainPID INALTERADO (3897783) após restart emitido → o gateway NÃO recarregou.
O processo live foi iniciado ANTES do deploy do fix (ou o restart não executou de
forma observável nesta sessão) → o handler carregado em memória é o PRÉ-fix (dict).
ROOT_CAUSE (persistência do erro) = GATEWAY NÃO RECARREGADO com o handler corrigido.
  (Não é duplicata; não é arquivo errado; não é o tool_error — o handler em disco retorna str.)
```

## 4. Por que não posso marcar READY_FOR_USER_TEST

```
Regra estrita: READY_FOR_USER_TEST=YES somente com PIPELINE_ALL_SERVERS executado e
  OBSERVADO após o fix. A ferramenta de acesso ao host não retorna output de execução
  de processo (registry/executor/pipeline não observáveis) — não é "equivalência",
  é impossibilidade técnica de observação nesta sessão.
```

## 5. Ação necessária (quando a ferramenta host voltar)

```
1. Restart single-bridge OBSERVADO (stop → old dead → :3000 livre → start → PID novo)
2. Handler identity via registry real (co_filename + fonte carregada + sha)
3. Execução real via registry: containers/Prosperfy, ports/Black, all
4. Pipeline real "Como estão meus servidores?" OBSERVADO
5. Só então READY_FOR_USER_TEST=YES
```

## 6. Métricas

```
CURRENT_1623_ERROR=tool_result_contract (dict) · HANDLER_SOURCE_FILE=correta no disco
DUPLICATE_HANDLER=NO · WRONG_MODULE_LOADED=N/A · TOOL_ERROR_RETURN_TYPE=str (código)
ROOT_CAUSE=gateway não recarregado com o handler corrigido
MINIMAL_FIX=reload observado (single-bridge) — já feito o deploy do handler correto
REGISTRY_*/PIPELINE_*=NÃO OBSERVADOS (tooling) · TOOL_RESULT_CONTRACT_ERROR=presente até reload
READY_FOR_USER_TEST=NO (regra estrita) · PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```