# Session Handoff Protocol

**Status:** normativo (execução V2)  
**Relacionado:** `41-MASTER-IMPLEMENTATION-PLAN.md`, `42-MASTER-ACCEPTANCE-GATES.md`, `43-MASTER-DEV-PROMPT.md`, `SESSION-HANDOFF.md`

---

## 1. Purpose

Este documento define como implementar, pausar, retomar e transferir trabalho da Prosperfy Cognitive V2 **sem depender da memória de sessão ou do agente**.

A continuidade confiável vem de:

```text
Repository
  + Git state
  + Migrations (files + applied state)
  + Database state (when applicable)
  + Tests (results recorded)
  + Documentation (normative)
  + Implementation Reports (historical)
  + Checkpoints
  + SESSION-HANDOFF.md (operational, mutable)
```

---

## 2. Principles

1. **Nenhum agente é estado persistente.** Claude Code, Cursor, Agent A/B — todos são substituíveis.
2. **Handoff é claim; repositório + testes + DB são evidência.**
3. **Escopo do usuário > permissão do Master Plan** para continuar.
4. **PASS exige acceptance gate completo** — código escrito ≠ PASS.
5. **Context exhaustion ≠ autorização para DONE.**
6. **Commit ≠ Safe Checkpoint** automaticamente.
7. **Interrupção inesperada:** recovery não depende de handoff existente.

---

## 3. Execution Modes

### MODE A — PHASE-SCOPED

Exemplo: *"Implemente somente a Fase 0."*

```text
Fase 0
  → 0.1 → checkpoint
  → 0.2 → checkpoint
  → 0.3 → checkpoint
  → 0.4 → checkpoint
  → 0.5 → checkpoint
  → Gate Fase 0 → Implementation Report
  → STOP (não iniciar Fase 1)
```

### MODE B — CONTINUOUS

Exemplo: *"Implemente o Master Plan completo."*

```text
Fase N → Gate PASS → checkpoint → Fase N+1 → ...
```

Avanço automático **somente** quando:

- todos os gates críticos da fase passaram;
- não há Decision Gate humano bloqueante;
- migrations reconciliadas;
- nenhum risco crítico aberto;
- safe checkpoint registrado.

### MODE C — RESUME

Exemplo: *"Continue de onde parou."*

Determinar escopo residual a partir de evidência real + handoff (se existir). Nunca exceder `REQUESTED_SCOPE` da instrução atual.

---

## 4. Scope Authority

```text
CURRENT USER EXECUTION SCOPE
        >
MASTER PLAN CONTINUATION PERMISSION
```

| Instrução do usuário | Comportamento |
|----------------------|---------------|
| "Somente Fase 0" | Para após Gate Fase 0; não Fase 1 |
| "Somente 0.1 e pare" | Para após 0.1 checkpoint |
| "Implemente tudo" | MODE B permitido se gates passarem |
| "Continue" | MODE C; verificar estado real primeiro |

---

## 5. Session Startup Protocol

Toda nova sessão/agente **antes de escrever código**:

```text
READ CURRENT EXECUTION REQUEST
        ↓
READ NORMATIVE DOCS (phase spec, ADRs, 41/42/43/44)
        ↓
READ LAST PHASE/SUBPHASE IMPLEMENTATION REPORT (if any)
        ↓
READ SESSION-HANDOFF.md (if available — não obrigatório)
        ↓
INSPECT GIT (branch, status, recent commits, diff)
        ↓
INSPECT CODE (files claimed vs reality)
        ↓
INSPECT MIGRATION FILES + APPLIED STATE
        ↓
INSPECT DB STATE (if applicable)
        ↓
RUN RELEVANT TESTS
        ↓
RECONCILE REAL STATE (handoff may be wrong)
        ↓
DETERMINE RESUME POINT + REQUESTED_SCOPE
        ↓
CONTINUE or STOP if BLOCKED
```

---

## 6. Safe Checkpoint Definition

Um **SAFE CHECKPOINT** existe somente quando **todos** aplicáveis:

- [ ] arquivos em estado coerente (compila/importa);
- [ ] nenhuma migration parcialmente aplicada sem registro;
- [ ] nenhum deploy parcialmente executado;
- [ ] nenhuma operação destrutiva pela metade;
- [ ] estado do banco conhecido e documentado;
- [ ] testes executados registrados (pass/fail/not run);
- [ ] falhas conhecidas registradas;
- [ ] próximo passo exato registrado;
- [ ] rollback point conhecido (commit, migration down) quando aplicável;
- [ ] SESSION-HANDOFF.md atualizado;
- [ ] nenhum secret em diff/log/handoff.

