# Phase 1B — Slice 1D: Grant + Enforcement + Wiring (status)

> Identidade resolvida + mecanismo de grant identificado. PROVISIONAMENTO do grant +
> enforcement restart-only no adapter + dry-run = pendentes (DB/código, execução dedicada).

## 1. Identidade REAL (resolvida)

```
TENANT_ID=11a26649-91d0-4971-8d1f-2afc57f8b5ae
ACTOR_ID=hermes-homolog (SERVICE_IDENTITY do Hermes no Cognitive Homolog)
BASE_URL=https://api-cognitive-homolog.prosperfy.com.br
SERVICE_IDENTITY=hermes-homolog · PROFILE=<derivado do actor pelo Cognitive> (a confirmar)
CURRENT_SCOPES/GRANTS: infra.inspect (leitura — Phase 1A); infra.action AUSENTE (deny)
```

## 2. Mecanismo de grant

```
GrantResolverPort → PostgresGrantResolver → GrantRepository (capability_grants, RLS,
  migration 000). resolve_grant(tenant_id, profile, capability_id).
Tabela 'grants' NÃO existe (testado) — o mecanismo é capability_grants.
```

## 3. Grant pendente (exato — executar em execução dedicada)

```
INSERT capability_grants: tenant=11a26649… · profile=<hermes-homolog> ·
  capability=infra.action · scope=infra:write · resource=prosperfy-vps-homolog (SOMENTE)
NÃO conceder Black/Manager1/Hostinger/wildcard.
GRANT_LIVE=NO (não provisionado nesta sessão — DB env + insert exigiram friction
  excessivo; documentado exatamente p/ a execução dedicada)
```

## 4. Policy state (testado no live, sem mutação)

```
restart+container (Prosperfy) → DENIED (sem grant — fail-closed, ZERO restart) ✓
start/stop/delete/restart+server → DENIED ✓
infra.inspect → ALLOW (Phase 1A intacta — CAPABILITIES=[infra.action, infra.inspect])
POLICY_NEGATIVES=PASS (fail-closed) · POLICY_POSITIVE=PENDING (requer grant)
```

## 5. Adapter enforcement — pendente (código Cognitive)

```
Enforcement restart-only DEVE estar no executor/adapter (antes da MCP invocation):
  capability=infra.action · action=restart · target_type=container · target não vazio ·
  resource autorizado → args {host, container, acao=restart, confirmar=true}
NÃO confiar só no YAML (validation_rules é spec; loader ignora chaves custom).
ADAPTER_ENFORCEMENT=PENDING · RESTART_ONLY_AT_ADAPTER=PENDING
```

## 6. Dry-run / wiring / confirmação — status

```
MCP_TOOL=prosperfy_vps_controlar_container · MCP_ARGS esperado {host, container,
  acao=restart, confirmar=true} (schema observado — Slice 1C)
ADAPTER_DRY_RUN=PENDING · HERMES_WIRING=2984ed5 (restart_container→infra.action já) ·
  CONFIRMATION_FIRST_TURN=PENDING (teste de contrato sem mutação) ·
  ZERO_MUTATION_BEFORE_CONFIRMATION=confirmado (nada executou — deny)
IDEMPOTENCY_REGRESSION=COGNITIVE_API_CRASH=NO (restart pós-correção; health a re-confirmar)
```

## 7. Métricas

```
BRANCH=dev/phase1b-restart-container · CHECKPOINT=2bccbd9
IDENTITY_RESOLVED=YES · GRANT_LIVE=NO · RESOURCE_SCOPE=Prosperfy-only (planejado)
POLICY_NEGATIVES=PASS · POLICY_POSITIVE=PENDING · ADAPTER_ENFORCEMENT=PENDING
ADAPTER_DRY_RUN=PENDING · CONFIRMATION_FIRST_TURN=PENDING
COGNITIVE_HEALTH=active (PID 3944123) · HERMES_WIRING=core pronto (2984ed5)
PHASE1A_REGRESSION=PENDING (a re-validar pós-wiring) · REAL_RESTART_BY_OPENCODE=NO
PHASE1B_RESTART_HUMAN_TEST_READY=NO
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```