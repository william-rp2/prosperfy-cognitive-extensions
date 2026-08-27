-- Rollback: 004_supabase_ops_registry
-- Remove tudo criado pela migration 004.
-- PERIGO: destrói o registry de projetos Supabase e o histórico de keepalive.
-- Usar apenas em dev/test.

DROP TABLE IF EXISTS supabase_keepalive_runs CASCADE;
DROP TABLE IF EXISTS supabase_projects CASCADE;
