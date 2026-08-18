-- Migration: 002_service_identities_lookup_least_privilege
-- Sprint 0.3 — Prosperfy Cognitive V2 — SEC-001 / SEC-002 / ownership remediation
-- Depende de: 001_capability_registry_audit
-- Nunca teve um COMMIT bem-sucedido em nenhum ambiente até esta revisão:
-- a tentativa de aplicação real em Homolog falhou em ALTER FUNCTION ...
-- OWNER TO (ver seção de ownership abaixo), então `_migrations` continua
-- sem a linha '002' — corrigida em lugar de sofrer um patch em migration
-- nova (000/001 nunca alterados).
--
-- SEC-001: o lookup de credential_hash -> tenant_id/actor_id precisa
-- acontecer ANTES de existir contexto de tenant (SET LOCAL
-- app.current_tenant_id). Usar cognitive_admin (BYPASSRLS) pra isso força
-- o pool admin a ficar vivo durante toda a vida do processo web público.
--
-- SEC-002 (achado do Gate, corrigindo a primeira versão desta mesma
-- migration): a primeira tentativa de correção liberou
-- `USING (true)` para SELECT em service_identities para
-- cognitive_app/cognitive_worker, assumindo que "a query da aplicação
-- sempre filtra por credential_hash exato" era suficiente boundary de
-- segurança. Não é — RLS permissiva + GRANT SELECT da migration 001
-- juntos permitem `SELECT * FROM service_identities` completo (todos os
-- tenants, actor_ids, credential_hash, profiles) para qualquer código
-- rodando com essas roles, não só o caminho de lookup pretendido. O
-- filtro por credential_hash só existe no application code — isso não é
-- boundary de banco.
--
-- Correção real: cognitive_app/cognitive_worker perdem QUALQUER
-- privilégio direto (SELECT/INSERT/UPDATE) sobre service_identities.
-- O único acesso possível é via uma função SECURITY DEFINER estreita,
-- que recebe exclusivamente o credential_hash, faz o match exato
-- internamente, atualiza last_used_at atomicamente na mesma operação
-- (elimina a necessidade de uma segunda função "touch" que aceitava
-- um id arbitrário), e retorna só os 4 campos necessários pra montar
-- o ActorContext — nunca o credential_hash, nunca outras linhas.
-- register()/deactivate() (bootstrap/CLI, fora do processo web) seguem via
-- admin_connection() — a CONEXÃO admin (quem roda migrations; `postgres`
-- no Supabase, dono real das tabelas por ter rodado o CREATE TABLE),
-- não a ROLE SQL `cognitive_admin` em si. `cognitive_admin` só tem GRANT
-- SELECT explícito em service_identities (migration 001) — sem INSERT/
-- UPDATE. Não confundir os dois: a role é usada pro SECURITY DEFINER
-- abaixo; quem escreve via register()/deactivate() é o dono da tabela.
--
-- Gate hotfix (retry pós-falha real em Homolog): `ALTER FUNCTION ... OWNER
-- TO cognitive_admin` falhou com
-- `InsufficientPrivilegeError: must be able to SET ROLE "cognitive_admin"`.
-- Causa raiz: migration 000 cria `cognitive_admin` com `CREATE ROLE
-- cognitive_admin BYPASSRLS` (sem LOGIN — não é uma role conectável
-- diretamente) mas nunca concede a role a quem quer que conecte como
-- admin pra rodar migrations (`postgres`, no Supabase — ver DG-001).
-- Criar uma role não torna automaticamente o criador membro dela; sem
-- essa membership, ninguém além de superuser consegue `SET ROLE`/transferir
-- ownership pra `cognitive_admin`. 000/001 não podem ser alterados, então
-- a correção entra aqui: concede `cognitive_admin` a `CURRENT_USER` (quem
-- quer que esteja rodando ESTA migration — sempre a conexão admin, por
-- definição; não depende de o nome literal ser "postgres", funciona em
-- qualquer ambiente). Isso NÃO é uma escalação: a conexão admin já é a
-- mais privilegiada do sistema (é quem cria/concede tudo via DDL); ganhar
-- membership numa role que ela mesma criou não aumenta seu poder real.
-- Idempotente — regrant de uma membership já concedida é um no-op no
-- Postgres, não falha se rodado de novo.
--
-- Defesa em profundidade (revisão adversarial): nada aqui valida que
-- CURRENT_USER é de fato a conexão admin — só o operador que aponta
-- COGNITIVE_DB_ADMIN_URL corretamente garante isso hoje. Se por engano de
-- configuração COGNITIVE_DB_ADMIN_URL um dia apontasse pra
-- cognitive_app/cognitive_worker (roles LOGIN, expostas ao processo web),
-- este GRANT daria BYPASSRLS a uma delas — bypass total de RLS
-- multi-tenant. Guarda barata: aborta a migration inteira (a transação
-- do runner reverte tudo) se CURRENT_USER for uma dessas duas roles.
-- Também evita um self-grant redundante (`GRANT cognitive_admin TO
-- cognitive_admin`) no cenário de dev local via docker-compose.dev.yml,
-- onde POSTGRES_USER=cognitive_admin faz o próprio Postgres bootstrapar
-- essa role como superuser via initdb — nesse caso migration 000 nunca
-- chega a criar uma role nova (IF NOT EXISTS já a encontra), e
-- CURRENT_USER já É cognitive_admin. `pg_has_role(x, x, 'MEMBER')` é
-- sempre true (toda role é membro de si mesma), então o `IF NOT` abaixo
-- pula o GRANT nesse caso sem depender de saber se o Postgres aceita ou
-- rejeita um self-grant explícito.
DO $$
BEGIN
  IF CURRENT_USER IN ('cognitive_app', 'cognitive_worker') THEN
    RAISE EXCEPTION
      'migration 002: CURRENT_USER (%) é uma role de runtime (app/worker) — '
      'migrations devem rodar com a conexão admin (COGNITIVE_DB_ADMIN_URL), '
      'nunca com credenciais de app/worker. Abortando antes de conceder '
      'cognitive_admin a essa conexão.', CURRENT_USER;
  END IF;

  IF NOT pg_has_role(CURRENT_USER, 'cognitive_admin', 'MEMBER') THEN
    -- CURRENT_USER aqui é o keyword de role-spec do GRANT, não uma
    -- variável interpolada — não precisa (nem deve) de EXECUTE/SQL
    -- dinâmico pra isso.
    GRANT cognitive_admin TO CURRENT_USER;
  END IF;
