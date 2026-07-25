# Relatório Fase H — Observabilidade

**Data:** 25/07/2026  
**Fase:** H — Observabilidade (OB1-OB7)  
**Projeto:** capability-intelligence  
**Status:** ✅ 33/33 testes passando

---

## Resumo

A Fase H valida a Observabilidade do pipeline Capability Intelligence em sete cenários:
logs do Resolver, Negotiator, Policy Engine, Executor, Interpreter, Feedback e propagação
do Correlation ID por todas as etapas.

Cada cenário verifica que as informações corretas são registradas (ou podem ser capturadas)
em cada etapa do pipeline, garantindo rastreabilidade ponta a ponta.

### Cenários

| ID   | Descrição                                                                    | Status |
|------|------------------------------------------------------------------------------|--------|
| OB1  | Log do Resolver — IntentQuery, domínio e timestamp                           | ✅     |
| OB2  | Log do Negotiator — candidatos, scores, ajuste de feedback, decisão          | ✅     |
| OB3  | Log do Policy Engine — políticas avaliadas, vereditos                        | ✅     |
| OB4  | Log do Executor — authorization result, execution_ref, duration              | ✅     |
| OB5  | Log do Interpreter — domínio, interpretador selecionado, Cognitive Register  | ✅     |
| OB6  | Log do Feedback — Capability ID, sucesso/falha, timestamp                    | ✅     |
| OB7  | Correlation ID propagado por todas as etapas do pipeline (mesmo ID)          | ✅     |

---

## Detalhamento dos Testes

### OB1: Log do Resolver

**Arquivo:** `tests/test_fase_h.py :: TestOB1ResolverLog`

**Objetivo:** Verificar que o Resolver cria uma IntentQuery com os campos esperados
(intent, domain, context/preferences) e que estas informações são rastreáveis.

**Testes (3):**

| Teste                                           | O que verifica                                                          |
|-------------------------------------------------|-------------------------------------------------------------------------|
| `test_ob1_resolver_logs_intent_query`           | Resolver cria IntentQuery com intent, domain e chama catalog.resolve()  |
| `test_ob1_resolver_logs_domain`                 | O domínio é incluído na consulta ao catálogo                            |
| `test_ob1_resolver_preserves_timestamp_in_query`| O timestamp (via context) é preservado na IntentQuery                   |

**Implementação:** Usa `MockCatalogPort` com spy no método `resolve()` para capturar
as IntentQuery criadas. Verifica os campos `intent`, `domain`, `context` e `preferences`.

---

### OB2: Log do Negotiator

**Arquivo:** `tests/test_fase_h.py :: TestOB2NegotiatorLog`

**Objetivo:** Verificar que o Negotiator registra/seleciona candidatos com base nos
scores, aplica ajustes por feedback histórico e decide entre auto-select e disambiguation.

**Testes (5):**

| Teste                                            | O que verifica                                                           |
|--------------------------------------------------|--------------------------------------------------------------------------|
| `test_ob2_negotiator_logs_candidates_and_scores` | Seleciona o candidato com maior score                                    |
| `test_ob2_negotiator_feedback_adjustment`        | Scores são ajustados por feedback histórico (33% sucesso → penalidade)  |
| `test_ob2_negotiator_decision_auto_select`       | Gap grande (> 0.30) → auto-select sem disambiguation                     |
| `test_ob2_negotiator_decision_disambiguation`    | Gap pequeno (≤ 0.30) → marca disambiguation                              |
| `test_ob2_negotiator_no_candidates_logs_none`    | Sem candidatos → retorna None                                            |

**Implementação:** Usa `Negotiator` diretamente com `CatalogResult` contendo
`CatalogMatch` objects. Constrói `CapabilityFeedback` para testar ajuste de scores.

---

### OB3: Log do Policy Engine

**Arquivo:** `tests/test_fase_h.py :: TestOB3PolicyEngineLog`

**Objetivo:** Verificar que o Policy Engine avalia políticas corretamente e retorna
vereditos de ALLOW, DENY ou REQUIRE_APPROVAL.

**Testes (5):**

| Teste                                          | O que verifica                                                           |
|------------------------------------------------|--------------------------------------------------------------------------|
| `test_ob3_policy_engine_evaluates_policies`    | Sem políticas → lista vazia de vereditos                                 |
| `test_ob3_policy_engine_deny_verdict`          | Política que nega → veredito DENY com razão                             |
| `test_ob3_policy_engine_allow_verdict`         | Política que permite → veredito ALLOW                                   |
| `test_ob3_policy_engine_requires_approval`     | Política que exige aprovação → veredito REQUIRE_APPROVAL                |
| `test_ob3_policy_engine_multiple_policies`     | Múltiplas políticas → todos os vereditos retornados, DENY detectado     |

**Implementação:** Cria funções de política inline que retornam `PolicyVerdict`.
Usa `PolicyEngine.evaluate()` com `asyncio.run()` por ser síncrono.

---

### OB4: Log do Executor

**Arquivo:** `tests/test_fase_h.py :: TestOB4ExecutorLog`

**Objetivo:** Verificar que o Executor registra o resultado da autorização, o
execution_ref gerado e a duração da execução.

**Testes (5):**

| Teste                                           | O que verifica                                                           |
|-------------------------------------------------|--------------------------------------------------------------------------|
| `test_ob4_executor_authorization_result`        | Autorização executada com capability_id e user corretos                  |
| `test_ob4_executor_execution_ref`               | ExecutionRef gerado e contido no metadata do resultado                   |
| `test_ob4_executor_duration`                    | Duration_ms presente no metadata (150ms do mock)                         |
| `test_ob4_executor_authorization_failure`       | Falha de autorização → success=False com mensagem de erro               |
| `test_ob4_executor_entities_impacted`           | Entidades impactadas presentes no metadata                              |

