# Fase I — Performance: Linha de Base

**Data:** 2026-07-25  
**Arquivo de teste:** `tests/test_fase_i.py`  
**Cenários:** PF1–PF6  
**Ferramenta de medição:** `time.perf_counter()` (Python stdlib)  

---

## Resumo Executivo

| Cenário | Descrição | Limite | Medido | Status |
|---------|-----------|--------|--------|--------|
| PF1 | Criacão de `IntentQuery` vazia | < 1 ms | **~0,000 ms** | ✅ |
| PF1 (full) | Criacão de `IntentQuery` completa | < 1 ms | **~0,000 ms** | ✅ |
| PF2 | `Negotiator` com 2 candidatos, sem feedback | < 1 ms | **~0,000 ms** | ✅ |
| PF2 (vazio) | `Negotiator` sem matches | < 1 ms | **~0,000 ms** | ✅ |
| PF3 | `Negotiator` com 10 candidatos, 100 feedbacks | < 10 ms | **~0,136 ms** | ✅ |
| PF4 | Pipeline completo (mock) | < 50 ms | **~0,004 ms** | ✅ |
| PF5 | Pipeline real via MCP | < 60 s | **SKIPPED**¹ | ⏭️ |
| PF6 | `Negotiator` 500 candidatos | < 100 ms | **~0,016 ms** | ✅ |
| PF6 (fb) | `Negotiator` 500 + 50 feedbacks | < 100 ms | **~1,302 ms** | ✅ |
| PF6 (gap) | `Negotiator` 500 (gap detection) | < 100 ms | **~0,076 ms** | ✅ |

¹ PF5: saltado porque `MCP_API_KEY` / `PROSPERFY_API_KEY` não está configurada no ambiente.

---

## Detalhamento por Cenário

### PF1 — Criacão de `IntentQuery`

**Objetivo:** Medir o custo de alocação de uma `IntentQuery` sem consulta real ao Catálogo.

**Metodologia:** 1000 iterações, média aritmética.

| Variação | Tempo médio | Limite | Resultado |
|----------|-------------|--------|-----------|
| Campos vazios (`intent=""`, `domain=OTHER`) | 0,000 ms | < 1 ms | ✅ |
| Todos os campos preenchidos | 0,000 ms | < 1 ms | ✅ |

**Conclusão:** A criacão de `IntentQuery` é essencialmente gratuita (< 1 μs). Sem gargalos.

---

### PF2 — Negotiator com 2 candidatos

**Objetivo:** Medir o tempo de selecão do `Negotiator` no cenario mínimo.

**Metodologia:** 1000 iterações, média aritmética.

| Variação | Tempo médio | Limite | Resultado |
|----------|-------------|--------|-----------|
| 2 candidatos, sem feedback | 0,000 ms | < 1 ms | ✅ |
| 0 candidatos (lista vazia) | 0,000 ms | < 1 ms | ✅ |

**Conclusão:** `Negotiator.select()` sem feedback histórico é sub-microssegundo.

---

### PF3 — Negotiator com 10 candidatos e 100 feedbacks

**Objetivo:** Medir o impacto do ajuste de scores via feedback histórico.

**Metodologia:** 100 iterações, média aritmética.  
**Carga:** 10 `CatalogMatch`, 100 `CapabilityFeedback` (10 por capability, ~66% success rate).

| Métrica | Valor |
|---------|-------|
| Tempo médio | **0,136 ms** |
| Limite | < 10 ms |
| Folga | ~73× abaixo do limite |

**Conclusão:** Mesmo com 100 feedbacks, o `Negotiator` processa em < 0,2 ms. O gargalo de `_apply_feedback` (filtro O(n·m) em listas) é irrelevante nesta escala.

---

### PF4 — Pipeline completo (mock)

**Objetivo:** Medir o overhead do pipeline inteiro sem IO real (todos os componentes mockados).

**Metodologia:** 20 execuções assíncronas, média aritmética.

