-- Migration: 006_browser_harness_capability_grants
-- Track BH — Browser Harness V1
-- Depende de: 000_foundation_tenancy (tabela capability_grants)
--
-- Semeia o grant de leitura (browser.read) para TODOS os tenants existentes.
-- Sem esta linha, browser.read cai em DENY [no_grant] mesmo com
-- default_policy: allow no YAML (registry/grant_resolver.py -- sem grant,
-- a policy do YAML nunca é consultada).
--
-- browser.act e browser.account NAO recebem grant automatico aqui de
-- proposito: sao default_policy=deny (escrita/criacao de conta) e exigem
-- grant explicito por tenant, decidido caso a caso pelo Arquiteto/PO --
-- mesma postura de infra.action (nunca semeado em massa).
--
-- Numeracao: worktree Track BH partiu de master b2bddbb (so 000-003
-- presentes localmente). 004/005 pertencem as tracks P0/P1 (aplicadas
-- direto no Homolog, fora deste worktree — doc 00 Sec.3). 006 assume que
-- 004/005 já estão aplicadas; CONFIRME com
-- `SELECT version FROM _migrations ORDER BY version DESC LIMIT 5;` antes
-- de aplicar — se o proximo numero livre for outro, renomeie este arquivo
-- de acordo (o SQL abaixo não depende do número do arquivo).
--
-- HUMAN_BLOCKER: esta sessão não teve SQL access ao Homolog
-- (esvjfkknrzzziafovwrv) — mcp Supabase direto respondeu "permission to
-- perform this action" e prosperfy_supabase_* respondeu "Nenhum inventário
-- de contas encontrado" (accounts.yaml ausente no deploy deste MCP). O
-- arquivo está pronto; falta braço humano/sessão com credencial válida
-- para rodar via apply_migration ou prosperfy_supabase_aplicar_migration.

INSERT INTO capability_grants (tenant_id, profile, capability_id, policy_override)
SELECT id, 'owner-core', 'browser.read', NULL
FROM tenants
ON CONFLICT (tenant_id, profile, capability_id) DO NOTHING;
