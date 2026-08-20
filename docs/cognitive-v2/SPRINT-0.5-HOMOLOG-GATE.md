# Sprint 0.5 — Homolog Gate QA Plan

> Este documento é operacional e autocontido. Foi escrito para ser executado
> por um agente diferente, com acesso à VPS/Homolog e ZERO contexto desta
> conversa. Siga as seções em ordem. Não interprete intenção — se algo aqui
> for ambíguo, pare e reporte ao Lead Dev em vez de decidir sozinho.

Escopo do Sprint 0.5: **primeiro vertical slice utilizável** — o caso
funcional "Como estão meus servidores?" atravessando a cadeia completa com
dados REAIS:

```
Hermes (client fino) → Cognitive API → Identity/Tenant/Actor
→ Capability Registry → Policy → Resource Resolver → ProsperfySkill Adapter
→ MCP → VPS → resultado consolidado → Hermes
```

Entregas nesta branch (`dev/sprint-0.5`):

1. **`CognitiveApiAdapter`** (`hermes/capability-intelligence/.../transport/
   cognitive_api_adapter.py`) — client fino do Hermes que implementa o
   `ProtocolAdapter` existente (passo 2 da migração de
   `27-HERMES-INTEGRATION.md`) falando o contrato HTTP real do gateway:
   `GET /v1/status`, `GET /v1/capabilities[/{id}]`,
   `POST /v1/capabilities/{id}/execute`. Fail-closed em 4xx/5xx, erro de
   transporte e `status=failed`; credencial nunca vazada.
2. **`server_views.build_server_status_view()`** — consolidação
   determinística `raw → normalized → summary` (PT-BR) da capability
   `infra.inspect`, sem LLM, sem framework.
3. **`scripts/sprint_0_5_servidores.py`** — demo "Como estão meus
   servidores?" com `--environment dev|homolog` (homolog exige
   `COGNITIVE_LIVE_MCP=1` + URL allowlistada).
4. **Testes DEV E2E** (`tests/test_sprint_05_e2e_local.py` + unit tests)
   provando o slice completo contra o gateway in-memory, inclusive o caminho
   negativo (DENY/401 fail-closed) e a trilha de auditoria.

**Este Gate NÃO executa nada contra Homolog** — é o runbook que será usado
quando o Lead Dev autorizar a execução. Nenhum passo abaixo deve ser rodado
antes dessa autorização.

---

## 1. Checkpoint esperado

- Branch: `dev/sprint-0.5`
- Commit de código: `ef357ea` (implementação do slice — client, views, demo
  runner, testes). A branch pode carregar por cima um commit de docs
  (este runbook) — o operador deve fazer checkout no commit de código:
  ```bash
  git checkout ef357ea
  git log -1 --format=%H
  ```
  Esperado: exatamente `ef357ea`. Qualquer outro valor → PARE (Seção 16).

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
- `MCP_PROSPERFYSKILLS_API_KEY` (lida pelo gateway no host da API)
- `COGNITIVE_GATEWAY_CREDENTIAL` + `COGNITIVE_TENANT_ID` + `COGNITIVE_ACTOR_ID`
  (identidade da service identity do slice — ver Seção 11)

Se qualquer uma estiver ausente, PARE — não prossiga com defaults locais.

---

## 5. Preflight

1. Confirme o checkpoint (Seção 1) bate com o checkout atual.
2. Confirme que o target é Homolog e não é o proibido:
   ```bash
   python scripts/sprint_0_2_remote_gate.py verify-target
   ```
   Esperado: `homolog_match=True`, `forbidden_match=False`, `verified=YES`.
   Qualquer outro resultado → PARE (ver Seção 16).
3. Confirme que as migrations 000/001/002/003 estão aplicadas e rastreadas:
   ```bash
   python core/migrations/runner.py --status
   python core/migrations/runner.py --verify
   ```
   Esperado: `APPLIED [✓]` para `000_foundation_tenancy`,
   `001_capability_registry_audit`,
   `002_service_identities_lookup_least_privilege`,
   `003_identity_lifecycle_audit`; nenhum `CHECKSUM MISMATCH`.

