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
# (aceita prefixo curto ou stem completo do arquivo — as duas formas resolvem
# pro mesmo veredito)
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --inspect 002
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --inspect 002_service_identities_lookup_least_privilege

# Raio-x READ-ONLY do banco inteiro (000/001/002 + _migrations) — usar quando
# _migrations não é confiável (ex: dropada por engano, incidente real do
# Gate — ver seção "Recovery" abaixo)
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --diagnose

# Reconstruir só a linha de tracking em _migrations — ÚNICO comando que
# escreve, e só age se --diagnose provar TRACKING_MISSING_ONLY
COGNITIVE_DB_ADMIN_URL=<url-do-dev-homolog> python core/migrations/runner.py --recover-tracking
```

## Recovery: quando `_migrations` não é confiável

Incidente real (Sprint 0.3, VPS/Homolog Gate): um run real contra
Supabase Homolog aplicou 000/001/002 com sucesso, mas um teste destrutivo
rodado depois derrubou a tabela `_migrations`. Sem `_migrations`, o runner
não consegue mais dizer "o que já está aplicado" — e reaplicar às cegas
(`--up`) arrisca rodar SQL não-idempotente contra um schema que já existe.

`--diagnose` e `--recover-tracking` existem exatamente pra esse cenário:

1. **`--diagnose` (read-only)** roda um fingerprint de estado real —
   existência de tabelas, roles, RLS habilitada — pra 000, 001 e 002
   (mesmo estilo do fingerprint que `--inspect 002` já usa), **sem
   depender de `_migrations` em nenhum momento**. Nenhum
   `CREATE`/`ALTER`/`DROP`/`INSERT`/`UPDATE`/`DELETE` roda aqui — só
   `SELECT` contra o catálogo do Postgres (`pg_class`, `pg_roles`,
   `pg_policies`, `to_regclass`, `has_table_privilege`, etc.). Termina
   imprimindo um `VERDICT`:
   - `HEALTHY` — schema intacto e `_migrations` bate certinho.
   - `TRACKING_MISSING_ONLY` — schema 100% intacto (000/001/002
     comprovadamente aplicadas), só falta a linha de tracking. **Único**
     veredito que `--recover-tracking` aceita agir sobre.
   - `MIGRATION_002_MISSING` — 000/001 completas, 002 nunca rodou
     (fingerprint bate exatamente com o estado limpo pré-002). Normal,
     seguro, não é corrupção.
   - `SCHEMA_PARTIAL` / `UNKNOWN_UNSAFE_STATE` — estado ambíguo ou
     inesperado. Exige revisão humana antes de qualquer ação; exit code 1.

2. **`--recover-tracking` (o único write path)** roda `--diagnose`
   internamente primeiro. Se o veredito não for **exatamente**
   `TRACKING_MISSING_ONLY` — "perto o suficiente" não conta — recusa com
   `RECOVERY REFUSED` e exit 1, sem tentar nenhum write. Só quando o
   schema/roles/RLS/policies/função já foram **provados intactos pelo
   fingerprint ANTES de qualquer escrita** é que ele:
   - `CREATE TABLE IF NOT EXISTS _migrations` (idempotente, mesma DDL de
     `ensure_migrations_table()`);
   - `INSERT ... ON CONFLICT (version) DO NOTHING` pras três migrations,
     com o checksum sempre **recalculado na hora** a partir do arquivo
     `.sql` real em disco — nunca aceito como input do operador (evita
     poluir `--verify`/`--up` com um checksum digitado errado);
   - tudo dentro de **uma única transação explícita** (`async with
     conn.transaction()`), mesmo contrato de atomicidade do resto deste
     runner.

   Nunca toca tabela, role, policy ou função de negócio — só
   `_migrations`. Também guarda contra rodar fora de Homolog: recusa
   qualquer `COGNITIVE_DB_ADMIN_URL` cujo project ref não verifique como
   `esvjfkknrzzziafovwrv` (reaproveita `verify_homolog_admin_dsn` de
   `cognitive.config.db_target` — o mesmo helper usado por
   `tests/db/conftest.py`).

   Idempotente: rodar duas vezes seguidas é seguro — a segunda vez já vê
   `HEALTHY` e recusa educadamente ("nada a fazer", exit 0), não como
   erro.

Nunca alcançável a partir de `--up`/`--down`/fluxo normal de migration —
é uma ação de operador deliberada e isolada.

## Ordem de Migrations

| Arquivo | O que cria |
|---|---|
| `000_foundation_tenancy.sql` | roles, tenants, members, resources, credential_refs, grants + RLS |
| `001_capability_registry_audit.sql` | service_identities, audit_events, execution_traces, cost_telemetry + RLS |
| `002_service_identities_lookup_least_privilege.sql` | SEC-001/SEC-002/SEC-003 (Sprint 0.3): remove `cognitive_app`/`cognitive_worker` de qualquer grant direto (SELECT/INSERT/UPDATE/DELETE) em `service_identities` — o único acesso é via `resolve_service_identity_by_credential_hash(hash)`, função `SECURITY DEFINER` (`search_path` hardened, `PUBLIC` sem `EXECUTE`) que recebe só o hash, nunca retorna `credential_hash`, e atualiza `last_used_at` atomicamente na mesma operação. Owner: sem `ALTER ... OWNER TO` — permanece com quem criou (a conexão admin), nunca um nome de role fixo (ver seção de ownership abaixo) |

## Modelo de ownership da função de lookup (SEC-003, Sprint 0.3)

`resolve_service_identity_by_credential_hash` (migration 002) **não** usa
`ALTER FUNCTION ... OWNER TO <role fixa>`. Duas tentativas reais contra o
Supabase Homolog provaram que essa transferência de ownership
(`cognitive_admin`, com ou sem self-grant de membership via `GRANT
cognitive_admin TO CURRENT_USER`) falha ali com
`InsufficientPrivilegeError: must be able to SET ROLE`, por um mecanismo
que não é possível confirmar sem Postgres real (DG-001 proíbe
Docker/Postgres local).

A função permanece com o owner padrão do Postgres: quem legitimamente a
cria — a conexão admin usada para rodar a migration (`postgres` no
Supabase, `cognitive_admin` no `docker-compose.dev.yml` local). Nenhum
passo de privilégio incerto depois do `CREATE FUNCTION`. A garantia de
segurança é expressa em relação a quem **nunca** pode ser nem se tornar
esse owner (`cognitive_app`/`cognitive_worker`), não em relação a um nome
de role específico. Tanto a suíte de testes DB (`pg_has_role`, checa
membership de verdade) quanto o fingerprint do `runner.py --inspect 002`
(mesma checagem via `pg_has_role`, não só comparação de nome) validam essa
propriedade. Ver comentário completo (comparação de 3 estratégias) no
topo de `002_service_identities_lookup_least_privilege.sql`.

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
└── 002_rollback.sql   ← restaura policy tenant-scoped original (PERIGO: reintroduz SEC-001, dev/test only)
```
