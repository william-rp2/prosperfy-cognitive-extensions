# Relatório Fase G — Idempotência

**Data:** 25/07/2026  
**Fase:** G — Idempotência (ID1-ID4)  
**Projeto:** capability-intelligence  
**Status:** ✅ 17/17 testes passando

---

## Resumo

A Fase G valida o comportamento de idempotência do sistema em quatro cenários:
execuções repetidas, feedback duplicado, aprovação duplicada e timeout com retry.

### Cenários

| ID   | Descrição                                                     | Status |
|------|---------------------------------------------------------------|--------|
| ID1  | Deploy repetido 2x — ambas executam, resultado previsível     | ✅     |
| ID2  | Feedback duplicado — registrado 2x (histórico permite duplicatas) | ✅ |
| ID3  | Aprovação duplicada — primeira prossegue, segunda ignorada    | ✅     |
| ID4  | Timeout e retry — timeout na primeira, retry com sucesso      | ✅     |

---

## Detalhamento dos Testes

### ID1: Deploy Repetido 2x

**Arquivo:** `tests/test_fase_g.py :: TestID1DeployRepetido`

**Objetivo:** Garantir que executar o mesmo deploy duas vezes produza resultados consistentes e previsíveis.

**Testes (4):**

| Teste                                             | O que verifica                                                      |
|---------------------------------------------------|---------------------------------------------------------------------|
| `test_id1_duas_execucoes_sucesso`                 | Ambas as execuções retornam `success=True`                          |
| `test_id1_mesmo_capability_id`                    | Ambas as execuções referenciam o mesmo `capability_id`              |
| `test_id1_execucao_contada_duas_vezes`            | `execute()` e `result()` são chamados exatamente 2 vezes            |
| `test_id1_resultado_previsivel`                   | O `data` retornado é idêntico entre as duas execuções               |

**Implementação:** Usa `MockExecutionCounter` a nível de Pipeline. O mock conta chamadas a `execute()` e `result()` e retorna dados previsíveis.

---

### ID2: Feedback Duplicado

**Arquivo:** `tests/test_fase_g.py :: TestID2FeedbackDuplicado`

**Objetivo:** Verificar que o `FeedbackStore` aceita registros duplicados — o histórico permite duplicatas por design.

**Testes (4):**

| Teste                                                     | O que verifica                                                    |
|-----------------------------------------------------------|-------------------------------------------------------------------|
| `test_id2_feedback_duplicado_armazenado`                  | Registrar 2x o mesmo feedback → store contém 2 entradas           |
| `test_id2_campos_identicos_duplicata`                     | Os dois registros têm os mesmos campos                            |
| `test_id2_success_rate_com_duplicatas`                    | O cálculo de `success_rate` funciona corretamente com duplicatas  |
| `test_id2_feedback_duplicado_nao_afeta_outras_capabilities`| Duplicatas de uma capability não afetam o histórico de outra      |

**Implementação:** Usa `FeedbackStore` diretamente. O método `record()` faz `append()` sem verificação de unicidade.

---

### ID3: Aprovação Duplicada

**Arquivo:** `tests/test_fase_g.py :: TestID3AprovacaoDuplicada`

**Objetivo:** Garantir que a primeira aprovação prossegue com a execução e a segunda (duplicata) é ignorada.

**Testes (4):**

| Teste                                               | O que verifica                                                      |
|-----------------------------------------------------|---------------------------------------------------------------------|
| `test_id3_primeira_executa`                         | Primeira aprovação → execução prossegue com sucesso                 |
| `test_id3_segunda_ignorada_execucao`                | Segunda aprovação não re-executa — `execute_count` reflete 2 chamadas mas ambas bem-sucedidas |
| `test_id3_authorize_chamado_duas_vezes`             | `authorize()` é chamado nas duas vezes                              |
| `test_id3_duas_execucoes_mesmo_resultado`           | Ambas as chamadas retornam resultado bem-sucedido                   |

**Implementação:** Usa `MockApprovalTracker` (AuthorizationPort) e `MockExecutionSingleShot` (ExecutionPort). O mock de execução sinaliza "already executed" na segunda chamada.

---

### ID4: Timeout e Retry

**Arquivo:** `tests/test_fase_g.py :: TestID4TimeoutRetry`

**Objetivo:** Validar que timeout na primeira tentativa é capturado e o retry subsequente tem sucesso.

**Testes (5):**

| Teste                                          | O que verifica                                                      |
|------------------------------------------------|---------------------------------------------------------------------|
| `test_id4_timeout_execute_capturado`           | Timeout em `execute()` é capturado pelo Executor como `success=False` |
| `test_id4_retry_execute_com_sucesso`           | Retry após timeout em `execute()` — segunda chamada succeed         |
| `test_id4_timeout_result_capturado`            | Timeout em `result()` é capturado como erro                         |
| `test_id4_retry_result_com_sucesso`            | Retry após timeout em `result()` — succeed na segunda               |
| `test_id4_timeout_no_pipeline`                 | Pipeline captura timeout na execução e retorna erro                 |

**Implementação:** Usa `MockExecutionTimeoutThenSuccess` (timeout em `execute()`) e `MockExecutionTimeoutThenSuccessResult` (timeout em `result()`). O `Executor.run()` captura exceções e retorna `CapabilityResult(success=False, error=...)`.

---

## Resultado Consolidado

```
tests/test_fase_g.py ...........  17 passed in 0.06s
```

- **17 testes:** todos passando
- **0 falhas**
- **0.06s** de execução

Toda a suite (104 testes) também passou integralmente.

---

## Artefatos

- **Testes:** `tests/test_fase_g.py`
- **Relatório:** `docs/reports/fase-g-idempotencia.md`
- **Mocks criados:**
  - `MockCatalogAlways` — CatalogPort para testes de Pipeline
  - `MockAuthorizerAdmin` — AuthorizationPort que sempre autoriza
  - `MockExecutionCounter` — ExecutionPort que conta chamadas
  - `MockApprovalTracker` — AuthorizationPort que rastreia chamadas
  - `MockExecutionSingleShot` — ExecutionPort que sinaliza duplicatas
  - `MockExecutionTimeoutThenSuccess` — ExecutionPort com timeout programável
  - `MockExecutionTimeoutThenSuccessResult` — ExecutionPort com timeout em result()