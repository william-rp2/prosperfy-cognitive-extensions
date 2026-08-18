# Migrations — Cognitive Core V2

## Ambientes

| Ambiente | Onde conectar | Configuração |
|---|---|---|
| **Dev/Homolog remoto** | `COGNITIVE_DB_ADMIN_URL` do ambiente DEV | Padrão de desenvolvimento integrado |
| **CI (testcontainers)** | Postgres efêmero criado pelo pytest | Nenhuma infra local necessária |
| **Docker local** | `docker/docker-compose.dev.yml` | **Opcional** — conveniência, não obrigatório |
| **Produção** | Banco dedicado e separado | Nunca usar estas migrations sem aprovação explícita |

## Contrato de atomicidade (Sprint 0.3 hotfix)

Cada migration é aplicada como **uma única transação explícita**
(`async with conn.transaction()`), cobrindo o SQL do arquivo inteiro **e**
o INSERT da linha de tracking em `_migrations` juntos. Se qualquer
statement falhar — inclusive um erro de privilégio no meio do arquivo — a
transação inteira reverte: nenhum objeto do arquivo persiste, e a linha de
tracking nunca chega a existir. A migration seguinte roda tentativa
fica marcada `PENDING`, segura pra tentar de novo depois de corrigida.

Isso substitui o comportamento anterior (duas chamadas `execute()`
separadas — SQL do arquivo, depois o INSERT de tracking — sem transação
única cobrindo as duas), que deixava uma janela real entre "migration
aplicada" e "migration rastreada".

Antes de reaplicar uma migration que falhou no meio, rode:

```bash
COGNITIVE_DB_ADMIN_URL=<url> python core/migrations/runner.py --inspect 002
```

Isso confere um pequeno conjunto de sinais de estado real do banco (existe
a função? tem grant residual? policy antiga ainda lá?) e reporta
`CLEAN` / `PARTIAL` / `APPLIED` — não decide sozinho, dá evidência pro
operador/Gate decidir se é seguro rodar `--up` de novo.

## Regras de Aplicação

1. **NUNCA** aplicar no Supabase prod sem aprovação humana explícita
2. Conectar sempre como a role admin (`COGNITIVE_DB_ADMIN_URL`) para migrations
3. Migration runner é idempotente **entre migrations** — uma já aplicada é
   pulada (`SKIP`) com checksum conferido; **dentro** de uma migration que
   ainda não rodou, a atomicidade vem da transação (ver acima), não de
   `IF NOT EXISTS`/`ON CONFLICT` — esses ajudam quando o SQL em si precisa
   ser reentrante, não substituem a garantia de rollback
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

# Conferir checksums de tudo que já foi aplicado
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --verify

# Antes de reaplicar uma migration que falhou no meio: diagnosticar estado residual
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --inspect 002
```

## Ordem de Migrations

| Arquivo | O que cria |
|---|---|
| `000_foundation_tenancy.sql` | roles, tenants, members, resources, credential_refs, grants + RLS |
| `001_capability_registry_audit.sql` | service_identities, audit_events, execution_traces, cost_telemetry + RLS |
| `002_service_identities_lookup_least_privilege.sql` | SEC-001/SEC-002 (Sprint 0.3): remove `cognitive_app`/`cognitive_worker` de qualquer grant direto (SELECT/INSERT/UPDATE/DELETE) em `service_identities` — o único acesso é via `resolve_service_identity_by_credential_hash(hash)`, função `SECURITY DEFINER` (owner `cognitive_admin`, `search_path` hardened, `PUBLIC` sem `EXECUTE`) que recebe só o hash, nunca retorna `credential_hash`, e atualiza `last_used_at` atomicamente na mesma operação. Também concede `cognitive_admin` a `CURRENT_USER` (quem roda a migration) — necessário pra `ALTER FUNCTION ... OWNER TO` funcionar, já que criar uma role não torna o criador membro dela |
| `003_identity_lifecycle_audit.sql` | Sprint 0.4: cria `identity_events` (append-only) — trilha de auditoria de provisionamento/revogação de `service_identities`, gravada por `ServiceIdentityRepository.register()`/`.deactivate()`/`.rotate()` na mesma transação `admin_connection()` da escrita em `service_identities`. RLS: leitura tenant-scoped para `cognitive_app`/`cognitive_worker` (mesmo shape de `audit_events` em 001); nenhum `GRANT INSERT/UPDATE/DELETE` pra essas duas roles — escrita é exclusiva da conexão admin (bootstrap/CLI), nunca de rota HTTP |

## Estratégia RLS (Sprint 0.2)

- Três roles: `cognitive_admin` (BYPASSRLS), `cognitive_app` (RLS enforced), `cognitive_worker` (RLS enforced)
- Mecanismo: `SET LOCAL app.current_tenant_id = '<tenant_id>'` + `current_setting('app.current_tenant_id', true)` nas policies
- Válido para Postgres dedicado (local e remoto)
- Decisão definitiva para ambiente Supabase compartilhado: pendente (DG-001 aberto)

## Rollbacks

```
rollback/
├── 000_rollback.sql   ← DROP de tudo da migration 000
├── 001_rollback.sql   ← DROP de tudo da migration 001
├── 002_rollback.sql   ← restaura policy tenant-scoped original (PERIGO: reintroduz SEC-001, dev/test only)
└── 003_rollback.sql   ← DROP TABLE identity_events (PERIGO: destrói histórico de auditoria, dev/test only)
```
