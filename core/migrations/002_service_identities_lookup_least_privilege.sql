-- Migration: 002_service_identities_lookup_least_privilege
-- Sprint 0.3 — Prosperfy Cognitive V2 — SEC-001 remediation
-- Depende de: 001_capability_registry_audit
--
-- Problema (SEC-001): o lookup de credential_hash -> tenant_id/actor_id
-- precisa acontecer ANTES de existir contexto de tenant (SET LOCAL
-- app.current_tenant_id). A policy tenant_isolation original em
-- service_identities exigia esse contexto, então o Gateway usava
-- cognitive_admin (BYPASSRLS) para o lookup — o que forçava o pool admin
-- a ficar vivo durante toda a vida do processo web público.
--
-- Correção: service_identities é estruturalmente uma tabela de
-- login/auth (mesmo padrão de auth.users do Supabase) — a autorização
-- real vem do credential_hash exato (só quem tem o Bearer token original
-- calcula o hash igual), não do tenant_id. A query de aplicação SEMPRE
-- filtra por credential_hash exato (nunca faz scan livre), então o hash
-- É o boundary de segurança para leitura — RLS tenant-scoped no SELECT
-- não agrega isolamento real e apenas força o uso de BYPASSRLS.
--
-- INSERT/UPDATE continuam tenant-scoped: uma conexão de um tenant não
-- pode criar/alterar identidades de outro tenant.

-- ─── service_identities: SELECT sem filtro de tenant, INSERT/UPDATE tenant-scoped ──
DROP POLICY IF EXISTS tenant_isolation ON service_identities;

CREATE POLICY service_identities_select ON service_identities
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (true);

CREATE POLICY service_identities_insert ON service_identities
  FOR INSERT
  TO cognitive_app, cognitive_worker
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

CREATE POLICY service_identities_update ON service_identities
  FOR UPDATE
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Grants de 001 (SELECT, INSERT, UPDATE para cognitive_app/cognitive_worker;
-- SELECT para cognitive_admin) permanecem válidos e não precisam mudar —
-- RLS policies e GRANTs são camadas independentes, ambas continuam
-- aplicadas.

-- ─── last_used_at touch: SECURITY DEFINER, single-column, id-scoped ────────
-- O lookup ainda precisa gravar last_used_at ANTES do tenant context
-- existir (mesmo ciclo do SELECT). Em vez de reabrir o ciclo via admin
-- pool ou afrouxar a policy de UPDATE para USING(true), expomos uma
-- função SECURITY DEFINER estreita: atualiza apenas last_used_at, apenas
-- por id, nada mais. A função roda com os privilégios de quem a criou
-- (cognitive_admin, via migration runner — BYPASSRLS), então funciona
-- sem tenant context; cognitive_app/cognitive_worker só recebem EXECUTE,
-- nunca UPDATE irrestrito na tabela.
CREATE OR REPLACE FUNCTION touch_service_identity_last_used(p_id UUID)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE service_identities SET last_used_at = NOW() WHERE id = p_id;
$$;

REVOKE ALL ON FUNCTION touch_service_identity_last_used(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION touch_service_identity_last_used(UUID)
  TO cognitive_app, cognitive_worker;
