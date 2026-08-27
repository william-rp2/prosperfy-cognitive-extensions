# Phase 1B — Slice 1F: Admin Grant + Enforcement (resultado: ADMIN_ACCESS=FAIL → STOP)

> Sem caminho canônico seguro acessível ao AGENTE para executar GrantRepository com
> COGNITIVE_DB_ADMIN_URL. Per §2: ADMIN_ACCESS=FAIL → STOP. O operador provisiona o grant.

## 1. Admin context (inspecionado)

```
ADMIN_BOOTSTRAP_ENTRYPOINT=scripts/sprint_0_2_remote_gate.py (bootstrap/operator)
ADMIN_CREDENTIAL_SOURCE_TYPE=operator bootstrap (credencial admin PROTEGIDA — fora do env
  do runtime; o env do serviço api-runtime-sprint03.env NÃO contém COGNITIVE_DB_ADMIN_URL
  nem COGNITIVE_DB_URL — nomes verificados, valores não lidos)
ADMIN_DSN_AVAILABLE_TO_OPERATOR=YES (via fluxo bootstrap do operador)
ADMIN_DSN_AVAILABLE_TO_AGENT=NO (não extrair/exportar credencial admin — regra do slice)
```

## 2. Gate (per §2)

```
ADMIN_ACCESS=FAIL
  Não existe forma segura/canônica acessível ao AGENTE de executar GrantRepository.upsert
  com COGNITIVE_DB_ADMIN_URL. O DSN admin é do operador/bootstrap.
  NÃO criar credencial nova · NÃO usar Production DSN · NÃO contornar RLS com SQL
  improvisado. → STOP.
```

## 3. Estado (nada mutado)

```
GRANT_BEFORE=ausente (policy real deny — comprovado pelos DENIED) · GRANT_LIVE=NO
POLICY_NEGATIVES=PASS (fail-closed) · POLICY_POSITIVE=PENDING (requer grant)
ADAPTER_ENFORCEMENT=PENDING (código do executor — restart-only, acao derivado)
infra.action registrada live (deny) · COGNITIVE_HEALTH=active (PID 3944123) · sem crash
HERMES_WIRING=core pronto (2984ed5) · REAL_RESTART_BY_OPENCODE=NO
PHASE1B_RESTART_HUMAN_TEST_READY=NO · PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```

## 4. Operação do operador (para destravar)

```
1. Executar o bootstrap/script canônico (GrantRepository.upsert, admin):
   capability_grants(tenant=11a26649…, profile=hermes-homolog, capability=infra.action,
   policy_override=allow, active=true) — SOMENTE isso (não mexer em infra.inspect)
2. Garantir autorização de RECURSO Prosperfy-only no executor (capability_grants não tem
   coluna resource — o recurso é validado na execução, reutilizando o mecanismo de
   infra.inspect) + enforcement restart-only (acao derivado após validação restart)
3. Depois do grant: policy positive (ALLOW Prosperfy) + negatives (Black/Manager1/Hostinger/
   start/stop/delete/server/vazio → DENY) · dry-run args {host, container, acao=restart,
   confirmar=true} · idempotency · Phase 1A regression · confirmation first-turn (sem
   mutação) · reload com Host Trust → HUMAN_TEST_READY
```