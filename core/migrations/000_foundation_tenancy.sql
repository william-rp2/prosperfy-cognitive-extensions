-- Migration: 000_foundation_tenancy
-- Sprint 0.2 — Prosperfy Cognitive V2
-- Aplicar com: cognitive_admin (BYPASSRLS)
-- NUNCA aplicar no Supabase prod sem aprovação humana explícita.
--
-- Cria: roles, tabelas base de tenancy, RLS policies.
-- Estratégia RLS: SET LOCAL app.current_tenant_id + current_setting()
-- Roles: cognitive_admin (bypass), cognitive_app (RLS), cognitive_worker (RLS)

-- ─── Roles ─────────────────────────────────────────────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cognitive_admin') THEN
    CREATE ROLE cognitive_admin BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cognitive_app') THEN
    CREATE ROLE cognitive_app LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cognitive_worker') THEN
    CREATE ROLE cognitive_worker LOGIN;
  END IF;
END $$;

-- cognitive_app / cognitive_worker: LOGIN without password here.
-- Runtime credentials assigned by secure bootstrap (see cognitive/gate/credential_bootstrap.py).

-- ─── Extensions ────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ─── Tenants ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        TEXT        NOT NULL UNIQUE,          -- ex: "prosperfy", "cliente-a"
  name        TEXT        NOT NULL,
  active      BOOLEAN     NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tenants IS 'Unidade de isolamento de dados, policies e billing.';

-- ─── Tenant Members ────────────────────────────────────────────────────────
-- Vínculo humano/serviço ↔ tenant (ADR-V2-002)
CREATE TABLE IF NOT EXISTS tenant_members (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  principal_id    TEXT        NOT NULL,   -- actor_id; pode ser user_id, hermes, worker slug
  principal_type  TEXT        NOT NULL CHECK (principal_type IN ('human','service','worker')),
  profile         TEXT        NOT NULL DEFAULT 'observer',  -- owner-core, infra-read, finance, ...
  active          BOOLEAN     NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_member
  ON tenant_members(tenant_id, principal_id);

-- ─── Tenant Resources ──────────────────────────────────────────────────────
-- Recursos lógicos tenant-scoped (ADR-V2-002 §3)
CREATE TABLE IF NOT EXISTS tenant_resources (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  resource_key    TEXT        NOT NULL,   -- ex: "prosperfy-main" — lógico, nunca IP
  resource_type   TEXT        NOT NULL,   -- "vps" | "mailbox" | "supabase-project" | ...
  resolved_params JSONB       NOT NULL DEFAULT '{}',  -- host, port, project_ref, etc.
  active          BOOLEAN     NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_resource_key
  ON tenant_resources(tenant_id, resource_key);

-- ─── Credential Refs ───────────────────────────────────────────────────────
-- Ponteiros para secret store — NUNCA armazenar valor em claro (ADR-V2-006)
CREATE TABLE IF NOT EXISTS credential_refs (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider        TEXT        NOT NULL,   -- "prosperfy_mcp" | "pluggy" | "smtp" | ...
  secret_ref      TEXT        NOT NULL,   -- ptr para env var ou vault key — sem valor
  rotated_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Tenant Integrations ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenant_integrations (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider            TEXT        NOT NULL,
  credential_ref_id   UUID        REFERENCES credential_refs(id),
  config              JSONB       NOT NULL DEFAULT '{}',
  active              BOOLEAN     NOT NULL DEFAULT true,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Capability Grants ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS capability_grants (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  profile         TEXT        NOT NULL,   -- "owner-core" | "infra-read" | ...
  capability_id   TEXT        NOT NULL,   -- "infra.inspect"
  policy_override TEXT        CHECK (policy_override IN ('allow','confirm','deny')),
  active          BOOLEAN     NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_capability_grant
  ON capability_grants(tenant_id, profile, capability_id);

-- ─── RLS — Tenants ─────────────────────────────────────────────────────────
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_self_read ON tenants;
CREATE POLICY tenant_self_read ON tenants
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (id::text = current_setting('app.current_tenant_id', true));

-- ─── RLS — Tenant Members ──────────────────────────────────────────────────
ALTER TABLE tenant_members ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant_members;
CREATE POLICY tenant_isolation ON tenant_members
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- ─── RLS — Tenant Resources ────────────────────────────────────────────────
ALTER TABLE tenant_resources ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant_resources;
CREATE POLICY tenant_isolation ON tenant_resources
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- ─── RLS — Credential Refs ─────────────────────────────────────────────────
ALTER TABLE credential_refs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON credential_refs;
CREATE POLICY tenant_isolation ON credential_refs
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- ─── RLS — Tenant Integrations ─────────────────────────────────────────────
ALTER TABLE tenant_integrations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant_integrations;
CREATE POLICY tenant_isolation ON tenant_integrations
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- ─── RLS — Capability Grants ───────────────────────────────────────────────
ALTER TABLE capability_grants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON capability_grants;
CREATE POLICY tenant_isolation ON capability_grants
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- ─── Grants de acesso às tabelas ───────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON tenants            TO cognitive_app, cognitive_worker;
GRANT SELECT, INSERT, UPDATE ON tenant_members     TO cognitive_app, cognitive_worker;
GRANT SELECT, INSERT, UPDATE ON tenant_resources   TO cognitive_app, cognitive_worker;
GRANT SELECT                  ON credential_refs   TO cognitive_app, cognitive_worker;
GRANT SELECT, INSERT, UPDATE ON tenant_integrations TO cognitive_app, cognitive_worker;
GRANT SELECT, INSERT, UPDATE ON capability_grants  TO cognitive_app, cognitive_worker;

-- cognitive_admin: acesso total (BYPASSRLS já está na role)
GRANT ALL ON ALL TABLES IN SCHEMA public TO cognitive_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO cognitive_admin;
