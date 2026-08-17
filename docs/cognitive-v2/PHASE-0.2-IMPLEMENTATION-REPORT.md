# Sprint 0.2 Implementation Report

## Status

**BLOCKED** — execução remota no servidor Prosperfy não disponível nesta sessão (VPS MCP: `PERMISSION_DENIED`). Código de gate/harness/fail-closed **implementado e commitado**; migrations e testes DB contra Homolog **pendentes de execução no servidor**.

---

## Environment

| Variável | Status (agente local) |
|----------|------------------------|
| `COGNITIVE_DB_ADMIN_URL` | NOT_AVAILABLE locally — AVAILABLE on Prosperfy server (claim humano) |
| `COGNITIVE_DB_URL` | NOT_CONFIGURED (derivar pós-migration no servidor) |
| `COGNITIVE_DB_WORKER_URL` | NOT_CONFIGURED (derivar pós-migration no servidor) |

| Target | Valor |
|--------|-------|
| Homolog esperado | `esvjfkknrzzziafovwrv` |
| Produção proibida | `wioorhtdwnfujkrynxij` — **não tocada** |

---

## Git

| Campo | Valor |
|-------|-------|
| Starting checkpoint | `a32750c` |
| Implementation checkpoint | ver commit final desta sessão |
| Branch | `master` |

---

## Implementado nesta sessão (pré-gate remoto)

1. **`COGNITIVE_MODE`** — `in_memory` vs `database`; fail-closed em database mode
2. **`IdentityResolver`** — sem fallback permissivo em database mode
3. **`tests/db/conftest.py`** — REMOTE DSN mode (Homolog) + testcontainers opcional
4. **Testes RLS** — roles reais `cognitive_app` / `cognitive_worker` (não admin simulado)
5. **`test_rls_gate.py`** — connection reuse, worker RLS, grants, privilege escape
6. **`scripts/sprint_0_2_remote_gate.py`** — runner para servidor Prosperfy
7. **Unit tests** — `test_runtime_modes.py` (5 testes fail-closed)

---

## Migrations

| Migration | Status Homolog |
|-----------|----------------|
| `000_foundation_tenancy.sql` | **PENDING** — aguarda `runner.py --up` no servidor |
| `001_capability_registry_audit.sql` | **PENDING** |

Rollbacks disponíveis: `core/migrations/rollback/000_rollback.sql`, `001_rollback.sql`  
Rollback **não** executar em Homolog compartilhado (testes de rollback skip em remote mode).

---

## Database Identity Model (design — evidência Homolog pendente)

| Role | Migration | BYPASSRLS esperado |
|------|-----------|-------------------|
| `cognitive_admin` | 000 | YES (role attribute) |
| `cognitive_app` | 000 | NO |
| `cognitive_worker` | 000 | NO |
| Conexão admin DSN | Supabase `postgres` user | superuser — **não** equivale automaticamente a `cognitive_admin`; gate script inspeciona `pg_roles` |

---

## Tests (local agent — sem Homolog DSN)

| Suíte | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| In-memory + unit (incl. 5 novos) | 50 | 0 | 0 |
| DB integration | 0 | 28 | 0 |
| Full suite | 50 | 28 | 0 |

Gate **não pode PASS** até `scripts/sprint_0_2_remote_gate.py full-gate` no servidor com DSNs configurados.

---

## Exact Next Action (desbloqueio)

No **servidor Prosperfy** (repo atualizado, secrets remotos presentes):

```bash
# 1. Verificar target (não expõe secrets)
python scripts/sprint_0_2_remote_gate.py verify-target

# 2. Aplicar migrations
python scripts/sprint_0_2_remote_gate.py migrate

# 3. Validar schema + roles + RLS
python scripts/sprint_0_2_remote_gate.py validate-schema

# 4. Configurar COGNITIVE_DB_URL + COGNITIVE_DB_WORKER_URL (secret remoto)
#    ou COGNITIVE_APP_PASSWORD + COGNITIVE_WORKER_PASSWORD

# 5. Testes DB
python scripts/sprint_0_2_remote_gate.py test-db

# Ou tudo:
python scripts/sprint_0_2_remote_gate.py full-gate
```

Depois: `cd core/cognitive && COGNITIVE_MODE=in_memory python -m pytest tests/ -v` (regressão).

---

## Decision Gates

| Gate | Estado |
|------|--------|
| DG-001 ambiente | Homolog provisionado (`esvjfkknrzzziafovwrv`) — **RLS não comprovado ainda** |
| DG-001-C roles | Pendente pós-migration |

---

## Next Phase

**Sprint 0.3 — NOT STARTED**

---

*Atualizado: 2026-08-16 — gate remoto pendente execução no servidor Prosperfy*
