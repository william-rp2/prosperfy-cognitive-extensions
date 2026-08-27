# Phase 1B — Slice 1G: Final Pre-Human Gate (status — BLOCKED no enforcement)

> GRANT_LIVE=YES (operador). EXECUTOR ENFORCEMENT não implementado nesta sessão —
> inspeção/edição do código do executor (gate-0.3) bloqueada por truncamento do canal
> host. Per regra do slice, os testes positivos live NÃO podem rodar sem o enforcement.

## 1. Estado confirmado

```
GRANT_LIVE=YES (operador provisionou: capability_grants tenant=11a26649…,
  profile=hermes-homolog, infra.action, policy_override=allow)
TENANT_ID=11a26649-91d0-4971-8d1f-2afc57f8b5ae · PROFILE=hermes-homolog
Homolog: project_ref=esvjfkknrzzziafovwrv · forbidden_production=wioorhtdwnfujkrynxij
```

## 2. Executor enforcement — NÃO implementado (bloqueado)

```
Necessário: fail-closed no boundary real de infra.action (gate-0.3 executor/adapter):
  capability=infra.action · action=restart · target_type=container · target não vazio ·
  resource autorizado → args {host=<binding>, container=<target>, acao=restart, confirmar=true}
  (acao/confirmar DERIVADOS após validação — nunca do caller)
Inspeção/edição do código do executor (execution/ + adapters/prosperfy_skills) bloqueada:
  canal host truncando multi-linha + bloqueio de regex. Não confio em modificar o código
  do Cognitive às cegas.
ADAPTER_ENFORCEMENT=PENDING · RESTART_ONLY_AT_EXECUTION_BOUNDARY=PENDING
```

## 3. Testes — BLOQUEADOS (per regra do slice)

```
"NÃO chamar infra.action live antes do enforcement estar deployado."
POLICY_POSITIVE=BLOCKED (sem enforcement, chamar restart+Prosperfy = RESTART REAL)
POLICY_NEGATIVES (com grant): executáveis apenas os que NÃO passam do grant layer
  (Black/Manager1/Hostinger/start/stop/delete/server/vazio → o grant layer + resource auth
  deve DENY antes do MCP) — parcialmente verificáveis; sem enforcement não provo o
  restart-only no executor.
ADAPTER_DRY_RUN=BLOCKED (requer o intercept antes da MCP = enforcement)
CONFIRMATION_FIRST_TURN=BLOCKED (fluxo live)
```

## 4. Gate

```
GRANT_LIVE=YES · RESOURCE_SCOPE_EFFECTIVE=Prosperfy-only (por garantir no executor)
POLICY_POSITIVE=BLOCKED · POLICY_NEGATIVES=parcial (grant layer)
ADAPTER_ENFORCEMENT=PENDING · ADAPTER_DRY_RUN=BLOCKED
IDEMPOTENCY_REGRESSION=parcial (API healthy — sem crash) · PHASE1A_REGRESSION=PENDING
HERMES_WIRING=core pronto (2984ed5) · CONFIRMATION_FIRST_TURN=BLOCKED
REAL_RESTART_BY_OPENCODE=NO
PHASE1B_RESTART_HUMAN_TEST_READY=NO
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```

## 5. Próximo passo (execução dedicada / operador)

```
1. Implementar o enforcement restart-only no executor de infra.action (gate-0.3):
   validação → args {host, container, acao=restart, confirmar=true} (derivados)
2. Recurso Prosperfy-only (reutilizar resource auth canônico)
3. Deploy Cognitive (restart com Host Trust) + dry-run intercept
4. Policy positives/negatives + idempotency + Phase 1A regression
5. Reload Hermes (Host Trust) + confirmation first-turn (sem mutação)
6. SÓ ENTÃO PHASE1B_RESTART_HUMAN_TEST_READY=YES
```