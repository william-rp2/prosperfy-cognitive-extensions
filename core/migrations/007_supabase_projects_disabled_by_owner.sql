-- 007_supabase_projects_disabled_by_owner
--
-- Estende o CHECK de supabase_projects.status com 'disabled_by_owner'.
--
-- Motivo: existe diferença operacional real entre "pausado por inatividade,
-- deve ser reativado" e "desativado de propósito pelo owner, não volta".
-- Sem esse estado os dois viravam 'paused' e os desativados apareceriam para
-- sempre em MANUAL_ACTIVATION_REQUIRED, gerando ação humana inútil a cada
-- rodada.
--
-- 'disabled_by_owner' NUNCA recebe keepalive e NUNCA entra na lista de
-- ativação manual.

ALTER TABLE supabase_projects
  DROP CONSTRAINT IF EXISTS supabase_projects_status_check;

ALTER TABLE supabase_projects
  ADD CONSTRAINT supabase_projects_status_check
  CHECK (status IN (
    'healthy',
    'warning',
    'failed',
    'paused',
    'unknown',
    'disabled_by_owner'
  ));
