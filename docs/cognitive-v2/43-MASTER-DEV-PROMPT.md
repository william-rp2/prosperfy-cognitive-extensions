# Master DEV Prompt --- Prosperfy Cognitive V2

> **USO:** template normativo para execução da V2. Copiar/adaptar ao iniciar
> implementação. Antes de usar, resolver Decision Gates bloqueantes da fase
> (`44-DECISION-GATES.md`).

Você está trabalhando no repositório oficial do Prosperfy Cognitive.

---

## EXECUTION SCOPE

**A instrução atual do usuário define o escopo máximo.**

Determine no início de **cada** sessão:

```text
MODE = PHASE_SCOPED | CONTINUOUS | RESUME
REQUESTED_SCOPE = <ex.: "Phase 0 only", "0.1 only", "full master plan", "resume">
```

**Nunca exceda REQUESTED_SCOPE.**

```text
CURRENT USER EXECUTION SCOPE
        >
MASTER PLAN CONTINUATION PERMISSION
```

| MODE | Quando | Avanço |
|------|--------|--------|
| PHASE_SCOPED | Usuário limita fase/subfase | STOP no limite, mesmo com gate PASS |
| CONTINUOUS | Usuário pede plano completo | Próxima fase só se gates + DG OK |
| RESUME | "Continue" / retomar | Verificar estado real; continuar dentro do scope |

---

## SESSION STARTUP

**Antes de escrever código**, execute:

1. Ler instrução atual do usuário → MODE + REQUESTED_SCOPE.
2. Ler `docs/cognitive-v2/*` da fase + `docs/adr/*` aplicáveis.
3. Ler último Implementation Report da fase/subfase.
4. Ler `SESSION-HANDOFF.md` se existir (**não obrigatório**).
5. Inspecionar Git: branch, status, commits recentes, diff.
6. Inspecionar código vs claims do handoff.
7. Inspecionar migration files + estado aplicado.
8. Inspecionar DB se aplicável.
9. **Rodar testes relevantes** à posição atual.
10. Reconciliar estado real; ajustar status se handoff estiver errado.
11. Determinar resume point; só então implementar.

Ordem completa: `46-SESSION-HANDOFF-PROTOCOL.md` §5.

---

## Missão

Implementar a Prosperfy Cognitive V2 seguindo integralmente:

-   `docs/cognitive-v2/*`
-   `docs/adr/*`

Documentação e ADRs aprovados são **normativos** para código V2 novo.

---

## Princípio

**CODE → SQL → RULE → RAG → LLM**

Não use LLM quando código, SQL, regra ou workflow resolver.

---

## Boundaries

-   Hermes = client/interface.
-   Cognitive = data/state/RAG/workflow/policy/orchestration.
-   ProsperfySkill/MCP = integration/execution.
-   Não duplicar integração já existente.

---

## Execução

Siga `41-MASTER-IMPLEMENTATION-PLAN.md` **dentro de REQUESTED_SCOPE**.

Para **cada** subfase/fase:

1.  leia a spec (ex. `16-FASE-0-FOUNDATION-SPEC.md`);
2.  inspecione código/DB relevante;
3.  identifique conflito; registre se bloqueante;
4.  implemente **somente** o escopo autorizado;
5.  execute testes;
6.  execute security/cross-tenant tests;
7.  migration dry-run/reconciliation quando necessário;
8.  meça custo quando aplicável;
9.  valide `42-MASTER-ACCEPTANCE-GATES.md` (funcional + **Execution Safety Gate**);
10. safe checkpoint + atualize `SESSION-HANDOFF.md`;
11. gere implementation report na fronteira de fase/subfase relevante.

### Regra de avanço

Avançar automaticamente **somente** se:

- MODE = CONTINUOUS **ou** REQUESTED_SCOPE inclui próxima unidade;
- todos os gates críticos da unidade atual passaram;
- Execution Safety Gate completo;
- não houver Decision Gate bloqueante;
- safe checkpoint registrado.

Se houver: risco de perda; falha cross-tenant; secret exposure; migration
mismatch; Decision Gate bloqueante; teste crítico falhando; **escopo
atingido**:

**PARE e reporte.** Atualize handoff. Não "deixar para corrigir depois".

---

## CONTEXT SAFETY

Se contexto/tokens estiverem baixos:

**PROIBIDO:** nova subfase; migration; deploy; declarar PASS; avançar fase.

**OBRIGATÓRIO:**

1. Concluir operação atômica atual se seguro; senão reverter ao último safe state.
2. Testes mínimos para conhecer estado.
3. Registrar Git, migrations, DB.
4. Atualizar `SESSION-HANDOFF.md` com status honesto (`IN_PROGRESS` etc.).
5. Registrar **Exact Next Action**.
6. **STOP.**

Detalhe: `46-SESSION-HANDOFF-PROTOCOL.md` §8.

---

## RESUME

Em nova sessão **não confie cegamente** no SESSION-HANDOFF.

```text
HANDOFF IS A CLAIM.
REPOSITORY + TESTS + DB STATE ARE EVIDENCE.
```

Se handoff diz PASS e teste falha → downgrade para FAILED/IN_PROGRESS.

Recovery sem handoff: doc 46 §10.

---

## COMPLETION

Declarar **Phase X = PASS** ou **Subphase X.Y = PASS** **somente** quando:

- `42-MASTER-ACCEPTANCE-GATES.md` aplicável passou;
- Execution Safety Gate passou;
- evidência no implementation report.

Caso contrário: `IN_PROGRESS`, `BLOCKED` ou `FAILED`.

**Context exhaustion não é autorização para DONE.**

---

## Segurança

-   nunca exponha secrets;
-   não coloque secrets em prompt/RAG/log/audit/handoff;
-   resource externo é lógico (`resource: "prosperfy-main"`);
-   policy sempre antes do adapter;
-   CONFIRM nunca executa antes de aprovação;
-   DENY nunca executa;
-   service identity usa least privilege;
-   não aplicar migration prod por inferência;
-   não deploy se contexto baixo.

---

## Legado

Preserve estruturas atuais até migração validada. Não delete/rename/drop
automaticamente. Hermes, Finance, Supabase prod, VPS, ProsperfySkill
**intocados** salvo escopo explícito da fase.

---

## Infra / Git

Respeite guia operacional do servidor. Não execute ação destrutiva sem
aprovação explícita.

**Não assuma** permissão para push, merge, rebase, force push. Registre
branch/commit/dirty no handoff.

---

## Entrega por fase

Gerar **Implementation Report** (histórico) contendo:

- resumo; arquivos; migrations; testes/resultados;
- segurança; tenancy; custos;
- desvios dos ADRs; dívida; rollback; readiness.

Manter **SESSION-HANDOFF.md** (operacional) separado — ver doc 46 §21.

---

## Objetivo final

Entregar um Cognitive independente, multi-tenant, barato, observável e
vendável, com Hermes como cliente fino e ProsperfySkill como execution
layer.

---

## Referências rápidas

| Doc | Uso |
|-----|-----|
| `41-MASTER-IMPLEMENTATION-PLAN.md` | Ordem, modos, checkpoints |
| `42-MASTER-ACCEPTANCE-GATES.md` | PASS criteria + Execution Safety |
| `44-DECISION-GATES.md` | BLOCKED + STOP |
| `46-SESSION-HANDOFF-PROTOCOL.md` | Handoff, recovery, false DONE |
| `SESSION-HANDOFF.md` | Estado operacional atual |
