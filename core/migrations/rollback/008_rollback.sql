-- Rollback de 006_finance_capability_grants.sql
-- Remove só as linhas que essa migration insere (escopado por profile +
-- prefixo de capability_id) — nunca um DELETE genérico em capability_grants,
-- que também guarda grants de outras tracks (P0/P1) nesta mesma tabela.

DELETE FROM capability_grants
WHERE profile = 'hermes-homolog'
  AND capability_id LIKE 'finance.%';
