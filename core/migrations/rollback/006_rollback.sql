-- Rollback: 006_browser_harness_capability_grants
-- Remove somente os grants semeados por esta migration (profile
-- 'owner-core' + capability_id 'browser.read'). Não remove tenants nem
-- outros grants -- PERIGO limitado ao escopo desta track.

DELETE FROM capability_grants
WHERE capability_id = 'browser.read'
  AND profile = 'owner-core';