**Commit sozinho não garante safe checkpoint.**

---

## 7. Subphase Checkpoints

Registrar safe checkpoint em fronteiras relevantes — **não** a cada arquivo.

### Fase 0 (`16-FASE-0-FOUNDATION-SPEC.md`)

| Subfase | Checkpoint após |
|---------|-----------------|
| 0.1 Core mock | Gate 0.1 + testes |
| 0.2 Persistence/Tenancy | Gate 0.2 + migration reconciled |
| 0.3 ProsperfySkill real | Gate 0.3 + adapter tests |
| 0.4 Auth identities | Gate 0.4 |
| 0.5 Hardening | Gate 0.5 |
| Fase 0 Gate | `PHASE-0-IMPLEMENTATION-REPORT.md` |

### Fases posteriores

Aplicar o mesmo padrão quando a spec definir subfases naturais (2A/2B, 4A/4B, 5A/5B/5C).

Checkpoints adicionais obrigatórios:

- antes/depois de migration relevante;
- antes/depois de deploy;
- antes de pausa planejada;
- antes de troca de agente/ferramenta;
- quando contexto/tokens baixos;
- após gate importante.

---

## 8. Context / Token Exhaustion Protocol

Quando o agente perceber limite de contexto/tokens iminente:

**PROIBIDO:**

- acelerar pulando testes;
- reduzir segurança;
- declarar fase/subfase PASS;
- iniciar nova subfase;
- iniciar migration arriscada;
- iniciar deploy;
- avançar "porque está quase pronto".

**OBRIGATÓRIO:**

1. Terminar operação atômica atual **se seguro**; senão reverter ao último safe state.
2. Executar testes mínimos para conhecer estado real.
3. Registrar Git (branch, commit ou dirty state).
4. Registrar migrations (created/applied/pending).
5. Registrar DB state se aplicável.
6. Atualizar `SESSION-HANDOFF.md`.
7. Marcar subfase: `PASS` | `IN_PROGRESS` | `BLOCKED` | `NOT_STARTED` | `FAILED`.
8. Registrar **Exact Next Action** (um passo concreto).
9. **STOP.**

---

## 9. Planned Pause Protocol

Quando o usuário pede pausa ou fim de sessão:

1. Não iniciar novo trabalho.
2. Estabilizar working tree (commit se safe checkpoint alcançado).
3. Rodar testes relevantes à subfase atual.
4. Atualizar handoff.
5. Registrar modo (`PHASE_SCOPED` / `CONTINUOUS` / `RESUME`) e scope.
6. STOP.

---

## 10. Unexpected Interruption Recovery

Se o agente morre **sem** handoff atualizado, nova sessão usa esta ordem:

```text
1. Documentação normativa (spec, ADRs, 41-46)
2. Git status + diff + recent commits
3. Código real no disco
4. Migration files + applied state
5. DB state (if applicable)
6. Implementation Reports
7. SESSION-HANDOFF.md (if exists)
8. Tests (re-run — do not trust prior claims)
```

Handoff **ajuda**; **não** supera evidência real.

---

## 11. Agent Change Protocol

Suportado explicitamente:

```text
Claude Code → checkpoint → Cursor → checkpoint → Claude Code
Agent A → Agent B
```

Novo agente:

- desconfia de afirmações não verificadas;
- reexecuta testes de gate da subfase claimada como PASS;
- se teste falhar → downgrade status (`FAILED` / `IN_PROGRESS`).

---

## 12. Tool Change Protocol

Estado arquitetural **não** depende de feature exclusiva de Cursor ou Claude Code.

| O quê | Onde vive |
|-------|-----------|
| Regras normativas | `docs/cognitive-v2/`, `docs/adr/` |
| Decisões | ADRs |
| Estado operacional | `SESSION-HANDOFF.md`, reports |
| Código | Git |
| Migrations | versionadas no repo |
| DB applied state | ambiente + registro no handoff |

---

## 13. Database / Migration Safety

### Antes de migration

- identificar ambiente (local/staging/prod);
- confirmar migration baseline;
- backup quando necessário;
- validar rollback/forward strategy;
- **nunca** aplicar prod por inferência;
- **não iniciar** migration se contexto baixo.

### Depois de migration

- registrar migration aplicada;
- verificar schema;
- reconciliation;
- testes;
- atualizar handoff.

### Falha parcial

Status: `BLOCKED` ou `FAILED` até reconciliação. Não avançar subfase.

---

## 14. Deploy Safety

### Antes

- gate apropriado PASS;
- ambiente confirmado explicitamente;
- testes;
- rollback plan;
- commit/version conhecido;
- **não iniciar deploy** se contexto baixo.

