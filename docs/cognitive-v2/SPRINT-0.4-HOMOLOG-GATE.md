# Sprint 0.4 — Homolog Gate QA Plan

> Este documento é operacional e autocontido. Foi escrito para ser executado
> por um agente diferente, com acesso à VPS/Homolog e ZERO contexto desta
> conversa. Siga as seções em ordem. Não interprete intenção — se algo aqui
> for ambíguo, pare e reporte ao Lead Dev em vez de decidir sozinho.

Escopo do Sprint 0.4 (subphase 0.4, `docs/cognitive-v2/16-FASE-0-FOUNDATION-SPEC.md`):
"Evoluir API key inicial para clients/credentials/actors sem acoplar
identidade ao Hermes." Duas entregas integradas nesta branch:

1. **CLI de operação** (`core/cognitive/scripts/manage_service_identity.py`)
   — wrapper de `ServiceIdentityRepository.register()/rotate()/deactivate()`.
   Nunca exposto via HTTP — provisionamento de identidade roda fora do
   processo web público (ver docstring de `identity_repo.py`).
2. **Migration 003** (`core/migrations/003_identity_lifecycle_audit.sql`) —
   tabela de auditoria `identity_events` + método
   `ServiceIdentityRepository.rotate()`, entregues por um workstream paralelo
   (branch `dev/sprint-0.4-db-identity`) e integrados em `dev/sprint-0.4`
   antes do checkpoint deste Gate.

---

## 1. Checkpoint esperado

- Branch: `dev/sprint-0.4`
- Commit: `e15b7a8` (merge que integra a baseline FINAL da Sprint 0.3 —
  checkpoint `2be672127f413649479afbc4640498ed2b4ec130` — em
  `dev/sprint-0.4`, preservando a implementação do Sprint 0.4: migration 003
  `identity_events`, `ServiceIdentityRepository.rotate()`, CLI
  `manage_service_identity.py` e respectivos testes). O valor foi preenchido
  após o commit final de dev, no padrão do projeto (ver histórico de
  `97b2996` preenchendo `9c5113a`). **Confirme** `git log -1 --format=%H`
  no checkout da
  VPS bate exatamente com o valor publicado pelo Lead Dev antes de prosseguir.

---

## 2. Target permitido

**Supabase Homolog, project ref `esvjfkknrzzziafovwrv`.** Nenhum outro
projeto Supabase é válido para este Gate.

---

## 3. Target proibido

> Copiar esta seção literalmente — não é negociável.

**PROIBIDO**: qualquer operação deste Gate contra o project ref
`wioorhtdwnfujkrynxij` (Produção) ou qualquer outro projeto Supabase que não
seja `esvjfkknrzzziafovwrv`. Se `COGNITIVE_DB_ADMIN_URL` (ou qualquer DSN
derivado) resolver para `wioorhtdwnfujkrynxij`, ou para um host que não seja
reconhecidamente `esvjfkknrzzziafovwrv`, **PARE IMEDIATAMENTE** e reporte ao
Lead Dev. Não prossiga "só para conferir". Não rode migrations, não rode
testes de DB, não conecte — nem para leitura.

---

## 4. Secrets necessários

Nomes de variáveis de ambiente (nunca os valores — não imprima, não logue,
não coloque em relatório):

- `COGNITIVE_DB_ADMIN_URL`
- `COGNITIVE_DB_URL`
- `COGNITIVE_DB_WORKER_URL`

Se qualquer uma estiver ausente, PARE — não prossiga com defaults locais
(`DEFAULT_ADMIN_DSN` do runner/CLI é só para dev local, nunca para o Gate).

---

## 5. Preflight

1. Confirme o checkpoint (Seção 1) bate com o checkout atual.
2. Confirme que o target é Homolog e não é o proibido:
   ```bash
   python scripts/sprint_0_2_remote_gate.py verify-target
   ```
   Esperado: `homolog_match=True`, `forbidden_match=False`, `verified=YES`.
   Qualquer outro resultado → PARE (ver Seção 17).
