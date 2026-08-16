-- Rollback: 000_foundation_tenancy
-- Remove tudo criado pela migration 000.
-- PERIGO: destrói dados. Usar apenas em dev/test.

DROP TABLE IF EXISTS capability_grants CASCADE;
DROP TABLE IF EXISTS tenant_integrations CASCADE;
DROP TABLE IF EXISTS credential_refs CASCADE;
DROP TABLE IF EXISTS tenant_resources CASCADE;
DROP TABLE IF EXISTS tenant_members CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;

-- Roles: não remover automaticamente — pode conflitar com outras DBs
-- Se necessário: DROP ROLE cognitive_app; DROP ROLE cognitive_worker;
-- cognitive_admin: nunca dropar automaticamente
