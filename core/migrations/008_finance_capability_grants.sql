-- 008_finance_capability_grants.sql
-- P2 (Financeiro pelo WhatsApp) — seed de capability_grants para as 10
-- capabilities finance.* (core/cognitive/cognitive/registry/capabilities/
-- finance.*.yaml). NAO altera schema — capability_grants já existe desde
-- 000_foundation_tenancy.sql. Idempotente via ON CONFLICT sobre a unique
-- key uq_capability_grant(tenant_id, profile, capability_id).
--
-- Verificado ao vivo no Homolog antes de escrever este arquivo (SELECT
-- read-only via Composio/Supabase, account "Supabase - Hermes",
-- ref esvjfkknrzzziafovwrv):
--   * tenants.slug real = 'prosperfy-homolog' (não 'prosperfy' — esse era
--     só o COGNITIVE_DEV_TENANT_ID do modo in-memory local).
--   * capability_grants já tem linhas de P0/P1 em DOIS profiles:
--     'hermes-homolog' (subset: infra.action, supabase.*) e 'infra-read'
--     (superset: infra.*, supabase.*, work.* completo). Sem confirmação de
--     qual profile o Hermes real usa neste ambiente, semeia nos dois —
--     zero downside (mesmo domínio finance.* nos dois) e elimina o risco
--     de escolher o profile errado.
--
-- policy_override fica NULL em todas as linhas — usa o default_policy=allow
-- de cada YAML (doc 00 §8: lançamento manual, reclassificação de transação
-- identificada e escrita de orçamento são ALLOW direto; nada aqui precisa
-- de override para CONFIRM/DENY).

INSERT INTO capability_grants (tenant_id, profile, capability_id, policy_override)
SELECT t.id, grant_profile.profile, cap.capability_id, NULL
FROM tenants t
CROSS JOIN (VALUES ('hermes-homolog'), ('infra-read')) AS grant_profile(profile)
CROSS JOIN (VALUES
  ('finance.summary.read'),
  ('finance.transactions.read'),
  ('finance.accounts.read'),
  ('finance.bills.read'),
  ('finance.manual.create'),
  ('finance.category.update'),
  ('finance.budget.read'),
  ('finance.budget.write'),
  ('finance.sync.run'),
  ('finance.sync.status')
) AS cap(capability_id)
WHERE t.slug = 'prosperfy-homolog'
ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING;
