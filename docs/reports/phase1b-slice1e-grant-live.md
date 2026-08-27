# Phase 1B — Slice 1E: Live Grant + Enforcement (status — PRE-HUMAN GATE NÃO passou)

> capability_grants schema inspecionado. GRANT NÃO provisionado (admin DSN/BYPASSRLS
> indisponível nos envs acessíveis — operação de bootstrap dedicada). Enforcement
> restart-only = código pendente. Sem restart real.

## 1. Schema REAL de capability_grants (inspecionado)

```
CAPABILITY_GRANTS_COLUMNS=[tenant_id, profile, capability_id, policy_override, active]
PRIMARY_KEY/UNIQUE=(tenant_id, profile, capability_id) (ON CONFLICT no upsert)
REQUIRED_COLUMNS=[tenant_id, profile, capability_id] · policy_override nullable
RESOURCE_SCOPE_FIELD=<ABSENT> — grant é por-CAPABILITY, sem coluna de resource
PROFILE_OR_IDENTITY_FIELD=profile · SCOPE_FIELD=policy_override
GrantRepository: get_grant(tenant, profile, capability) RLS; upsert admin (BYPASSRLS) idempotente
→ RESOURCE_SCOPE granular por-resource NÃO existe na tabela; o escopo Prosperfy-only deve
  ser garantido pela autorização de RECURSO no executor (a capability recebe o resource e
  valida se a identidade pode usá-lo) — a documentar/validar na execução dedicada.
```

## 2. Grant — NÃO provisionado (honestidade)

```
GrantRepository.upsert/get_profile usam admin_connection (COGNITIVE_DB_ADMIN_URL / BYPASSRLS),
que NÃO está no env do uvicorn (só app+worker) nem nos arquivos acessíveis (referenciado em
scripts/sprint_0_2_remote_gate.py — caminho de bootstrap com credencial).
GRANT_BEFORE=NONE (não lido via admin; policy real = deny, comprovado pelos DENIED anteriores)
GRANT_LIVE=NO · RESOURCE_SCOPE=não aplicável (sem coluna resource; Prosperfy-only a garantir
  pela autorização de recurso)
```

## 3. Policy (estado atual, fail-closed)

```
restart+container(Prosperfy) → DENIED (sem grant — ZERO restart) ✓
start/stop/delete/restart+server → DENIED ✓ · infra.inspect → ALLOW ✓
POLICY_POSITIVE=PENDING (requer grant) · POLICY_NEGATIVES=PASS (fail-closed)
```

## 4. Adapter enforcement — código pendente (boundary executável)

```
A spec YAML NÃO é segurança (loader ignora chaves custom). O executor/adapter que monta a
  chamada MCP deve fail-close ANTES da invocation: capability=infra.action · action=restart ·
  target_type=container · target não vazio · resource autorizado → args {host, container,
  acao=restart, confirmar=true} (acao derivado do action validado — NUNCA input direto).
ADAPTER_ENFORCEMENT=PENDING · RESTART_ONLY_AT_EXECUTION_BOUNDARY=PENDING
```

## 5. Métricas

```
BRANCH=dev/phase1b-restart-container · CHECKPOINT=d7800b4
CAPABILITY_GRANTS_SCHEMA=inspecionado · GRANT_BEFORE=N/A(admin) · GRANT_AFTER=N/A
GRANT_LIVE=NO · POLICY_NEGATIVES=PASS · POLICY_POSITIVE=PENDING
ADAPTER_ENFORCEMENT=PENDING · ADAPTER_DRY_RUN=PENDING
HERMES_WIRING=core pronto (2984ed5) · CONFIRMATION_FIRST_TURN=PENDING
IDEMPOTENCY_REGRESSION=COGNITIVE_API_CRASH=NO · COGNITIVE_HEALTH=active (PID 3944123)
PHASE1A_REGRESSION=PENDING · REAL_RESTART_BY_OPENCODE=NO
PHASE1B_RESTART_HUMAN_TEST_READY=NO
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```

## 6. Próximo passo (execução dedicada/operador)

```
1. Resolver o admin DSN (bootstrap/scripts) + provisionar o grant via GrantRepository.upsert
   (capability_grants: tenant · profile=hermes-homolog · infra.action · policy_override=allow)
2. Garantir autorização de RECURSO (Prosperfy-only) no executor (a capability_grants não tem
   resource scope — o recurso deve ser validado na execução)
3. Implementar enforcement restart-only no adapter/executor + dry-run (args exatos)
4. Policy positive (ALLOW Prosperfy) + negatives após grant · idempotency · Phase 1A regression
5. Confirmation first-turn (sem mutação) · reload com Host Trust
6. SÓ ENTÃO PHASE1B_RESTART_HUMAN_TEST_READY=YES
```