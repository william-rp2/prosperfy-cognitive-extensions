# Execution Protocol Review

**Data:** 2026-08-16  
**Escopo:** atualização documental — Execution / Checkpoint / Handoff Protocol  
**Status:** concluído — **STOP GATE** (aguardar revisão humana antes de implementação)

---

## Summary

Documentação atualizada para tornar a implementação V2 **resiliente a limite
de contexto, troca de sessão/agente/ferramenta, interrupções, escopos parciais
e retomada**. Nenhum runtime foi alterado.

Princípio central reforçado: **estado confiável = Git + código + migrations +
DB + testes + docs + reports + checkpoints + handoff** — agente/sessão **não**
são estado persistente.

---

## Files Created

| Arquivo | Propósito |
|---------|-----------|
| `docs/cognitive-v2/46-SESSION-HANDOFF-PROTOCOL.md` | Normativo: modos, checkpoints, exhaustion, recovery, migration/deploy safety |
| `docs/cognitive-v2/SESSION-HANDOFF.md` | Template operacional mutável (estado inicial: NOT_STARTED) |
| `docs/cognitive-v2/47-EXECUTION-PROTOCOL-REVIEW.md` | Este relatório de validação |

---

## Files Updated

| Arquivo | Motivo | Mudança |
|---------|--------|---------|
| `docs/cognitive-v2/41-MASTER-IMPLEMENTATION-PLAN.md` | Integrar protocolo de execução | Modos A/B/C; scope authority; safe checkpoint; subphase checkpoints 0.1–0.5; pause/resume; recovery; reports vs handoff; refs doc 46 |
| `docs/cognitive-v2/42-MASTER-ACCEPTANCE-GATES.md` | Gate de segurança de execução | Seção **Execution Safety Gate**; regra PASS; status model |
| `docs/cognitive-v2/43-MASTER-DEV-PROMPT.md` | Prompt operacional completo | EXECUTION SCOPE; SESSION STARTUP; CONTEXT SAFETY; RESUME; COMPLETION; refs 46 |
| `docs/cognitive-v2/00-README.md` | Índice incompleto | Docs 16, 41–47 e SESSION-HANDOFF.md |

**Não alterados (sem contradição detectada):** `44-DECISION-GATES.md`, `45-REQUIREMENTS-TRACEABILITY.md`, `16-FASE-0-FOUNDATION-SPEC.md`, ADRs, código, Hermes, Finance, Supabase, VPS.

---

## Execution Modes Supported

| Modo | Documentado em | Comportamento |
|------|----------------|---------------|
| **PHASE-SCOPED** | 41 §Modos, 43 §EXECUTION SCOPE, 46 §3 | Para no limite do scope; não avança fase seguinte |
| **CONTINUOUS** | 41, 43, 46 | Avança só com gates + DG + safe checkpoint |
| **RESUME** | 41, 43 §RESUME, 46 §3/§10/§18 | Evidência real > handoff |

---

## Token/Context Exhaustion Handling

- Protocolo explícito em `46-SESSION-HANDOFF-PROTOCOL.md` §8
- Integrado em `43-MASTER-DEV-PROMPT.md` §CONTEXT SAFETY
- **False DONE proibido** — §20 doc 46; §COMPLETION doc 43; §Regra PASS doc 42
- Ações: estabilizar → testes mínimos → handoff → STOP; **não** nova subfase/migration/deploy

---

## Agent Handoff Handling

- `SESSION-HANDOFF.md` template criado
- Formato §17 doc 46
- Agent change §11: Claude ↔ Cursor; re-verificação com testes
- **HANDOFF IS A CLAIM; REPOSITORY + TESTS + DB ARE EVIDENCE**

---

## Unexpected Interruption Handling

Recovery order documentada (`46` §10): normative docs → Git → code → migrations → DB → reports → handoff → tests.

Nova sessão **não depende** de handoff existente.

---

## Migration Safety

`46` §13 + `43` §Segurança + `41` ciclo:

- identificar ambiente; baseline; backup; rollback plan;
- não prod por inferência;
- não iniciar se contexto baixo;
- falha parcial → BLOCKED/FAILED até reconciliação.

---

## Deploy Safety

`46` §14: gate PASS, ambiente explícito, tests, rollback, **não deploy se contexto baixo**; pós-deploy health/smoke/logs.

Git: não assumir push/merge/rebase — registrar estado apenas.

---

## Scope Protection

```text
CURRENT USER EXECUTION SCOPE > MASTER PLAN CONTINUATION PERMISSION
```

Documentado em 41, 43, 46. Exemplos: "Fase 0 only", "0.1 and stop", "full plan".

---

## Conflicts Found

### CONFLITO 1 — 43 original vs scope authority

| | |
|---|---|
| **Evidência** | `43-MASTER-DEV-PROMPT.md` original: "avance automaticamente à próxima fase" sem priorizar instrução do usuário |
| **Impacto** | Agente poderia exceder scope phase-scoped |
| **Resolução** | EXECUTION SCOPE + hierarquia explícita em 43 e 41 |
| **Status** | Resolvido (documentação) |

### CONFLITO 2 — Checkpoints só no final de fase

| | |
|---|---|
| **Evidência** | `41` original: checkpoint só mencionado após GATE REPORT de fase |
| **Impacto** | Retomada granular 0.1–0.5 difícil |
| **Resolução** | Subphase checkpoints alinhados a `16-FASE-0-FOUNDATION-SPEC.md` |
| **Status** | Resolvido (documentação) |

### CONFLITO 3 — PASS implícito por código escrito

| | |
|---|---|
| **Evidência** | Gates funcionais sem safety gate de execução |
| **Impacto** | False DONE |
| **Resolução** | Execution Safety Gate em 42; regra PASS explícita |
| **Status** | Resolvido (documentação) |

**Nenhum conflito com ADRs arquiteturais** — CODE→SQL→RULE→RAG→LLM e boundaries preservados.

---

## Open Questions

1. Formato exato de nomes de Implementation Reports por subfase (ex. `PHASE-0.1-IMPLEMENTATION-REPORT.md` vs `15-SPRINT-0.1-...`) — padronizar na primeira implementação.
2. Frequência mínima de commit vs safe checkpoint — deixar critério doc 46; time decide na prática.
3. CI automatizado para Execution Safety Gate checklist — futuro; hoje manual no handoff.

---

## Validation Checklist

- [x] Phase-scoped execution supported
- [x] Continuous execution supported
- [x] Resume execution supported
- [x] User scope overrides continuation
- [x] Subphase checkpoints defined (Fase 0.1–0.5)
- [x] Safe checkpoint defined
- [x] Token exhaustion protocol defined
- [x] False DONE prohibited
- [x] Unexpected interruption recoverable
- [x] Agent/tool switching supported
- [x] Migration safety defined
- [x] Deploy safety defined
- [x] Handoff template created
- [x] Real state overrides handoff claims
- [x] Master Prompt updated
- [x] Acceptance Gates updated

---

## Confirmações de integridade (STOP GATE)

| Verificação | Resultado |
|-------------|-----------|
| `core/cognitive` criado | ❌ Não |
| FastAPI / runtime | ❌ Não |
| Migrations executáveis criadas/aplicadas | ❌ Não |
| Docker Compose runtime | ❌ Não |
| Supabase alterado | ❌ Não |
| Hermes alterado | ❌ Não |
| Finance alterado | ❌ Não |
| ProsperfySkill / VPS alterados | ❌ Não |
| Deploy | ❌ Não |

**Documentação congelada. Aguardar revisão humana antes de qualquer implementação (Fase 0 / Sprint 0.1).**
