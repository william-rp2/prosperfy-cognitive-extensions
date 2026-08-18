-- Rollback: 002_service_identities_lookup_least_privilege
-- Restaura a policy tenant_isolation original (FOR ALL, tenant-scoped) e os
-- grants diretos de 001 em service_identities; remove a função de lookup.
-- PERIGO: reverter isto volta a exigir cognitive_admin (BYPASSRLS) para o
-- lookup de credential_hash — reintroduz SEC-001. Usar apenas em dev/test.

DROP FUNCTION IF EXISTS resolve_service_identity_by_credential_hash(TEXT);

GRANT SELECT, INSERT, UPDATE ON service_identities TO cognitive_app, cognitive_worker;

CREATE POLICY tenant_isolation ON service_identities
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));
