-- 010_finance_f2b_hermes_service_grants.sql
-- F2B — grants das 9 capabilities finance.* (F2B) para o service profile
-- REAL do Hermes homolog: 'infra-read'.
--
-- ROOT CAUSE (live WhatsApp):
--   FinanceAcl ALLOW (owner + canal autorizado)
--   + service identity hermes-homolog / profile infra-read
--   + finance.clarification.list
--   → DENY [no_grant]
--
-- Arquitetura preservada (dois planos independentes):
--   1) Service grant: o profile do service identity pode ALCANÇAR finance.*
--   2) FinanceAcl: só owner + canal autorizado pode EXECUTAR
--
-- NÃO rebindar Hermes para finance-owner.
-- NÃO resolver grant pelo canonical owner.
-- NÃO enfraquecer FinanceAcl.
-- NÃO editar 009_finance_f2b_grants.sql (já aplicada; finance-owner
--   permanece intacto).
-- NÃO alterar as 10 capabilities P2 da 008.
--
-- SOBRE O NOME 'infra-read':
--   É o profile REAL do service identity Hermes neste homolog, apesar do
--   nome legado. NÃO significa "apenas infraestrutura" neste contexto —
--   é o rótulo histórico do profile de serviço que o Hermes autentica.
--
--   SERVICE_PROFILE_RENAMING=BACKLOG
--   Futuro possível: profile dedicado (ex.: hermes-runtime). NÃO fazer
--   essa refatoração nesta migration.
--
-- Idempotente: ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING.
-- Tenant-scoped: slug = 'prosperfy-homolog'.
-- Sem alteração de schema. Sem secrets.

INSERT INTO capability_grants (tenant_id, profile, capability_id, policy_override)
SELECT t.id, 'infra-read', cap.capability_id, NULL
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
