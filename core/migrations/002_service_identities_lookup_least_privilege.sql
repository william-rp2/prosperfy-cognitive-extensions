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
-- UPDATE. A role `cognitive_admin` NÃO é a identidade do SECURITY
-- DEFINER abaixo (ver SEC-003 mais adiante — isso foi tentado e
-- abandonado); quem escreve via register()/deactivate() é o dono da
-- tabela, via admin_connection().
--
-- SEC-003 (Gate real, DUAS tentativas): a primeira versão desta migration
-- tentava `ALTER FUNCTION ... OWNER TO cognitive_admin`, e depois de uma
-- primeira falha (`InsufficientPrivilegeError: must be able to SET ROLE
-- "cognitive_admin"`) o hotfix anterior adicionou `GRANT cognitive_admin
-- TO CURRENT_USER` logo antes, assumindo que a membership recém-concedida
-- seria suficiente pro `ALTER ... OWNER TO` seguinte. O Gate testou de
-- novo contra o Supabase Homolog real e falhou com o MESMO erro — ou
-- seja, essa suposição (não testável localmente, DG-001) estava errada, e
-- insistir numa terceira tentativa sobre o mesmo mecanismo não verificado
-- seria repetir o erro anterior de "não presumir comportamento, testar".
--
-- Três estratégias de ownership foram comparadas (SEC_003_OWNERSHIP_ANALYSIS):
--
--   A. Forçar owner = role fixa `cognitive_admin` via GRANT+ALTER (a
--      implementação anterior). REJEITADA: já falhou duas vezes contra o
--      Postgres gerenciado do Supabase; o mecanismo exato pelo qual a
--      membership não habilita `ALTER ... OWNER TO` ali não pode ser
--      confirmado sem Postgres real (proibido localmente) — reinsistir
--      seria adivinhação, não engenharia.
--
--   B. Role dedicada nova (ex.: `cognitive_functions_owner`) criada e
--      assumida via `SET ROLE` antes do `CREATE FUNCTION`. REJEITADA: só
--      desloca o mesmo problema — assumir uma role recém-criada via SET
--      ROLE exige exatamente a mesma garantia de membership que já falhou
--      para `cognitive_admin`; criar uma role NÃO torna automaticamente o
--      criador membro dela (mesma causa raiz), e adiciona uma role nova
--      pra auditar sem remover a incerteza.
--
--   C. (ESCOLHIDA) Não forçar nome de owner algum — deixar a função com o
--      owner padrão do Postgres: quem legitimamente a CRIA (a própria
--      conexão admin usada para migrations — `postgres` no Supabase,
--      `cognitive_admin` no docker-compose.dev.yml local onde
--      POSTGRES_USER=cognitive_admin, ou qualquer identidade futura).
--      Nenhuma transferência de ownership pós-CREATE, logo nenhum
--      privilégio de GRANT/ALTER incerto a depender. A garantia de
--      segurança real nunca exigiu o NOME literal "cognitive_admin" — só
--      exige que cognitive_app/cognitive_worker (as duas roles LOGIN
--      expostas ao processo web) nunca sejam nem consigam se tornar esse
--      owner. Isso vale incondicionalmente aqui: app/worker nunca criam
--      esta função (migrations rodam só pela conexão admin) e nunca têm
--      membership nela concedida em lugar nenhum do schema. Portável entre
--      ambientes, zero passo de privilégio que possa falhar.
--
-- Guarda de identidade (mantida, sem custo de privilégio): aborta a
-- migration inteira se CURRENT_USER for uma role de runtime — não previne
-- escalação de ownership (não há mais transferência), mas ainda impede
-- que esta migration seja aplicada por engano com credenciais de
-- app/worker em vez da conexão admin.
DO $$
BEGIN
  IF CURRENT_USER IN ('cognitive_app', 'cognitive_worker') THEN
    RAISE EXCEPTION
      'migration 002: CURRENT_USER (%) é uma role de runtime (app/worker) — '
      'migrations devem rodar com a conexão admin (COGNITIVE_DB_ADMIN_URL), '
      'nunca com credenciais de app/worker.', CURRENT_USER;
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

-- Owner: sem ALTER — permanece com quem criou (a conexão admin desta
-- migration; ver SEC-003 acima). Nunca cognitive_app/cognitive_worker,
-- que nunca rodam migrations e nunca têm membership nesta identidade.
--
-- PUBLIC nunca executa; só as duas roles que realmente precisam resolver
-- identidade em runtime.
REVOKE ALL ON FUNCTION resolve_service_identity_by_credential_hash(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_service_identity_by_credential_hash(TEXT)
  TO cognitive_app, cognitive_worker;