**Implementação:** Usa `MockAuthorizationPort` e `MockExecutionPort`. O mock de
execução retorna `ResultMetadata` com execution_ref, duration_ms e entities_impacted.

---

### OB5: Log do Interpreter

**Arquivo:** `tests/test_fase_h.py :: TestOB5InterpreterLog`

**Objetivo:** Verificar que o Interpreter seleciona o interpretador correto para
o domínio, processa o resultado e atualiza o Cognitive Register.

**Testes (5):**

| Teste                                               | O que verifica                                                       |
|-----------------------------------------------------|----------------------------------------------------------------------|
| `test_ob5_interpreter_selects_correct_interpreter`  | Domínio "infrastructure" → InfrastructureInterpreter selecionado    |
| `test_ob5_interpreter_fallback_generic`             | Domínio desconhecido → GenericInterpreter (fallback)                 |
| `test_ob5_interpreter_cognitive_register_updated`   | CognitiveRegister recebe evento capability:executed:infra            |
| `test_ob5_interpreter_no_cognitive_register_skips`  | CognitiveRegister = None → não quebra, processa sem atualizar        |
| `test_ob5_interpreter_entities_updated_in_cognitive_register` | Entidades impactadas são registradas no CognitiveRegister |

**Implementação:** Usa `MockCognitiveRegister` que implementa o Protocolo
`CognitiveRegister` (create_event, update_entity, create_artifact, create_task).

---

### OB6: Log do Feedback

**Arquivo:** `tests/test_fase_h.py :: TestOB6FeedbackLog`

**Objetivo:** Verificar que o FeedbackStore registra Capability ID, sucesso/falha
e timestamp.

**Testes (5):**

| Teste                                           | O que verifica                                                       |
|-------------------------------------------------|----------------------------------------------------------------------|
| `test_ob6_feedback_records_capability_id`       | Capability ID registrado corretamente                                |
| `test_ob6_feedback_records_success_failure`     | Sucesso e falha registrados, success_rate calculado (50%)            |
| `test_ob6_feedback_timestamp_auto_generated`    | Timestamp gerado automaticamente (datetime)                          |
| `test_ob6_feedback_preferred_capability`        | Capability mais frequente para uma intent retornada corretamente     |
| `test_ob6_feedback_no_history_returns_none`     | Intent sem histórico → retorna None                                  |

**Implementação:** Usa `FeedbackStore` diretamente com `LocalFeedback` objects.
Verifica `get_history()` e `get_preferred_capability()`.

---

### OB7: Correlation ID

**Arquivo:** `tests/test_fase_h.py :: TestOB7CorrelationID`

**Objetivo:** Verificar que um Correlation ID (ou Session ID) é propagado por
todas as etapas do pipeline — Resolver, Negotiator, PolicyEngine, Executor,
Interpreter e Feedback.

**Testes (5):**

| Teste                                                  | O que verifica                                                       |
|--------------------------------------------------------|----------------------------------------------------------------------|
| `test_ob7_correlation_id_in_pipeline_context`          | Correlation ID via context → pipeline executa com sucesso completo   |
| `test_ob7_correlation_id_propagated_to_all_stages`     | Mesmo correlation_id em Resolver, Executor, Interpreter, Feedback    |
| `test_ob7_different_correlation_ids_isolate_executions`| IDs diferentes → execuções isoladas, feedbacks separados             |
| `test_ob7_correlation_id_with_policy_engine`           | Pipeline com políticas roda com correlation_id no contexto           |
| `test_ob7_session_id_alternative`                      | Session ID funciona como alternativa ao correlation_id               |

**Implementação:** Usa Pipeline completo com todos os mocks. O correlation_id
é passado via `context={"correlation_id": "..."}`. Verifica-se que todas as
etapas recebem e processam o mesmo identificador.

---

## Resultado Consolidado

```
tests/test_fase_h.py ................................. 33 passed in 0.21s
```

- **33 testes:** todos passando
- **0 falhas**
- **0.21s** de execução

Toda a suite (226 testes) também passou integralmente:

```
======================= 226 passed, 1 skipped in 10.53s ========================
```

---

## Artefatos

- **Testes:** `tests/test_fase_h.py`
- **Relatório:** `docs/reports/fase-h-observabilidade.md`
- **Mocks criados:**
  - `LogCapture` / `_CaptureHandler` — captura de logs para verificação
  - `MockCatalogPort` — CatalogPort para testes de Resolver e Pipeline
  - `MockAuthorizationPort` — AuthorizationPort que rastreia último request
  - `MockExecutionPort` — ExecutionPort com execution_ref e metadata completos
  - `MockCognitiveRegister` — CognitiveRegister mock com eventos, entidades, artefatos, tasks

---

## Observações

1. **Correlation ID atual:** O pipeline não possui um campo `correlation_id` nativo
   — o ID é propagado via `context["correlation_id"]` e repassado ao Resolver como
   parte do contexto. Em futuras fases, pode-se adicionar `correlation_id` como
   parâmetro explícito do `Pipeline.run()`.

2. **Logging nativo:** O código atual tem logging mínimo (apenas `executor.py` usa
   `logging`). Os testes verificam que as informações estão disponíveis nas saídas
   de cada componente. Para produção, recomenda-se adicionar logging estruturado
   (JSON) com os campos verificados nestes testes.

3. **Cobertura:** Os 33 testes cobrem todos os 7 cenários propostos (OB1-OB7),
   com múltiplos testes por cenário para cobrir caminhos felizes e borda.