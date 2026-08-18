-- Migration: 002_service_identities_lookup_least_privilege
-- Sprint 0.3 — Prosperfy Cognitive V2 — SEC-001 / SEC-002 remediation
-- Depende de: 001_capability_registry_audit
-- NÃO aplicada em nenhum ambiente até o momento desta revisão (SEC-002) —
-- corrigida em lugar de sofrer um patch em migration nova.
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
-- register()/deactivate() (bootstrap/CLI, fora do processo web) seguem
-- via cognitive_admin, que mantém acesso direto à tabela por ownership.

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
