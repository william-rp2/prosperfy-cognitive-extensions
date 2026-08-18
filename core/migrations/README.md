# Migrations — Cognitive Core V2

## Ambientes

| Ambiente | Onde conectar | Configuração |
|---|---|---|
| **Dev/Homolog remoto** | `COGNITIVE_DB_ADMIN_URL` do ambiente DEV | Padrão de desenvolvimento integrado |
| **CI (testcontainers)** | Postgres efêmero criado pelo pytest | Nenhuma infra local necessária |
| **Docker local** | `docker/docker-compose.dev.yml` | **Opcional** — conveniência, não obrigatório |
| **Produção** | Banco dedicado e separado | Nunca usar estas migrations sem aprovação explícita |

## Regras de Aplicação

1. **NUNCA** aplicar no Supabase prod sem aprovação humana explícita
2. Conectar sempre como `cognitive_admin` (tem `BYPASSRLS`) para migrations
3. Migration runner é idempotente — seguro reaplicar (`IF NOT EXISTS`, `ON CONFLICT`)
4. Rollback deve ser testado antes de qualquer merge em staging

## Uso

```bash
# Status atual
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --status

# Aplicar todas as pending
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --up

# Rollback completo (dev/test only)
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --down 0

# Reaplicar do zero (dev/test only)
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --down 0
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --up
```

## Ordem de Migrations

| Arquivo | O que cria |
|---|---|
| `000_foundation_tenancy.sql` | roles, tenants, members, resources, credential_refs, grants + RLS |
| `001_capability_registry_audit.sql` | service_identities, audit_events, execution_traces, cost_telemetry + RLS |
| `002_service_identities_lookup_least_privilege.sql` | SEC-001 (Sprint 0.3): troca RLS de `service_identities` para SELECT irrestrito (credential_hash é o boundary) + INSERT/UPDATE tenant-scoped + função SECURITY DEFINER `touch_service_identity_last_used` — remove a necessidade de `cognitive_admin`/BYPASSRLS para lookup de identidade em runtime |

## Estratégia RLS (Sprint 0.2)

- Três roles: `cognitive_admin` (BYPASSRLS), `cognitive_app` (RLS enforced), `cognitive_worker` (RLS enforced)
- Mecanismo: `SET LOCAL app.current_tenant_id = '<tenant_id>'` + `current_setting('app.current_tenant_id', true)` nas policies
- Válido para Postgres dedicado (local e remoto)
- Decisão definitiva para ambiente Supabase compartilhado: pendente (DG-001 aberto)

## Rollbacks

```
rollback/
├── 000_rollback.sql   ← DROP de tudo da migration 000
└── 001_rollback.sql   ← DROP de tudo da migration 001
```
