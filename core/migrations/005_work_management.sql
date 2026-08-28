-- Migration: 005_work_management
-- Track P1 — Ideias, Projetos e Tarefas (Supabase canônico + Trello adapter)
-- Depende de: 000_foundation_tenancy, 001_capability_registry_audit
--
-- Decisão estrutural (P1 spec §1): Supabase é Source of Truth. Trello é
-- Adapter/View descartável — nenhum ID nem regra de negócio central pode
-- depender do Trello. work_trello_bindings é a ÚNICA tabela que conhece IDs
-- Trello; todas as demais (work_projects/work_ideas/work_tasks/relações)
-- são 100% independentes do adapter.
--
-- Cria: work_projects, work_ideas, work_tasks, work_idea_projects,
--       work_task_projects, work_task_ideas, work_task_dependencies,
--       work_events, work_trello_bindings, work_sync_outbox.
-- RLS: mesmo padrão de 000-003 (SET LOCAL app.current_tenant_id via
-- tenant_transaction). work_events é append-only (SELECT+INSERT, sem
-- UPDATE/DELETE para cognitive_app/cognitive_worker) — mesmo padrão de
-- audit_events (001).
--
-- Hard delete NÃO é fluxo normal (P1 spec §3.3): "arquivar" preserva
-- histórico via archived_at + status='archived'. DELETE físico é
-- capability administrativa separada, fora do escopo V1 (default_policy
-- deny), não implementada aqui.

