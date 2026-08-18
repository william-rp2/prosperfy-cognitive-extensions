-- Rollback: 002_service_identities_lookup_least_privilege
-- Restaura a policy tenant_isolation original (FOR ALL, tenant-scoped) em
-- service_identities e remove a função SECURITY DEFINER de touch.
-- PERIGO: reverter isto volta a exigir cognitive_admin (BYPASSRLS) para o
-- lookup de credential_hash — reintroduz SEC-001. Usar apenas em dev/test.

DROP FUNCTION IF EXISTS touch_service_identity_last_used(UUID);

DROP POLICY IF EXISTS service_identities_select ON service_identities;
DROP POLICY IF EXISTS service_identities_insert ON service_identities;
DROP POLICY IF EXISTS service_identities_update ON service_identities;

CREATE POLICY tenant_isolation ON service_identities
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));