3. Confirme que migrations 000/001/002 já estão aplicadas e rastreadas:
   ```bash
   python core/migrations/runner.py --status
   ```
   Esperado: `APPLIED [✓]` para `000_foundation_tenancy`,
   `001_capability_registry_audit`,
   `002_service_identities_lookup_least_privilege`. `003_identity_lifecycle_audit`
   deve aparecer como `PENDING` (ainda não aplicada).
4. Rode `--verify` para conferir checksums das migrations já aplicadas:
   ```bash
   python core/migrations/runner.py --verify
   ```
   Esperado: nenhum `CHECKSUM MISMATCH`.

Se qualquer verificação do preflight falhar, PARE — não avance para
migrations.

---

## 6. Migrations

```bash
python core/migrations/runner.py --up
```

Esperado: aplica **apenas** `003_identity_lifecycle_audit`. As três
anteriores devem aparecer como `SKIP (already applied)` — se qualquer uma
delas tentar reaplicar ou reportar `CHECKSUM MISMATCH`, PARE (schema drift,
Seção 17).

Se `003` já estiver aplicada (Gate rodado antes e falhou depois deste
passo), o runner deve reportar `SKIP (already applied): 003` — isso é
esperado e não é um erro; é um no-op idempotente. Não rode `--down` para
"resetar" — isso é destrutivo e fora de escopo deste Gate (ver Seção 17,
nunca tente sua própria correção).

---

## 7. Inspect

`003_identity_lifecycle_audit` **ainda não tem fingerprint registrado** em
`INSPECTION_QUERIES` (`core/migrations/runner.py`) — isso é uma lacuna
conhecida, não um bloqueador. `python core/migrations/runner.py --inspect 003`
vai imprimir `(sem fingerprint cadastrado para 003 — só o tracking acima é
verificado)` e reportar `APPLIED`/`UNKNOWN` baseado só na tabela
`_migrations`. Isso é esperado — não é evidência de falha.

`--status` e `--verify` (Seção 5, passo 3-4) continuam totalmente
aplicáveis a `003` e devem ser reconferidos depois do `--up`:

```bash
python core/migrations/runner.py --status
python core/migrations/runner.py --verify
```

Esperado: `003_identity_lifecycle_audit` agora `APPLIED [✓]`, nenhum
mismatch.

---

## 8. DB tests

```bash
cd core/cognitive
COGNITIVE_MODE=database python -m pytest tests/db/test_identity_lifecycle_audit.py -v
```

Depois, a suíte `tests/db` completa (regressão — nada quebrou nas migrations
000-002 nem nos repositórios existentes):

```bash
python -m pytest tests/db -v
```

Esperado: **zero failures, zero skips** (com os três DSNs configurados e
target Homolog verificado, `conftest.py` não deve pular nenhum teste —
skip aqui é sinal de configuração incompleta, revise a Seção 4 antes de
prosseguir).

---

## 9. API tests

**N/A para este sprint.** Provisionamento de identidade é deliberadamente
CLI-only (ver docstring de `core/cognitive/cognitive/db/repositories/identity_repo.py`)
— nenhuma rota HTTP do Gateway deve chamar `register()`, `deactivate()` ou
`rotate()`. Se durante este Gate você encontrar qualquer rota HTTP nova
expondo esses métodos, isso é um desvio de escopo grave — PARE e reporte
(Seção 17), não prossiga achando que é uma melhoria.

---

## 10. MCP tests

**N/A** — nenhuma superfície MCP foi tocada neste sprint.

---

## 11. E2E — smoke test manual do CLI

Rode em sequência, todos contra Homolog (mesmo `COGNITIVE_DB_ADMIN_URL` do
resto do Gate). Use um `--tenant-id` e `--actor-id` de teste dedicados
(sugestão: um UUID reservado para Gate, análogo a `gate-tenant-a`/
`gate-tenant-b` em `tests/db/conftest.py` — não reutilize identidades de
tenants reais).

