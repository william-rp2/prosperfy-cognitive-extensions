# Master Acceptance Gates

## Global Gate

-   [ ] docs/ADRs respeitados
-   [ ] testes passam
-   [ ] cross-tenant passa
-   [ ] secrets redigidos
-   [ ] audit/telemetry
-   [ ] rollback/migration plan quando aplicável
-   [ ] custo medido
-   [ ] sem duplicação desnecessária de ProsperfySkill

---

## Execution Safety Gate

Checklist mínimo **antes de declarar PASS** em qualquer fase/subfase ou
pausar com trabalho em andamento. Ver `46-SESSION-HANDOFF-PROTOCOL.md`.

-   [ ] **Requested scope respected** — não excedeu instrução do usuário
-   [ ] **Current phase/subphase identified** — posição explícita no handoff
-   [ ] **Acceptance criteria executed** — gate funcional da unidade rodado
-   [ ] **Test results recorded** — passed / failed / not run
-   [ ] **Git state known** — branch, commit ou dirty, arquivos relevantes
-   [ ] **Migration state known** — created / applied / pending / rollback
-   [ ] **DB state known** when applicable — ambiente + verificação
-   [ ] **No partial destructive operation** — migration/deploy/destructive incompleto
-   [ ] **No secret exposure** — logs, handoff, audit, diff
-   [ ] **Safe checkpoint created** — critérios doc 46 §6
-   [ ] **SESSION-HANDOFF updated** — `SESSION-HANDOFF.md`
-   [ ] **Exact next action recorded** — um passo concreto
-   [ ] **Decision Gates checked** — nenhum DG bloqueante ignorado

---

## Regra PASS

**Uma fase NÃO recebe PASS apenas porque código foi escrito.**

PASS exige:

1. acceptance criteria funcional desta unidade (seções abaixo);
2. Execution Safety Gate completo;
3. evidência em implementation report quando aplicável.

Se gate funcional ou safety falhar: `IN_PROGRESS`, `BLOCKED` ou `FAILED`
— **nunca** PASS por proximidade ou contexto baixo.

---

## Status model

| Status | Uso |
|--------|-----|
| **PASS** | Criteria + safety gate OK; evidência registrada |
| **IN_PROGRESS** | Trabalho iniciado; gate ainda não passou |
| **BLOCKED** | Decision Gate ou dependência externa |
| **NOT_STARTED** | Unidade não iniciada |
| **FAILED** | Gate executado e falhou |

Handoff claim de PASS **deve ser reverificado** com testes na retomada.

---

## Foundation

-   [ ] Gateway
-   [ ] tenant/actor/resource
-   [ ] registry
-   [ ] policy
-   [ ] adapter
-   [ ] execution/audit/telemetry
-   [ ] idempotency

## Projects

-   [ ] projects/tasks
-   [ ] state/history
-   [ ] planning
-   [ ] delegation

## RAW

-   [ ] ingest
-   [ ] dedup
-   [ ] attachments
-   [ ] source trace

## RAG

-   [ ] embeddings
-   [ ] vector search
-   [ ] tenant filter
-   [ ] citations
-   [ ] relevance

## Workflow

-   [ ] scheduler
-   [ ] outbox
-   [ ] retry
-   [ ] follow-up
-   [ ] approval

## Finance

-   [ ] migration reconciliation
-   [ ] Pluggy
-   [ ] budgets
-   [ ] ACL
-   [ ] WhatsApp/manual ingest

## Infra

-   [ ] checks
-   [ ] incidents
-   [ ] notifications
-   [ ] no continuous LLM

## Email

-   [ ] incremental sync
-   [ ] routing
-   [ ] task/knowledge
-   [ ] safe send

## Customer

-   [ ] scope
-   [ ] requirements/tasks
-   [ ] followups
-   [ ] escalation

## Proposal

-   [ ] spec
-   [ ] template
-   [ ] render
-   [ ] approval

## Hermes migration

-   [ ] thin tool surface
-   [ ] cost comparison
-   [ ] rollback
-   [ ] functional equivalence

## Social

-   [ ] brand isolation
-   [ ] approval
-   [ ] scheduling/publication
