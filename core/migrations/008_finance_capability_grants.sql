-- 008_finance_capability_grants.sql
-- P2 (Financeiro pelo WhatsApp) — seed de capability_grants para as 10
-- capabilities finance.* (core/cognitive/cognitive/registry/capabilities/
-- finance.*.yaml). NAO altera schema — capability_grants já existe desde
-- 000_foundation_tenancy.sql. Idempotente via ON CONFLICT sobre a unique
-- key uq_capability_grant(tenant_id, profile, capability_id).
--
-- profile='hermes-homolog': mesmo profile usado pelo Hermes real ao chamar
-- o Cognitive gateway em nome do usuário (ver tests/unit/
-- test_infra_action_enforcement.py, que usa o mesmo profile para
-- infra.action). policy_override fica NULL em todas — usa o
-- default_policy=allow de cada YAML (doc 00 §8: lançamento manual,
-- reclassificação de transação identificada e escrita de orçamento são
-- ALLOW direto; nada aqui precisa de override para CONFIRM/DENY).
--
-- Pré-requisito: já existir uma linha em `tenants` com slug='prosperfy'
-- (mesmo dev_tenant usado pelas outras tracks — ver COGNITIVE_DEV_TENANT_ID
-- em gateway/app.py). Se essa linha não existir ainda no Homolog, o SELECT
-- não retorna nenhuma linha e o INSERT vira no-op silencioso — rode
-- `SELECT slug FROM tenants;` antes para confirmar o slug certo, e ajuste
-- o WHERE abaixo se necessário.

INSERT INTO capability_grants (tenant_id, profile, capability_id, policy_override)
SELECT t.id, 'hermes-homolog', cap.capability_id, NULL
FROM tenants t
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
WHERE t.slug = 'prosperfy'
ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING;