1. **Register**:
   ```bash
   python core/cognitive/scripts/manage_service_identity.py \
     --register --tenant-id <gate-test-tenant-uuid> --actor-id gate-smoke-actor --profile owner-core
   ```
   Anote a credential impressa (aparece **uma única vez**). Guarde-a
   temporariamente só para os próximos passos deste smoke test — não a
   reutilize depois, não a coloque no relatório final (Seção 18).

2. **Verificar lookup funciona** — via um script ad hoc de uma linha (não
   crie um script novo permanente para isso):
   ```bash
   python -c "
   import asyncio, os, sys
   sys.path.insert(0, 'core/cognitive')
   from cognitive.db.connection import create_pools, close_pools
   from cognitive.db.repositories.identity_repo import ServiceIdentityRepository

   async def main():
       await create_pools(app_dsn=os.environ['COGNITIVE_DB_URL'])
       repo = ServiceIdentityRepository()
       result = await repo.lookup('<credential-from-step-1>')
       print('lookup_ok' if result is not None else 'lookup_failed')
       await close_pools()

   asyncio.run(main())
   "
   ```
   Esperado: `lookup_ok`.

3. **Rotate**:
   ```bash
   python core/cognitive/scripts/manage_service_identity.py \
     --rotate --old-credential '<credential-from-step-1>'
   ```
   Anote a NOVA credential impressa.

4. **Verificar credential antiga falha, nova funciona** — repita o script
   do passo 2 duas vezes: uma vez com a credential antiga (esperado
   `lookup_failed`), outra com a nova (esperado `lookup_ok`).

5. **Deactivate**:
   ```bash
   python core/cognitive/scripts/manage_service_identity.py \
     --deactivate --credential '<credential-from-step-3>'
   ```
   Confirme que o CLI só mostra um prefixo de hash truncado, nunca a
   credential completa.

6. **Verificar lookup falha após deactivate** — repita o script do passo 2
   com a credential do passo 3. Esperado: `lookup_failed`.

Se qualquer passo divergir do esperado, PARE (Seção 17) — não tente
diagnosticar/corrigir sozinho além de capturar a saída exata para o
relatório.

---

## 12. Security negative tests

- **Cross-tenant `identity_events` read denied**: já coberto pela suíte
  `tests/db` (Seção 8) — referencie os testes de
  `tests/db/test_identity_lifecycle_audit.py` relacionados a isolamento
  cross-tenant no relatório, não reimplemente o teste manualmente.
- **`cognitive_app`/`cognitive_worker` não podem `INSERT` em
  `identity_events`**: idem — referencie o teste correspondente em
  `tests/db/test_identity_lifecycle_audit.py` (deve existir um teste
  análogo aos de `tests/db/test_rls_gate.py::TestRolePrivileges` para
  `service_identities`).
- **CLI nunca ecoa uma credential crua mais de uma vez**: coberto pelos
  testes unitários (`core/cognitive/tests/unit/test_manage_service_identity_cli.py`,
  classes `TestCmdRegister`/`TestCmdRotate`/`TestCmdDeactivate`) — não
  precisa ser reverificado manualmente no Homolog além do smoke test da
  Seção 11 (observe visualmente que a credential só aparece uma vez no
  output de cada comando).
- **CLI nunca loga uma credential crua**: idem — coberto por
  `test_manage_service_identity_cli.py` (asserts contra `caplog`). Durante
  o smoke test (Seção 11), inspecione os logs do CLI (stderr/stdout de
  `logging`, não os `print()` do banner) e confirme visualmente que nenhuma
  linha `INFO`/`ERROR` contém a credential.

---

## 13. Console

**N/A** — nenhuma mudança no `apps/cognitive-console` neste sprint.

---

## 14. Regression

Suíte não-DB completa:

```bash
cd core/cognitive
python -m pytest tests -q
```

(A suíte inteira — `tests/db` pula honestamente sem os três DSNs
configurados; com eles configurados para Homolog, roda de verdade e cai na
Seção 8.)