| Componente | Mock |
|------------|------|
| `CatalogPort` | Retorna 2 matches fixos |
| `AuthorizationPort` | Sempre autoriza |
| `ExecutionPort` | Retorna resultado fake |
| `CognitiveRegister` | Operações no-op |
| `PolicyEngine` | Sem políticas ativas |

| Métrica | Valor |
|---------|-------|
| Tempo médio | **0,004 ms** |
| Limite | < 50 ms |
| Folga | ~12.500× abaixo do limite |

**Conclusão:** O overhead do pipeline (criacão de objetos, chamadas assíncronas encadeadas) é desprezível. A latência real será dominada pelo IO do transporte (MCP/REST).

---

### PF5 — Pipeline real via MCP (SKIPPED)

**Objetivo:** Medir o pipeline completo com execucão real via `MCPAdapter`.

**Status:** ⏭️ **SKIPPED**  
**Motivo:** Nenhuma chave `MCP_API_KEY` ou `PROSPERFY_API_KEY` configurada no ambiente.

**Decisão de implementacão:** O teste usa `@pytest.mark.skipif` e verifica as env vars. Quando configurado, o teste cria wrappers nos protocolos `CatalogPort`, `AuthorizationPort` e `ExecutionPort` delegando ao `MCPAdapter` real.

**Threshold definido:** < 60 segundos (para comportar latência de rede + plataforma).

---

### PF6 — Negotiator com 500 Capabilities

**Objetivo:** Medir o `Negotiator` em escala — filtragem, ordenacão e gap detection com 500 candidatos.

**Metodologia:** 50 iterações, média aritmética. Scores pseudo-aleatórios com seed fixa (42).

| Variação | Tempo médio | Limite | Resultado |
|----------|-------------|--------|-----------|
| 500 candidatos, sem feedback | 0,016 ms | < 100 ms | ✅ |
| 500 candidatos + 50 feedbacks | 1,302 ms | < 100 ms | ✅ |
| 500 candidatos (gap detection: scores < threshold) | 0,076 ms | < 100 ms | ✅ |

**Conclusão:** Mesmo com 500 candidatos, o `Negotiator` opera em ~1,3 ms no pior caso (com feedback). Folga de ~76× abaixo do limite de 100 ms.

---

## Metodologia

1. **Medicão exclusiva com `time.perf_counter()`** — maior precisão disponível no Python stdlib.
2. **Múltiplas iteracões antes da média** — cada cenario executa N iteracões (50–1000) para amortizar ruído de scheduler.
3. **Mocks implementando Protocolos** — todos os mocks (`MockCatalogPort`, `MockAuthorizationPort`, `MockExecutionPort`, `MockCognitiveRegister`) implementam os Protocolos definidos no código (`CatalogPort`, `AuthorizationPort`, `ExecutionPort`, `CognitiveRegister`).
4. **Contexto isolado** — cada cenario cria suas próprias instâncias; sem estado compartilhado entre testes.

---

## Artefatos

| Arquivo | Descricão |
|---------|-----------|
| `tests/test_fase_i.py` | 13 testes (12 ativos, 1 skip condicional) |
| `docs/reports/fase-i-performance.md` | Este relatório |

---

## Observações

- **PF5 (MCP real)** exige credenciais da plataforma Prosperfy Skills. O teste está preparado para rodar assim que `MCP_API_KEY` for configurada. Nenhuma alteracão de código é necessária.
- **1 falha preexistente** em `tests/test_fase_h.py::TestOB7CorrelationID::test_ob7_correlation_id_with_policy_engine` — não relacionada aos cenários PF1–PF6. A falha ocorre porque uma política retorna "Correlation ID mismatch" mesmo quando o teste cria uma política `policy_always_allow`. Estava presente antes da criacão de `test_fase_i.py`.
- Os tempos medidos estabelecem a **linha de base (baseline)**. Futuras otimizacões (ex.: paralelismo no `_apply_feedback`, caching de `IntentQuery`) devem comparar contra estes números para validar melhoria.