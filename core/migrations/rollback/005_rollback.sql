-- Rollback: 005_work_management
-- Remove tudo criado pela migration 005.
-- PERIGO: destrói dados. Usar apenas em dev/test.

DROP TABLE IF EXISTS work_sync_outbox CASCADE;
DROP TABLE IF EXISTS work_trello_bindings CASCADE;
DROP TABLE IF EXISTS work_events CASCADE;
DROP TABLE IF EXISTS work_task_dependencies CASCADE;
DROP TABLE IF EXISTS work_task_ideas CASCADE;
DROP TABLE IF EXISTS work_task_projects CASCADE;
DROP TABLE IF EXISTS work_idea_projects CASCADE;
DROP TABLE IF EXISTS work_tasks CASCADE;
DROP TABLE IF EXISTS work_ideas CASCADE;
DROP TABLE IF EXISTS work_projects CASCADE;
