-- Seed operacional (NAO e migration — mesmo padrao das grants ja existentes
-- de infra.inspect/infra.action, que tambem nao vieram de nenhum arquivo em
-- core/migrations/). Idempotente (INSERT ... WHERE NOT EXISTS).
--
-- HUMAN_BLOCKER da track P0: esta escrita foi bloqueada pelo classifier de
-- auto mode por tocar capability_grants (tabela de autorizacao/controle de
-- acesso) — tratado como "modificar configuracao de seguranca", fora do
-- que o agente pode executar sem confirmacao explicita do operador. Rodar
-- manualmente contra o Cognitive Homolog (ref esvjfkknrzzziafovwrv, conta
-- Composio "Supabase - Hermes") via SUPABASE_BETA_RUN_SQL_QUERY ou
-- equivalente, com read_only=false.
--
-- Sem isso, TODA chamada as 5 capabilities supabase.* recebe
-- DENY [no_grant] do PolicyEngine (ver policy/engine.py: "Sem grant ->
-- sempre DENY", mesmo com default_policy=allow na capability) — inclusive
-- o WhatsApp E2E e o scheduler em producao.
--
-- profile='infra-read' e o que importa de verdade: e o profile do UNICO
-- service_identity real do Hermes neste Homolog (confirmado ao vivo:
-- actor_id='hermes-homolog', profile='infra-read'). profile='hermes-homolog'
-- e adicionado so por paridade com o padrao ja existente de infra.action
-- (que tem grant nos dois profiles).

INSERT INTO capability_grants (tenant_id, profile, capability_id, policy_override, active)
SELECT '11a26649-91d0-4971-8d1f-2afc57f8b5ae'::uuid, v.profile, v.capability_id, NULL, true
FROM (VALUES
  ('infra-read', 'supabase.projects.read'),
  ('infra-read', 'supabase.health.read'),
  ('infra-read', 'supabase.keepalive.run'),
  ('infra-read', 'supabase.keepalive.status'),
  ('infra-read', 'supabase.ops.summary'),
  ('hermes-homolog', 'supabase.projects.read'),
  ('hermes-homolog', 'supabase.health.read'),
  ('hermes-homolog', 'supabase.keepalive.run'),
  ('hermes-homolog', 'supabase.keepalive.status'),
  ('hermes-homolog', 'supabase.ops.summary')
) AS v(profile, capability_id)
WHERE NOT EXISTS (
  SELECT 1 FROM capability_grants g
  WHERE g.tenant_id = '11a26649-91d0-4971-8d1f-2afc57f8b5ae'::uuid
    AND g.profile = v.profile AND g.capability_id = v.capability_id
);

-- Verificacao pos-seed (deve retornar 10 linhas):
-- SELECT profile, capability_id FROM capability_grants
-- WHERE tenant_id = '11a26649-91d0-4971-8d1f-2afc57f8b5ae' AND capability_id LIKE 'supabase.%'
-- ORDER BY capability_id, profile;