### Depois

- health check;
- smoke test;
- logs (sem secrets);
- versão registrada;
- report/handoff.

Deploy exige aprovação explícita do usuário/ambiente — nunca inferir permissão de push/merge.

---

## 15. Test State Recording

No handoff e reports, registrar:

```text
Passed:   [lista ou "none"]
Failed:   [lista + erro resumido]
Not Run:  [lista + motivo]
```

Comando usado (sem secrets). Timestamp opcional.

Testes não executados **impedem** declarar PASS.

---

## 16. Git State Recording

Sempre registrar:

- branch;
- commit hash (ou "uncommitted");
- clean / dirty;
- arquivos relevantes alterados.

**Não assumir** permissão para: push, merge, rebase, force push, branch protegida.

Nunca commitar credentials.

---

## 17. Handoff File Format

Arquivo operacional mutável: `docs/cognitive-v2/SESSION-HANDOFF.md`

Ver template inicial no repo. Campos obrigatórios:

- Metadata (Updated At, Agent/Tool, Execution Mode, Requested Scope)
- Current Position (Phase, Subphase, Status)
- Last Safe Checkpoint
- Completed / In Progress / Not Started / Blocked
- Files Changed, Migrations, Database State, Tests
- External Systems (Hermes, ProsperfySkill, Supabase, Finance, VPS — unchanged unless touched)
- Decision Gates Pending
- Exact Next Action (numbered, one concrete step)
- Resume Verification Required

---

## 18. Resume Verification Protocol

Ao retomar subfase claimada como PASS no handoff:

1. Re-run acceptance tests da subfase.
2. Se falhar → status `FAILED` ou `IN_PROGRESS`; corrigir antes de avançar.
3. Se passar → confirmar PASS; continuar próximo passo.

**Exemplo:** handoff diz 0.2 PASS; testes cross-tenant falham → 0.2 **não** é PASS.

---

## 19. Status Model

| Status | Significado |
|--------|-------------|
| **PASS** | Acceptance criteria da unidade passaram; evidência registrada |
| **IN_PROGRESS** | Trabalho iniciado; gate ainda não passou |
| **BLOCKED** | Não continuar sem decisão/dependência/correção externa |
| **NOT_STARTED** | Nenhum trabalho autorizado/iniciado nesta unidade |
| **FAILED** | Gate executado e falhou; requer correção antes de avanço |

Opcionalmente usar `FAILED` vs manter `IN_PROGRESS` quando causa é conhecida — preferir `FAILED` após execução de gate com falha.

---

## 20. False Completion Prevention

**Context exhaustion NÃO autoriza DONE.**

Proibido:

- "Está quase pronto, considero concluído."
- "Testes restantes depois."
- "Implementação principal terminou, então PASS."
- "Contexto acabando, vou avançar."

Se gate não passou → `IN_PROGRESS`, `BLOCKED` ou `FAILED` — **nunca** PASS.

---

## 21. Implementation Report vs Session Handoff

| Artefato | Natureza | Exemplo |
|----------|----------|---------|
| **Implementation Report** | Histórico; imutável após publicação | `15-SPRINT-0.1-IMPLEMENTATION-REPORT.md`, `PHASE-0-IMPLEMENTATION-REPORT.md` |
| **SESSION-HANDOFF.md** | Operacional; mutável a cada pausa | `docs/cognitive-v2/SESSION-HANDOFF.md` |

Não substituir um pelo outro. Report = evidência de conclusão; Handoff = ponte para próxima sessão.

---

## 22. Examples

### Fase 0 phase-scoped (uma sessão longa)

Scope: PHASE 0 ONLY → 0.1 PASS → checkpoint → … → 0.5 PASS → Gate → Report → STOP.

### Contexto acaba no 0.3

Estado: 0.1 PASS, 0.2 PASS, 0.3 IN_PROGRESS → estabilizar → testes → handoff → STOP.  
Nova sessão: verificar 0.1/0.2 → continuar 0.3.

### Decision Gate bloqueante

Chegou DG-003 antes de 2B → status BLOCKED → registrar gate → STOP. Não escolher silenciosamente.

---

## 23. Acceptance Criteria (deste protocolo)

- [ ] Documento referenciado por 41, 42, 43
- [ ] Dois modos + resume definidos
- [ ] Scope authority explícita
- [ ] Safe checkpoint formalizado
- [ ] Token exhaustion protocol completo
- [ ] Recovery sem handoff documentado
- [ ] Template SESSION-HANDOFF.md existe
- [ ] Status model padronizado
- [ ] False DONE proibido explicitamente
