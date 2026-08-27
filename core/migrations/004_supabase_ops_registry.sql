-- Migration: 004_supabase_ops_registry
-- P0 — Supabase Ops + Anti-Hibernação
-- Depende de: 000_foundation_tenancy (tenants, roles cognitive_admin/app/worker, RLS).
--
-- Contexto (docs/P0_Supabase_Ops_Anti_Hibernacao.txt §5/§6): registry local dos
-- projetos Supabase conectados via Compose MCP + histórico de execuções de
-- keepalive read-only. O Compose MCP (inventário ao vivo) continua sendo a
-- fonte primária de "quais projetos existem" (ADR-V2-005: banco não é source
-- of truth de definição) — esta tabela é o ESTADO OPERACIONAL local: qual é o
-- plano detectado, se keepalive está habilitado, último resultado, para que
-- uma pausa em um projeto monitorado não esconda o próprio histórico dele
-- (doc §6: "Não usar o próprio projeto monitorado como único local de
-- registro").
--
-- ─── supabase_projects (registry, upsert) ──────────────────────────────────
-- Uma linha por projeto Supabase conectado (project_ref é o identificador
-- público do projeto — 20 chars, usado na própria URL do dashboard Supabase;
-- não é secret). UPDATE frequente (last_success_at, consecutive_failures,
-- status, next_run_at) tanto pelo scheduler (cognitive_worker) quanto pelo
-- caminho on-demand via WhatsApp/Hermes ("Teste agora o Supabase X" →
-- capability supabase.keepalive.run executada via cognitive_app). Mesmo
-- shape de tenant_resources (migration 000): policy FOR ALL, sem admin-only,
-- porque os dois papéis de runtime legitimamente escrevem aqui.
CREATE TABLE IF NOT EXISTS supabase_projects (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             UUID        NOT NULL REFERENCES tenants(id),
  composio_account      TEXT        NOT NULL,   -- alias da conta Composio (ex.: "Supabase - Hermes") — não é secret
  project_ref           TEXT        NOT NULL,   -- ref público do projeto (20 chars) — identificador, não secret
  display_name          TEXT        NOT NULL,
  region                TEXT,
  plan                  TEXT        NOT NULL DEFAULT 'unknown'
                                     CHECK (plan IN ('free','paid','unknown')),
  plan_source           TEXT        NOT NULL DEFAULT 'undetermined',  -- origem da classificação, ou causa do unknown
  keepalive_enabled     BOOLEAN     NOT NULL DEFAULT false,
  status                TEXT        NOT NULL DEFAULT 'unknown'
                                     CHECK (status IN ('healthy','warning','failed','paused','unknown')),
  last_success_at       TIMESTAMPTZ,
  last_latency_ms       INTEGER,
  consecutive_failures  INTEGER     NOT NULL DEFAULT 0,
  last_error_code       TEXT,
  next_run_at           TIMESTAMPTZ,
  active                BOOLEAN     NOT NULL DEFAULT true,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, project_ref)
);

CREATE INDEX IF NOT EXISTS idx_supabase_projects_tenant
  ON supabase_projects(tenant_id);
CREATE INDEX IF NOT EXISTS idx_supabase_projects_keepalive
  ON supabase_projects(tenant_id, keepalive_enabled)
  WHERE active = true;

ALTER TABLE supabase_projects ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON supabase_projects;
CREATE POLICY tenant_isolation ON supabase_projects
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE ON supabase_projects TO cognitive_app, cognitive_worker;
GRANT ALL ON supabase_projects TO cognitive_admin;

-- ─── supabase_keepalive_runs (append-only) ─────────────────────────────────
-- Uma linha por execução de keepalive (start/end/status/latency/error já
-- resolvidos no momento do INSERT — nunca há UPDATE de uma linha existente).
-- Mesmo shape de audit_events (migration 001): policy de SELECT e policy de
-- INSERT separadas, sem UPDATE/DELETE para cognitive_app/cognitive_worker.
-- error_message é sempre sanitizado pelo SupabaseKeepaliveService antes de
-- persistir (nunca DSN/token/secret — mesmo contrato de
-- adapters/prosperfy_skills/client.py `sanitize_exception`).
CREATE TABLE IF NOT EXISTS supabase_keepalive_runs (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id),
  project_id      UUID        NOT NULL REFERENCES supabase_projects(id),
  started_at      TIMESTAMPTZ NOT NULL,
  ended_at        TIMESTAMPTZ NOT NULL,
  status          TEXT        NOT NULL CHECK (status IN ('success','failure','skipped')),
  latency_ms      INTEGER,
  error_code      TEXT,
  error_message   TEXT,          -- sanitizado — nunca secret/DSN/token
  triggered_by    TEXT        NOT NULL DEFAULT 'scheduler'
                               CHECK (triggered_by IN ('scheduler','manual','whatsapp')),
  correlation_id  TEXT        NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_supabase_runs_tenant_created
  ON supabase_keepalive_runs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_supabase_runs_project_created
  ON supabase_keepalive_runs(project_id, created_at DESC);

ALTER TABLE supabase_keepalive_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_read ON supabase_keepalive_runs;
DROP POLICY IF EXISTS tenant_isolation_insert ON supabase_keepalive_runs;

CREATE POLICY tenant_isolation_read ON supabase_keepalive_runs
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true));

CREATE POLICY tenant_isolation_insert ON supabase_keepalive_runs
  FOR INSERT
  TO cognitive_app, cognitive_worker
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Sem UPDATE/DELETE policy → implicitamente bloqueado (append-only, mesma
-- garantia estrutural de audit_events em 001).
GRANT SELECT, INSERT ON supabase_keepalive_runs TO cognitive_app, cognitive_worker;
GRANT ALL ON supabase_keepalive_runs TO cognitive_admin;
