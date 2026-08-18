-- Migration: 003_identity_lifecycle_audit
-- Sprint 0.4 — Prosperfy Cognitive V2 — trilha de auditoria de provisionamento
-- Depende de: 000_foundation_tenancy, 001_capability_registry_audit,
--             002_service_identities_lookup_least_privilege
--
-- Contexto (16-FASE-0-FOUNDATION-SPEC.md, subphase 0.4): "Evoluir API key
-- inicial para clients/credentials/actors sem acoplar identidade ao Hermes."
-- Sprint 0.3 entregou o lado de leitura/lookup de service_identities
-- (migration 001 cria a tabela; migration 002 tranca o acesso direto atrás
-- de resolve_service_identity_by_credential_hash). O lado de provisionamento
-- — ServiceIdentityRepository.register()/deactivate() — sempre existiu, mas
-- sem trilha de auditoria própria: não havia registro de quem provisionou
-- ou revogou qual credential_hash, quando. Esta migration fecha essa lacuna.
--
-- ─── Identity Events (append-only) ─────────────────────────────────────────
-- Mesmo padrão de audit_events (001): tabela append-only, RLS tenant-scoped
-- para leitura, sem UPDATE/DELETE para nenhuma role de runtime. Diferença
-- deliberada em relação a audit_events: nem INSERT é concedido a
-- cognitive_app/cognitive_worker aqui. register()/deactivate()/rotate() são
-- bootstrap/CLI — nunca chamados por rota HTTP do Gateway (mesma
-- justificativa do docstring de identity_repo.py) — e escrevem exclusivamente
-- via admin_connection(), a mesma conexão que já escreve em
-- service_identities. Não existe caminho de runtime (web) que precise
-- inserir aqui, então não existe grant de INSERT pra runtime: menos
-- superfície é mais seguro que superfície "concedida mas nunca exercida".
--
-- event_type restrito a 'registered'/'deactivated' — únicas duas operações
-- que ServiceIdentityRepository expõe hoje. rotate() (Sprint 0.4) não é um
-- terceiro event_type: internamente é um deactivate() do credential antigo
-- seguido de um register() do novo, dentro da MESMA transação — produz
-- naturalmente duas linhas aqui (uma 'deactivated', uma 'registered'), sem
-- precisar de um terceiro valor no CHECK nem de lógica extra de leitura.
--
-- actor_id e profile aqui espelham os da service_identity afetada no
-- momento do evento (não um "quem operou" separado — este sistema não tem
-- hoje um conceito de operador humano distinto do actor_id da própria
-- identidade sendo provisionada/revogada; bootstrap/CLI roda com a conexão
-- admin, não com uma identidade de serviço própria). Nenhum valor de
-- credencial em claro ou hash entra nesta tabela — só os 4 campos que já
-- não são segredo (ADR-V2-006 continua valendo: credential_hash nunca sai
-- de service_identities/lookup).
CREATE TABLE IF NOT EXISTS identity_events (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type          TEXT        NOT NULL CHECK (event_type IN ('registered','deactivated')),
  service_identity_id UUID        NOT NULL REFERENCES service_identities(id),
  tenant_id           UUID        NOT NULL REFERENCES tenants(id),
  actor_id            TEXT        NOT NULL,
  profile             TEXT        NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_identity_events_tenant_created
  ON identity_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_identity_events_service_identity
  ON identity_events(service_identity_id);

-- ─── RLS: leitura tenant-scoped, escrita nenhuma para app/worker ──────────
-- Visibilidade é só pra suportar uma futura view no Console ("quando essa
-- credential foi emitida/revogada") — não é o caminho de escrita. Mesmo
-- shape da policy de leitura de audit_events em 001.
ALTER TABLE identity_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_read ON identity_events;
CREATE POLICY tenant_isolation_read ON identity_events
  FOR SELECT
  TO cognitive_app, cognitive_worker
  USING (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Nenhuma policy de INSERT/UPDATE/DELETE é criada para cognitive_app/
-- cognitive_worker — combinado com a ausência do GRANT correspondente
-- abaixo, isso é bloqueio em duas camadas (grant é a barreira primária,
-- como em 002: sem GRANT, o INSERT falha por privilégio antes mesmo de RLS
-- ser avaliada; a ausência de policy é a rede de segurança caso um GRANT
-- seja adicionado por engano no futuro sem revisar esta migration).
GRANT SELECT ON identity_events TO cognitive_app, cognitive_worker;
GRANT ALL    ON identity_events TO cognitive_admin;
