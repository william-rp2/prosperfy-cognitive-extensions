-- 009_finance_f2b_grants.sql
-- F2B (Finance V2) — seed de capability_grants para as 9 capabilities
-- finance.* novas de F2B:
--   finance.clarification.list      finance.clarification.resolve
--   finance.clarification.deliver
--   finance.correction.apply        finance.rule.upsert
--   finance.onboarding.batch        finance.statement.import
--   finance.statement.reconcile     finance.cycle.read
--
-- NAO altera schema — capability_grants já existe desde
-- 000_foundation_tenancy.sql. NAO altera nem substitui 008 (as 10
-- capabilities de P2 continuam com os grants que 008 semeou). Idempotente
-- via ON CONFLICT sobre uq_capability_grant(tenant_id, profile, capability_id).
--
-- DIFERENÇA DELIBERADA EM RELAÇÃO À 008:
-- 008 semeou nos profiles 'hermes-homolog' E 'infra-read' porque não havia
-- confirmação de qual profile o Hermes usava, e as capabilities daquela
-- leva eram majoritariamente read-only. As capabilities de F2B mutam o
-- ledger financeiro (correções, resolução de clarification, regras de
-- classificação, import de extrato, backfill histórico). Doc
-- 03_WHATSAPP_ACL_AND_CLARIFICATIONS.md §"Authorized finance actors":
-- "Finance access is owner-only". Por isso estas linhas vão APENAS para o
-- papel de finance owner ('finance-owner'), nunca para um profile
-- genérico de leitura de infra. Ampliar depois é uma migration nova e
-- uma decisão explícita; começar amplo e estreitar depois não seria
-- fail-closed.
--
-- policy_override fica NULL: usa default_policy=allow de cada YAML. A
-- autorização de FATO (owner vs terceiro, grupo financeiro vs DM vs
-- qualquer outro chat) é decidida ANTES, de forma determinística e
-- fail-closed, em cognitive/policy/finance_acl.py — o grant apenas define
-- que o papel finance-owner pode, em princípio, alcançar a capability.

INSERT INTO capability_grants (tenant_id, profile, capability_id, policy_override)
SELECT t.id, 'finance-owner', cap.capability_id, NULL
FROM tenants t
CROSS JOIN (VALUES
  ('finance.clarification.list'),
  ('finance.clarification.deliver'),
  ('finance.clarification.resolve'),
  ('finance.correction.apply'),
  ('finance.rule.upsert'),
  ('finance.onboarding.batch'),
  ('finance.statement.import'),
  ('finance.statement.reconcile'),
  ('finance.cycle.read')
) AS cap(capability_id)
WHERE t.slug = 'prosperfy-homolog'
ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING;
