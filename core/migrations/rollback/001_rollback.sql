-- Rollback: 001_capability_registry_audit
-- Remove tudo criado pela migration 001.
-- PERIGO: destrói dados. Usar apenas em dev/test.

DROP TABLE IF EXISTS cost_telemetry CASCADE;
DROP TABLE IF EXISTS execution_traces CASCADE;
DROP TABLE IF EXISTS audit_events CASCADE;
DROP TABLE IF EXISTS service_identities CASCADE;