END $$;

-- ─── service_identities: nenhum acesso direto para app/worker ──────────
DROP POLICY IF EXISTS tenant_isolation ON service_identities;

-- REVOKE explícito do que a migration 001 concedeu — não confiar só em
-- RLS. Com RLS enabled e nenhuma policy para estas roles, um SELECT
-- tentado sem o GRANT já falha com permission denied antes mesmo de RLS
-- ser avaliada; o REVOKE é a camada primária e intencional aqui.
REVOKE SELECT, INSERT, UPDATE, DELETE ON service_identities FROM cognitive_app, cognitive_worker;

-- cognitive_admin mantém o SELECT concedido em 001 (uso administrativo/
-- inspeção; register()/deactivate() usam a conexão admin para
-- INSERT/UPDATE, cobertos por ownership/BYPASSRLS, não por GRANT
-- explícito adicional aqui).

-- ─── Lookup seguro: função SECURITY DEFINER estreita, hash-in only ──────
-- Contrato:
--   entrada:  credential_hash (sha256 hex do Bearer token)
--   saída:    no máximo 1 linha — service_identity_id, tenant_id,
--             actor_id, profile (nunca credential_hash, nunca outras
--             identidades)
--   efeito:   atualiza last_used_at atomicamente APENAS na linha cujo
--             credential_hash bateu — impossível direcionar a um id
--             arbitrário, porque não há parâmetro de id, só de hash.
--   garantia: UNIQUE(credential_hash) em 001 já garante 0 ou 1 linha.
CREATE OR REPLACE FUNCTION resolve_service_identity_by_credential_hash(p_credential_hash TEXT)
RETURNS TABLE (
  service_identity_id UUID,
  tenant_id UUID,
  actor_id TEXT,
  profile TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  UPDATE service_identities
  SET last_used_at = NOW()
  WHERE credential_hash = p_credential_hash AND active = true
  RETURNING id, service_identities.tenant_id, service_identities.actor_id, service_identities.profile;
$$;

-- Owner explícito e controlado — nunca depender de quem rodou a migration
-- (poderia ser o service_role/postgres do runner, não cognitive_admin).
ALTER FUNCTION resolve_service_identity_by_credential_hash(TEXT) OWNER TO cognitive_admin;

-- PUBLIC nunca executa; só as duas roles que realmente precisam resolver
-- identidade em runtime.
REVOKE ALL ON FUNCTION resolve_service_identity_by_credential_hash(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_service_identity_by_credential_hash(TEXT)
  TO cognitive_app, cognitive_worker;
