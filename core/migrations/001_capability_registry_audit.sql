-- Migration: 001_capability_registry_audit
-- Sprint 0.2 — Prosperfy Cognitive V2
-- Depende de: 000_foundation_tenancy
--
-- Cria: service_identities, audit_events, execution_traces, cost_telemetry
-- Todas as tabelas: RLS enabled, filtro por tenant_id

-- ─── Service Identities ────────────────────────────────────────────────────
-- Substitui credenciais estáticas em memória (Sprint 0.1)
-- credential_hash = sha256(Bearer token) — nunca o valor original (ADR-V2-006)
CREATE TABLE IF NOT EXISTS service_identities (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  actor_id          TEXT        NOT NULL,
  credential_hash   TEXT        NOT NULL UNIQUE,   -- sha256 hex do Bearer token
  profile           TEXT        NOT NULL DEFAULT 'observer',
  active            BOOLEAN     NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_used_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_service_identities_hash
  ON service_identities(credential_hash);

-- service_identities: cognitive_admin lê tudo (para lookup no middleware)
-- cognitive_app e cognitive_worker: leem apenas do próprio tenant (RLS)
ALTER TABLE service_identities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON service_identities;
CREATE POLICY tenant_isolation ON service_identities
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- ATENÇÃO: credential lookup é feito como cognitive_admin (sem RLS) para validar
-- o token antes de sabermos o tenant. Após validação → tenant context é setado.
GRANT SELECT ON service_identities TO cognitive_admin;
GRANT SELECT, INSERT, UPDATE ON service_identities TO cognitive_app, cognitive_worker;

-- ─── Audit Events (append-only) ────────────────────────────────────────────
-- R13: toda execução relevante registrada. R14: inputs redigidos.
CREATE TABLE IF NOT EXISTS audit_events (
  audit_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  execution_id      UUID        NOT NULL DEFAULT gen_random_uuid(),
  tenant_id         UUID        NOT NULL REFERENCES tenants(id),
  actor_id          TEXT        NOT NULL,
  capability_id     TEXT        NOT NULL,
  correlation_id    TEXT        NOT NULL,
  policy_decision   TEXT        NOT NULL CHECK (policy_decision IN ('allow','confirm','deny')),
  outcome           TEXT        NOT NULL CHECK (outcome IN ('completed','pending_confirmation','denied','failed')),
  inputs_redacted   JSONB       NOT NULL DEFAULT '{}',   -- nunca secrets em claro
  result_summary    JSONB       NOT NULL DEFAULT '{}',
  duration_ms       INTEGER     NOT NULL DEFAULT 0,
  cost_estimate     NUMERIC(10,4) NOT NULL DEFAULT 0,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Append-only: sem UPDATE/DELETE para cognitive_app e cognitive_worker
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_read ON audit_events;
DROP POLICY IF EXISTS tenant_isolation_insert ON audit_events;

CREATE POLICY tenant_isolation_read ON audit_events
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true));

CREATE POLICY tenant_isolation_insert ON audit_events
  FOR INSERT
  TO cognitive_app, cognitive_worker
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Sem UPDATE/DELETE policy → implicitamente bloqueado para cognitive_app/worker
GRANT SELECT, INSERT ON audit_events TO cognitive_app, cognitive_worker;
GRANT ALL ON audit_events TO cognitive_admin;

CREATE INDEX IF NOT EXISTS idx_audit_tenant_created
  ON audit_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_execution_id
  ON audit_events(execution_id);

-- ─── Execution Traces ──────────────────────────────────────────────────────
-- Passos individuais de capabilities compostas
CREATE TABLE IF NOT EXISTS execution_traces (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  execution_id    UUID        NOT NULL,   -- FK lógica para audit_events.execution_id
  tenant_id       UUID        NOT NULL REFERENCES tenants(id),
  step_index      INTEGER     NOT NULL,
  tool_name       TEXT        NOT NULL,
  status          TEXT        NOT NULL,
  duration_ms     INTEGER     NOT NULL DEFAULT 0,
  error           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE execution_traces ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_read ON execution_traces;
DROP POLICY IF EXISTS tenant_isolation_insert ON execution_traces;

CREATE POLICY tenant_isolation_read ON execution_traces
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true));

CREATE POLICY tenant_isolation_insert ON execution_traces
  FOR INSERT
  TO cognitive_app, cognitive_worker
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT ON execution_traces TO cognitive_app, cognitive_worker;
GRANT ALL ON execution_traces TO cognitive_admin;

-- ─── Cost Telemetry ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cost_telemetry (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id),
  actor_id        TEXT        NOT NULL,
  capability_id   TEXT        NOT NULL,
  correlation_id  TEXT        NOT NULL,
  latency_ms      INTEGER     NOT NULL DEFAULT 0,
  tool_calls      INTEGER     NOT NULL DEFAULT 0,
  tokens_in       INTEGER,
  tokens_out      INTEGER,
  cost_estimate   NUMERIC(10,4) NOT NULL DEFAULT 0,
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE cost_telemetry ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON cost_telemetry;
CREATE POLICY tenant_isolation ON cost_telemetry
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT ON cost_telemetry TO cognitive_app, cognitive_worker;
GRANT ALL ON cost_telemetry TO cognitive_admin;

CREATE INDEX IF NOT EXISTS idx_cost_telemetry_tenant
  ON cost_telemetry(tenant_id, recorded_at DESC);
