-- rollback 007: volta o CHECK de status ao conjunto original.
-- Requer que nenhuma linha esteja em 'disabled_by_owner' — normaliza para
-- 'paused' antes, senão o ADD CONSTRAINT falha.

UPDATE supabase_projects SET status = 'paused' WHERE status = 'disabled_by_owner';

ALTER TABLE supabase_projects
  DROP CONSTRAINT IF EXISTS supabase_projects_status_check;

ALTER TABLE supabase_projects
  ADD CONSTRAINT supabase_projects_status_check
  CHECK (status IN ('healthy','warning','failed','paused','unknown'));
