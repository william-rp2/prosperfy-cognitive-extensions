"""adapters/supabase_registry — terceiro adapter do orchestrator (P0).

Sem chamada de rede: expõe leituras do registry local (supabase_projects /
supabase_keepalive_runs) atrás do contrato SkillsAdapterPort, para reusar
policy/grant/audit do ExecutionOrchestrator nas capabilities de leitura
(supabase.projects.read / keepalive.status / ops.summary).
"""