Se qualquer verificação falhar, PARE — não avance.

---

## 6. Migrations

**Nenhuma.** Este sprint não adiciona migration (`NEW_MIGRATIONS=0`).

---

## 7. Inspect

**N/A** — nada mudou no schema. As migrações 000-003 devem continuar
`APPLIED` e sem mismatch (já conferidas na Seção 5).

---

## 8. DB tests

```bash
cd core/cognitive
COGNITIVE_MODE=database python -m pytest tests/db -v
```

Esperado: **zero failures, zero skips** (com os três DSNs configurados e
target Homolog verificado). Skip aqui é sinal de configuração incompleta.

---

## 9. API tests / regression não-DB

```bash
cd core/cognitive
python -m pytest tests -q
```

Esperado: **zero regressões**. Baseline pré-sprint: 456 passed / 91 skipped
(91 = DB suite sem DSNs no ambiente local; com DSNs cai na Seção 8). Este
sprint não altera `core/cognitive` além de nada — nenhum teste existente
pode mudar de resultado.

---

## 10. Hermes plugin suite

```bash
cd hermes/capability-intelligence
python -m pytest tests -q
```

Esperado: **zero failures**. Baseline pós-sprint: 308 passed, 1 skipped
(skip pré-existente) — inclui os 30 testes novos: 23 unit
(`test_cognitive_api_adapter.py` + `test_server_views.py`) e 7 DEV E2E do
slice (`test_sprint_05_e2e_local.py`, incl. reprodução do FAIL de resource do
Homolog). Qualquer teste que passava antes e agora falha é STOP (Seção 16).

---

## 11. E2E — smoke test manual do slice (READ-ONLY)

A capability `infra.inspect` é read-only (`default_policy: allow`). O
runner `scripts/sprint_0_5_servidores.py` não escreve em dados de produção —
só lê panorama/containers/portas da VPS e grava a trilha de auditoria normal
do gateway (1 `audit_events` por execução, scoped ao tenant/actor da
identidade usada).

Rode em sequência, todos contra Homolog:

1. **Reuse o contexto sintético do Sprint 0.3** (se ainda existir em Homolog)
   ou **provisione uma service identity dedicada** para o slice:
   ```bash
   python scripts/sprint_0_3_synthetic_context.py bootstrap-homolog-context
   ```
   → grava o caminho do arquivo de credencial (nunca o valor) em stdout.
   Se optar por service identity própria, use
   `core/cognitive/scripts/manage_service_identity.py --register
   --tenant-id <gate-test-tenant-uuid> --actor-id sprint05-actor
   --profile owner-core` e exporte `COGNITIVE_GATEWAY_CREDENTIAL`,
   `COGNITIVE_TENANT_ID`, `COGNITIVE_ACTOR_ID`.

   > **Resource selector (obrigatório).** O resource provisionado no Homolog
   > pelo bootstrap 0.3 tem resource_key `homolog-synthetic-vps` — NÃO
   > `prosperfy-main`. O `InfraService`/runner usa por default o selector de
   > DEV (`prosperfy-main`), que **não existe** no Homolog → Resource Resolver
   > falha (status=failed, REAL_VPS_DATA=NO). Defina explicitamente o selector
   > correto em **todo** o smoke test abaixo:
   > ```bash
   > export COGNITIVE_RESOURCE_KEY=homolog-synthetic-vps
   > ```
   > (ou passe `--resource homolog-synthetic-vps` no runner). Nunca hardcode
   > um host — o selector é só o resource lógico; o host vem do
   > `tenant_resources` no Cognitive.

