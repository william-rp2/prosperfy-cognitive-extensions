# Master Implementation Plan

## Regra

O agente pode receber uma missão longa, mas deve executar **fase por
fase com gate obrigatório**. Falha crítica impede avanço.

**Estado do projeto não depende da sessão ou do agente.** Continuidade via
Git + código + migrations + DB + testes + documentação + reports +
checkpoints + `SESSION-HANDOFF.md` — ver `46-SESSION-HANDOFF-PROTOCOL.md`.

---

## Modos de execução

### MODE A — PHASE-SCOPED

Exemplo: *"Implemente somente a Fase 0."*

Executar a fase solicitada até gate + implementation report, então **STOP**
— mesmo que a fase passe completamente, **não** iniciar a fase seguinte.

### MODE B — CONTINUOUS

Exemplo: *"Implemente o Master Plan completo."*

Avançar fase a fase **somente** quando gates críticos passarem, não houver
Decision Gate bloqueante, migrations reconciliadas, safe checkpoint
registrado e riscos críticos fechados.

### MODE C — RESUME

Exemplo: *"Continue de onde parou."*

Recuperar estado real (Git, código, migrations, DB, testes) antes de
continuar. Handoff ajuda; **não** substitui evidência.

---

## Autoridade de escopo

```text
CURRENT USER EXECUTION SCOPE
        >
MASTER PLAN CONTINUATION PERMISSION
```

A instrução **atual** do usuário define o limite máximo. O Master Plan **não**
autoriza avanço além do escopo pedido.

| Pedido | Comportamento |
|--------|---------------|
| "Somente Fase 0" | Para após Gate Fase 0; não Fase 1 |
| "Somente 0.1 e pare" | Para após checkpoint 0.1 |
| "Implemente tudo" | MODE B permitido se gates passarem |

---

## Ordem

### Phase 0 --- Foundation

0.1 Core mock → **checkpoint**\
0.2 Postgres/tenancy → **checkpoint**\
0.3 ProsperfySkill real → **checkpoint**\
0.4 Auth identities → **checkpoint**\
0.5 Hardening → **checkpoint**\
→ **Gate Fase 0** → `PHASE-0-IMPLEMENTATION-REPORT.md`

Detalhe: `16-FASE-0-FOUNDATION-SPEC.md`

### Phase 1 --- Projects/Tasks/Planning

### Phase 2A --- Collector/RAW

### Phase 2B --- Knowledge/RAG

### Phase 3 --- Workflow/Follow-ups

### Phase 4A --- Finance

### Phase 4B --- Infrastructure Monitor

### Phase 5A --- Email Intelligence

### Phase 5B --- Customer Agent

### Phase 5C --- Proposal Engine

### Hermes Migration

Executar após Core e funcionalidades suficientes para equivalência.

### Phase 6 --- Social Engine

Não bloqueia MVP.

---

## Ciclo por subfase / fase

``` text
READ SPECS + ADRs + EXECUTION REQUEST
 -> SESSION STARTUP (Git, migrations, DB, tests) — 46-SESSION-HANDOFF-PROTOCOL
 -> INSPECT CURRENT CODE
 -> PLAN (within REQUESTED_SCOPE)
 -> IMPLEMENT
 -> MIGRATION DRY-RUN if needed (never if context low)
 -> TEST
 -> SECURITY TEST
 -> COST TEST
 -> GATE REPORT (42-MASTER-ACCEPTANCE-GATES)
 -> SAFE CHECKPOINT + SESSION-HANDOFF update
 -> IMPLEMENTATION REPORT (phase/subphase boundary)
 -> NEXT (only if scope + gates allow)
```

---

## Safe checkpoint

Checkpoint **seguro** somente quando critérios em
`46-SESSION-HANDOFF-PROTOCOL.md` §6 forem atendidos.

**Commit ≠ safe checkpoint** automaticamente.

Registrar checkpoint em:

- fronteira de subfase (0.1 … 0.5, 2A/2B, etc.);
- antes/depois de migration relevante;
- antes/depois de deploy;
- pausa planejada ou troca de agente/ferramenta;
- esgotamento de contexto/tokens;
- após gate importante.

---

## Pausa, retomada e interrupção

### Pausa planejada ou contexto baixo

Não iniciar nova subfase, migration ou deploy. Estabilizar → testes mínimos
→ atualizar `SESSION-HANDOFF.md` → STOP.

### Interrupção inesperada (sem handoff)

Nova sessão recupera estado por: docs normativos → Git → código →
migrations → DB → reports → handoff (se existir) → **re-run tests**.

Ver `46-SESSION-HANDOFF-PROTOCOL.md` §10.

### Troca de agente / ferramenta

Claude Code ↔ Cursor ↔ outro agente: checkpoint + handoff; novo agente
**verifica** claims com testes. Handoff é claim; repo é evidência.

---

## Regra contra avanço sem gate

Uma fase/subfase **não** recebe PASS porque código foi escrito.

PASS exige `42-MASTER-ACCEPTANCE-GATES.md` aplicável + evidência em
implementation report.

Context exhaustion **não** autoriza PASS. Ver §False completion em doc 46.

---

## Stop automático

Parar se:

- risco de perda de dados;
- decisão humana (Decision Gate) bloqueante não resolvida;
- cross-tenant falhar;
- secrets vazarem;
- migration reconciliation falhar;
- gate crítico falhar;
- contexto/tokens baixos (checkpoint + STOP);
- escopo do usuário atingido.

Não "deixar para corrigir depois".

---

## Decision Gates

Ver `44-DECISION-GATES.md`. Resumo:

1.  mecanismo RLS/auth DB --- antes de 0.2 production-ready;
2.  secret store produção --- antes de credenciais reais multi-tenant;
3.  embeddings model/dimension --- antes de 2B migration;
4.  Finance source of truth --- antes de 4A;
5.  Proposal renderer boundary --- antes de 5C;
6.  dedicated deployment --- antes do primeiro cliente dedicado;
7.  WhatsApp adapter --- antes de collector/customer WhatsApp produtivo.

Status `BLOCKED` + handoff + STOP. Não decidir silenciosamente.

---

## Checkpoints e reports

| Artefato | Quando | Natureza |
|----------|--------|----------|
| **Safe checkpoint** | Fronteiras acima | Estado recuperável |
| **SESSION-HANDOFF.md** | Toda pausa | Mutável, operacional |
| **PHASE-X-IMPLEMENTATION-REPORT.md** | Gate de fase | Histórico, evidência |
| **Subphase report** | Opcional por subfase crítica | ex. `15-SPRINT-0.1-IMPLEMENTATION-REPORT.md` |

Cada report de fase inclui: arquivos, migrations, testes, riscos, métricas,
readiness, desvios de ADR, rollback.

---

## Referências

- `43-MASTER-DEV-PROMPT.md` — prompt operacional do agente
- `46-SESSION-HANDOFF-PROTOCOL.md` — handoff, checkpoints, recovery
- `SESSION-HANDOFF.md` — estado operacional atual (template até implementação)
