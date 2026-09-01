-- Rollback de 010_finance_f2b_hermes_service_grants.sql
-- Remove APENAS as 9 capabilities F2B semeadas para o profile 'infra-read'.
-- NÃO toca finance-owner (009). NÃO toca as 10 P2 da 008 em infra-read.

DELETE FROM capability_grants
WHERE profile = 'infra-read'
  AND capability_id IN (
    'finance.clarification.list',
    'finance.clarification.deliver',
    'finance.clarification.resolve',
    'finance.correction.apply',
    'finance.rule.upsert',
    'finance.onboarding.batch',
    'finance.statement.import',
    'finance.statement.reconcile',
    'finance.cycle.read'
  );