Baseline antes deste sprint: 199 testes unitários (`tests/unit`) + suíte
`tests/db` (contagem exata depende de quantos testes
`test_identity_lifecycle_audit.py` adiciona — não fixado aqui). Este sprint
adiciona 27 testes novos em `tests/unit/test_manage_service_identity_cli.py`.
Contagem esperada pós-integração: **zero regressões** — todo teste que
passava antes continua passando; a única mudança de contagem esperada é o
incremento pelos testes novos de ambos os workstreams (CLI + audit table).
Qualquer teste que passava antes e agora falha é STOP (Seção 17), não
"talvez seja flaky, roda de novo".

---

## 15. Performance

**N/A / não é uma preocupação nesta escala.** `identity_events` é uma
tabela de auditoria append-only de baixo volume (eventos de
register/rotate/deactivate, não tráfego de request). Não invente um
benchmark para esta seção — se o Lead Dev pedir análise de performance no
futuro, será uma tarefa separada e explícita.

---

## 16. Cleanup

Qualquer dado de teste criado no smoke test E2E (Seção 11) — a
`service_identity` do tenant/actor de Gate — deve terminar **desativada**
ao fim do Gate (o próprio passo 5 da Seção 11 já faz isso, desde que o Gate
tenha chegado até lá com sucesso). Se o Gate parar antes do passo 5 por
qualquer motivo, desative manualmente a credential de teste mais recente
antes de encerrar:

```bash
python core/cognitive/scripts/manage_service_identity.py \
  --deactivate --credential '<credential-mais-recente-do-smoke-test>'
```

Não é necessário (nem desejável) fazer `DELETE` na linha de
`service_identities` ou em `identity_events` — desativação é suficiente e
preserva o rastro de auditoria, que é o propósito da tabela.

---

## 17. STOP conditions

Pare imediatamente e reporte ao Lead Dev — **nunca tente sua própria
correção** — se qualquer um destes ocorrer:

- Qualquer falha em `tests/db` (Seção 8) ou nos testes referenciados na
  Seção 12.
- Qualquer vazamento cross-tenant observado (em teste automatizado ou no
  smoke test manual).
- Uma credential crua (não hash) aparecendo em qualquer log, stdout fora do
  banner "SHOWN EXACTLY ONCE", relatório, ou saída de qualquer comando além
  do exatamente esperado pela Seção 11.
- Qualquer schema drift inesperado — `--verify` (Seção 5/7) reportando
  `CHECKSUM MISMATCH`, ou `--status` mostrando uma migration em estado
  diferente do esperado.
- `verify-target` (Seção 5, passo 2) não reportar `homolog_match=True` e
  `forbidden_match=False` — isso inclui qualquer ambiguidade sobre qual
  projeto está configurado.
- Migration `003` tentando aplicar contra qualquer coisa que não seja
  Homolog.

---

## 18. Formato do relatório

Ao final (sucesso ou STOP), publique um relatório espelhando o estilo já
usado neste projeto para relatórios de Gate/hotfix (ex.: os relatórios de
Sprint 0.3 como "SEC-002 review follow-ups" e "migration atomicity +
ownership hotfix" — ver `git log --oneline` nas branches `dev/sprint-0.3*`
para o tom e nível de detalhe esperado). Isto descreve o **formato**
esperado do relatório futuro — não escreva o relatório em si agora, ele só
existe depois da execução real do Gate.

Estrutura esperada:

- **Status**: um veredito curto e inequívoco no topo (ex.: `GATE PASSED`,
  `GATE FAILED at step=<nome>`, `GATE STOPPED — <motivo>`).
- **Root cause** (se houve falha): o que quebrou e por quê — só se
  aplicável; omita a seção inteira se o Gate passou limpo.
- **Findings**: lista objetiva do que foi verificado e o resultado de cada
  seção (1-17), especialmente contagens de teste (Seção 8, 14) e o
  resultado do smoke test (Seção 11) passo a passo.
- **Checkpoint**: o commit hash real que rodou (deve bater com o commit da
  Seção 1 — se não bater, isso por si só é motivo de nota no relatório).
- **Published**: onde o relatório foi deixado (commit message, doc, ambos)
  e para quem — nunca inclua nenhuma credential, DSN completo, ou senha em
  qualquer parte publicada, mesmo em rascunho.