-- ─── work_projects ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS work_projects (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  title        TEXT        NOT NULL,
  description  TEXT,
  status       TEXT        NOT NULL DEFAULT 'planned'
                            CHECK (status IN ('planned','active','on_hold','completed','cancelled','archived')),
  priority     TEXT        NOT NULL DEFAULT 'medium'
                            CHECK (priority IN ('low','medium','high','urgent')),
  owner        TEXT,                       -- principal_id (tenant_members) — livre, sem FK (mesmo padrão de actor_id)
  start_date   DATE,
  due_date     DATE,
  tags         TEXT[]      NOT NULL DEFAULT '{}',
  created_by   TEXT        NOT NULL,       -- actor_id de quem criou
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  archived_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_projects_tenant_status
  ON work_projects(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_work_projects_tenant_updated
  ON work_projects(tenant_id, updated_at DESC);

ALTER TABLE work_projects ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_projects;
CREATE POLICY tenant_isolation ON work_projects
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE ON work_projects TO cognitive_app, cognitive_worker;
GRANT ALL ON work_projects TO cognitive_admin;

-- ─── work_ideas ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS work_ideas (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  title        TEXT        NOT NULL,
  description  TEXT,
  status       TEXT        NOT NULL DEFAULT 'inbox'
                            CHECK (status IN ('inbox','evaluating','approved','rejected','converted','archived')),
  source       TEXT,                       -- 'whatsapp' | 'manual' | 'email' | ...
  impact       TEXT        CHECK (impact IN ('low','medium','high') OR impact IS NULL),
  value_notes  TEXT,                       -- justificativa livre de valor/impacto
  tags         TEXT[]      NOT NULL DEFAULT '{}',
  created_by   TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  archived_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_ideas_tenant_status
  ON work_ideas(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_work_ideas_tenant_updated
  ON work_ideas(tenant_id, updated_at DESC);

ALTER TABLE work_ideas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_ideas;
CREATE POLICY tenant_isolation ON work_ideas
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE ON work_ideas TO cognitive_app, cognitive_worker;
GRANT ALL ON work_ideas TO cognitive_admin;

-- ─── work_tasks ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS work_tasks (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  title        TEXT        NOT NULL,
  description  TEXT,
  status       TEXT        NOT NULL DEFAULT 'todo'
                            CHECK (status IN ('todo','in_progress','blocked','waiting','done','cancelled','archived')),
  priority     TEXT        NOT NULL DEFAULT 'medium'
                            CHECK (priority IN ('low','medium','high','urgent')),
  assignee     TEXT,                       -- principal_id, livre sem FK
  due_at       TIMESTAMPTZ,
  source       TEXT,
  created_by   TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  archived_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_tasks_tenant_status
  ON work_tasks(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_work_tasks_tenant_updated
  ON work_tasks(tenant_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_tasks_tenant_assignee
  ON work_tasks(tenant_id, assignee);

ALTER TABLE work_tasks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_tasks;
CREATE POLICY tenant_isolation ON work_tasks
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE ON work_tasks TO cognitive_app, cognitive_worker;
GRANT ALL ON work_tasks TO cognitive_admin;

-- ─── work_idea_projects (M2M: Idea <-> Project) ────────────────────────────
CREATE TABLE IF NOT EXISTS work_idea_projects (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  idea_id      UUID        NOT NULL REFERENCES work_ideas(id) ON DELETE CASCADE,
  project_id   UUID        NOT NULL REFERENCES work_projects(id) ON DELETE CASCADE,
  relation     TEXT        NOT NULL DEFAULT 'contributes_to',
  created_by   TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_work_idea_project
  ON work_idea_projects(idea_id, project_id);
CREATE INDEX IF NOT EXISTS idx_work_idea_projects_tenant
  ON work_idea_projects(tenant_id);
CREATE INDEX IF NOT EXISTS idx_work_idea_projects_project
  ON work_idea_projects(project_id);

ALTER TABLE work_idea_projects ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_idea_projects;
CREATE POLICY tenant_isolation ON work_idea_projects
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON work_idea_projects TO cognitive_app, cognitive_worker;
GRANT ALL ON work_idea_projects TO cognitive_admin;

-- ─── work_task_projects (M2M: Task <-> Project) ────────────────────────────
CREATE TABLE IF NOT EXISTS work_task_projects (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  task_id      UUID        NOT NULL REFERENCES work_tasks(id) ON DELETE CASCADE,
  project_id   UUID        NOT NULL REFERENCES work_projects(id) ON DELETE CASCADE,
  is_primary   BOOLEAN     NOT NULL DEFAULT false,
  created_by   TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_work_task_project
  ON work_task_projects(task_id, project_id);
CREATE INDEX IF NOT EXISTS idx_work_task_projects_tenant
  ON work_task_projects(tenant_id);
CREATE INDEX IF NOT EXISTS idx_work_task_projects_project
  ON work_task_projects(project_id);

ALTER TABLE work_task_projects ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_task_projects;
CREATE POLICY tenant_isolation ON work_task_projects
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON work_task_projects TO cognitive_app, cognitive_worker;
GRANT ALL ON work_task_projects TO cognitive_admin;

-- ─── work_task_ideas (M2M: Task <-> Idea) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS work_task_ideas (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  task_id      UUID        NOT NULL REFERENCES work_tasks(id) ON DELETE CASCADE,
  idea_id      UUID        NOT NULL REFERENCES work_ideas(id) ON DELETE CASCADE,
  relation     TEXT        NOT NULL DEFAULT 'implements',  -- 'implements' | 'validates'
  created_by   TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_work_task_idea
  ON work_task_ideas(task_id, idea_id);
CREATE INDEX IF NOT EXISTS idx_work_task_ideas_tenant
  ON work_task_ideas(tenant_id);
CREATE INDEX IF NOT EXISTS idx_work_task_ideas_idea
  ON work_task_ideas(idea_id);

ALTER TABLE work_task_ideas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_task_ideas;
CREATE POLICY tenant_isolation ON work_task_ideas
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON work_task_ideas TO cognitive_app, cognitive_worker;
GRANT ALL ON work_task_ideas TO cognitive_admin;

-- ─── work_task_dependencies (Task -> Task: depends_on/blocks) ──────────────
CREATE TABLE IF NOT EXISTS work_task_dependencies (
  id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  task_id            UUID        NOT NULL REFERENCES work_tasks(id) ON DELETE CASCADE,  -- tarefa bloqueada
  depends_on_task_id UUID        NOT NULL REFERENCES work_tasks(id) ON DELETE CASCADE,  -- tarefa bloqueadora
  created_by         TEXT        NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (task_id <> depends_on_task_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_work_task_dependency
  ON work_task_dependencies(task_id, depends_on_task_id);
CREATE INDEX IF NOT EXISTS idx_work_task_dependencies_tenant
  ON work_task_dependencies(tenant_id);
CREATE INDEX IF NOT EXISTS idx_work_task_dependencies_depends_on
  ON work_task_dependencies(depends_on_task_id);

ALTER TABLE work_task_dependencies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_task_dependencies;
CREATE POLICY tenant_isolation ON work_task_dependencies
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON work_task_dependencies TO cognitive_app, cognitive_worker;
GRANT ALL ON work_task_dependencies TO cognitive_admin;

-- ─── work_events (append-only history — mesmo padrão de audit_events) ─────
CREATE TABLE IF NOT EXISTS work_events (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  entity_type     TEXT        NOT NULL
                              CHECK (entity_type IN ('idea','project','task','idea_project','task_project','task_idea','task_dependency','trello_binding')),
  entity_id       UUID        NOT NULL,
  event_type      TEXT        NOT NULL,   -- 'created' | 'updated' | 'status_changed' | 'linked' | 'unlinked' | 'archived' | 'synced_to_trello' | 'synced_from_trello'
  before_state    JSONB       NOT NULL DEFAULT '{}',
  after_state     JSONB       NOT NULL DEFAULT '{}',
  actor_id        TEXT        NOT NULL,
  correlation_id  TEXT        NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_work_events_tenant_entity
  ON work_events(tenant_id, entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_events_correlation
  ON work_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_work_events_tenant_created
  ON work_events(tenant_id, created_at DESC);

-- Append-only: sem UPDATE/DELETE policy → implicitamente bloqueado.
ALTER TABLE work_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_read ON work_events;
DROP POLICY IF EXISTS tenant_isolation_insert ON work_events;

CREATE POLICY tenant_isolation_read ON work_events
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true));

CREATE POLICY tenant_isolation_insert ON work_events
  FOR INSERT
  TO cognitive_app, cognitive_worker
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT ON work_events TO cognitive_app, cognitive_worker;
GRANT ALL ON work_events TO cognitive_admin;

-- ─── work_trello_bindings (adapter mapping — ÚNICA tabela ciente do Trello) ─
-- entity_type='board'|'list': linhas de registro do board/listas (entity_id NULL).
-- entity_type='idea'|'project'|'task': binding 1:1 entidade -> card Trello.
CREATE TABLE IF NOT EXISTS work_trello_bindings (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  entity_type       TEXT        NOT NULL CHECK (entity_type IN ('board','list','idea','project','task')),
  entity_id         UUID,                 -- NULL para entity_type IN ('board','list')
  list_key          TEXT,                 -- chave lógica: 'inbox'|'ideias'|'projetos'|'todo'|'in_progress'|'blocked'|'waiting'|'done'
  board_id          TEXT        NOT NULL,
  list_id           TEXT,                 -- lista Trello atual (registro de lista, ou lista atual do card)
  card_id           TEXT,                 -- só para entity_type IN ('idea','project','task')
  sync_state        TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (sync_state IN ('pending','synced','conflict','error')),
  last_synced_at    TIMESTAMPTZ,
  last_synced_hash  TEXT,                 -- hash do conteúdo (name+desc+list+due) na última escrita DB->Trello — base do anti-echo
  last_error        TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Uma linha por entidade (idea/project/task) já vinculada.
CREATE UNIQUE INDEX IF NOT EXISTS uq_work_trello_binding_entity
  ON work_trello_bindings(tenant_id, entity_type, entity_id)
  WHERE entity_id IS NOT NULL;

-- Uma linha de board por tenant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_work_trello_binding_board
  ON work_trello_bindings(tenant_id)
  WHERE entity_type = 'board';

-- Uma linha por lista lógica por tenant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_work_trello_binding_list
  ON work_trello_bindings(tenant_id, list_key)
  WHERE entity_type = 'list';

CREATE INDEX IF NOT EXISTS idx_work_trello_bindings_card
  ON work_trello_bindings(card_id) WHERE card_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_work_trello_bindings_tenant
  ON work_trello_bindings(tenant_id);

ALTER TABLE work_trello_bindings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_trello_bindings;
CREATE POLICY tenant_isolation ON work_trello_bindings
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON work_trello_bindings TO cognitive_app, cognitive_worker;
GRANT ALL ON work_trello_bindings TO cognitive_admin;

-- ─── work_sync_outbox (retry confiável DB -> Trello) ───────────────────────
CREATE TABLE IF NOT EXISTS work_sync_outbox (
  id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  entity_type      TEXT        NOT NULL CHECK (entity_type IN ('idea','project','task','task_dependency')),
  entity_id        UUID        NOT NULL,
  operation        TEXT        NOT NULL CHECK (operation IN ('create','update','move','archive','link','unlink')),
  payload          JSONB       NOT NULL DEFAULT '{}',
  status           TEXT        NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending','processing','done','failed','dead_letter')),
  attempts         INTEGER     NOT NULL DEFAULT 0,
  max_attempts     INTEGER     NOT NULL DEFAULT 5,
  last_error       TEXT,
  correlation_id   TEXT        NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_sync_outbox_pending
  ON work_sync_outbox(status, next_attempt_at) WHERE status IN ('pending','failed');
CREATE INDEX IF NOT EXISTS idx_work_sync_outbox_tenant
  ON work_sync_outbox(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_sync_outbox_entity
  ON work_sync_outbox(entity_type, entity_id);

ALTER TABLE work_sync_outbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON work_sync_outbox;
CREATE POLICY tenant_isolation ON work_sync_outbox
  FOR ALL
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

GRANT SELECT, INSERT, UPDATE ON work_sync_outbox TO cognitive_app, cognitive_worker;
GRANT ALL ON work_sync_outbox TO cognitive_admin;

-- ─── Capability grants (V1 owner-core no dev tenant, mesmo padrão do infra) ─
-- Sem grants automáticos aqui — grants reais são inseridos via
-- capability_grants (migration 000) pelo bootstrap/seed do ambiente, não
-- hardcoded na migration de schema (mesmo padrão de 001-003: nenhuma delas
-- insere capability_grants).
