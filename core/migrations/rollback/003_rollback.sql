-- Rollback: 003_identity_lifecycle_audit
-- Remove tudo criado pela migration 003.
-- PERIGO: destrói dados (histórico de provisionamento/revogação de
-- credentials). Usar apenas em dev/test.

DROP TABLE IF EXISTS identity_events CASCADE;