2. **Preflight de runtime e host do resource (2ª falha).** No retry anterior,
   `RESOURCE_FOUND=YES` e `GRANT_FOUND=YES`, mas `MCP_CALLS_CONFIRMED=NO` e
   `REAL_VPS_DATA=NO` com `REQUEST_LATENCY_MS≈12s`. O trace DEV
   (`test_infra_inspect_fanout_three_tools_reaches_adapter`) prova que, com
   resource resolvido, o orchestrator seleciona as 3 tools e chama o adapter —
   **não há bug de código** nesse trecho. As duas causas operacionais a
   eliminar ANTES de executar o slice:

   a. **`COGNITIVE_LIVE_MCP` efetivamente ativo no PROCESSO da API.** Mudar o
      EnvironmentFile não altera um processo já em memória. Confirme que o
      serviço foi reiniciado/recarregado após o env temporário e que o
      processo novo lê `COGNITIVE_LIVE_MCP=1`:
      ```bash
      # no host da API — nunca imprima secrets
      systemctl show <servico> -p ActiveState -p EnvironmentFile  # nome do serviço real
      # confirme que o processo em execução foi iniciado APÓS a edição do env
      systemctl restart <servico>   # quando o Gate autorizar
      ```
      `PROCESS_LIVE_MCP=1` é condição necessária: com `0`, o gateway usa
      `MockSkillsAdapter` e a resposta seria `completed` com dados mock
      (host `mock-host`, latência baixa) — não é o que o retry reportou.

   b. **`resolved_params.host` do resource alcançável.** O MCP tenta conectar
      em `tenant_resources.resolved_params.host`. Se o contexto sintético foi
      re-bootstrapado SEM `--resource-host`, o host fica
      `synthetic-e2e-placeholder.invalid` (placeholder do
      `sprint_0_3_synthetic_context.py`) → conexão falha em ~10-12s →
      `status=failed`, `REAL_VPS_DATA=NO`. O bootstrap do contexto sintético
      para este Gate DEVE provisionar `homolog-synthetic-vps` com o host REAL
      da VPS:
      ```bash
      python scripts/sprint_0_3_synthetic_context.py bootstrap-homolog-context \
          --resource-host <host-real-da-vps>
      ```
      Confirme (sem imprimir DSN/secret) que `resolved_params` contém um host
      alcançável e não o placeholder. Se o contexto 0.3 original ainda existir
      em Homolog com host real, reutilize-o; NUNCA rode o slice com placeholder.

3. **Pré-condições do runner** (falha fechada sem `COGNITIVE_LIVE_MCP=1` e
   sem URL homolog allowlistada):
   ```bash
   export COGNITIVE_LIVE_MCP=1
   export COGNITIVE_HOMOLOG_API_URL=https://api-cognitive-homolog.prosperfy.com.br
   python scripts/sprint_0_5_servidores.py \
       --environment homolog --gateway-url "$COGNITIVE_HOMOLOG_API_URL"
   ```
   Esperado: executa e imprime `=== normalized ===`, `=== summary ===` e
   `DEMO_RESULT=OK`. Sem `COGNITIVE_LIVE_MCP=1` o runner deve recusar com
   `GATE_REFUSED` antes de qualquer chamada HTTP (validar isso ANTES de
   exportar a variável).

4. **Valide o summary**: host real da VPS, uptime, contagem de containers e
   portas coerentes com o estado real. Confirme visualmente que o summary
   está em PT-BR e que nenhuma credencial ou `Authorization` aparece em
   qualquer stdout/stderr.

5. **Trilha de auditoria** — via script ad hoc de uma linha (não crie
   script novo permanente), verifique que a execução deixou `audit_events`
   com o tenant/actor/capability/correlation corretos e sem secret em
   `inputs_redacted` (mesma técnica da Seção 11 do Gate 0.3):
   ```bash
   python -c "
   import asyncio, os, sys
   sys.path.insert(0, 'core/cognitive')
   from cognitive.db.connection import create_pools, close_pools
   from cognitive.db.repositories.audit_repo import PostgresAuditWriter
   async def main():
       await create_pools(app_dsn=os.environ['COGNITIVE_DB_URL'])
       rows = await PostgresAuditWriter().fetch_for_tenant('<tenant-uuid>')
       print('audit_rows=%d' % len(rows))
       await close_pools()
   asyncio.run(main())
   "
   ```
   Esperado: pelo menos 1 linha para o tenant do slice, `outcome=COMPLETED`,
   `capability_id=infra.inspect`.

6. **LLM_CALLS=0** — fato de código, não medido em runtime: a composição da
   capability é determinística (sequência de tools do YAML) e
   `server_views` é função pura. Nenhum chamado LLM existe no caminho.

---

## 12. Security negative tests

- **DENY (sem grant) / 401 (credential inválida) / fail-closed**: já coberto
  pelos testes DEV E2E do slice (`tests/test_sprint_05_e2e_local.py`:
  `test_deny_fails_closed_without_adapter_call`,
  `test_unknown_credential_401_fails_closed`) e pela suíte `tests/db`
  (cross-tenant/RLS). Referencie no relatório — não reimplemente
  manualmente.
- **Boundary guard (11 forbidden keys)**: coberto pela suíte unit do
  Cognitive (`test_prosperfy_skills_guard.py`) e pelo `run-negative` do
  Gate 0.3 — não reimplementar aqui.
- **Credencial nunca vazada**: coberto por `test_cognitive_api_adapter.py`
  (`test_execute_failed_raises_and_redacts_credential`,
  `test_transport_error_fail_closed`, `test_http_500_raises_and_redacts`) e
  visualmente no smoke test (Seção 11 passo 3).

---

## 13. Console

**N/A** — nenhuma mudança em `apps/cognitive-console`.

---

## 14. Performance

Reporte apenas os números que o runner/API expõem (mesmo espírito do Gate
0.3): wall-clock do round trip completo do smoke test (Seção 11) medido pelo
operador, `tool_calls` inferido de `len(response.data)` (3 para
`infra.inspect`) e `llm_calls=0`. Não invente benchmark além disso.

---

## 15. Cleanup

1. Deletar o arquivo de credencial do contexto sintético (ou desativar a
   service identity dedicada via `manage_service_identity.py --deactivate`).
2. Confirmar que não sobrou `audit_events` além das linhas scoped ao
   tenant/actor do slice (a trilha de auditoria é o propósito da tabela —
   não faça DELETE).

---

## 16. STOP conditions

Pare imediatamente e reporte ao Lead Dev — **nunca tente sua própria
correção** — se qualquer um destes ocorrer:

- Qualquer falha nas suítes das Seções 8/9/10, ou qualquer teste que passava
  antes e agora falha.
- Qualquer vazamento de credential/segredo em log, stdout, relatório ou
  resposta.
- `verify-target` (Seção 5) não reportar `homolog_match=True` e
  `forbidden_match=False`.
- Qualquer `CHECKSUM MISMATCH` ou migration em estado inesperado.
- O smoke test (Seção 11) não completar com `DEMO_RESULT=OK`, ou o summary
  mostrar dados incoerentes (host/containers/portas inexistentes).
- Qualquer chamada do runner/suite tocando Produção (`wioorhtdwnfujkrynxij`).

---

## 17. Formato do relatório

Espelhar o estilo dos relatórios de Gate/hotfix anteriores (Sprint 0.3/0.4 —
ver `git log --oneline`). Estrutura esperada:

- **Status**: veredito curto e inequívoco no topo (ex.: `GATE PASSED`,
  `GATE FAILED at step=<nome>`, `GATE STOPPED — <motivo>`).
- **Root cause** (se houve falha): o que quebrou e por quê — só se
  aplicável.
- **Findings**: resultado de cada seção (1-16), contagens de teste,
  resultado do smoke test passo a passo, resumo do summary obtido.
- **Checkpoint**: commit hash real que rodou (deve bater com `ef357ea`).
- **Published**: onde o relatório foi deixado e para quem — nunca inclua
  credential, DSN completo ou senha em qualquer parte publicada.