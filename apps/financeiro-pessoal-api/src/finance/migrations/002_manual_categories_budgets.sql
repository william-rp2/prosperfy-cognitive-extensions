-- P2 (Financeiro WhatsApp): internal categories, manual transactions,
-- per-transaction category overrides and monthly budgets.
--
-- Hard rule preserved from 001: never edit the raw Pluggy record. Manual
-- entries live in their own table (source='manual', never merged into
-- financial_transactions) and reclassifications live in an override table
-- keyed by pluggy_transaction_id — financial_transactions.category_original
-- stays exactly what Pluggy sent.

CREATE TABLE IF NOT EXISTS financial_categories (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  kind        TEXT NOT NULL DEFAULT 'expense', -- expense | income | both
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_manual_transactions (
  id                     TEXT PRIMARY KEY,
  source                 TEXT NOT NULL DEFAULT 'manual',
  amount_cents           INTEGER NOT NULL CHECK (amount_cents > 0),
  direction              TEXT NOT NULL CHECK (direction IN ('income','expense')),
  occurred_at            TEXT NOT NULL,
  description            TEXT NOT NULL,
  category_id            TEXT REFERENCES financial_categories(id),
  account_id             TEXT,
  notes                  TEXT,
  created_by             TEXT NOT NULL DEFAULT 'cognitive',
  reconciliation_status  TEXT NOT NULL DEFAULT 'unreconciled',
  deleted_at             TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_financial_manual_tx_date ON financial_manual_transactions(occurred_at);
CREATE INDEX IF NOT EXISTS ix_financial_manual_tx_category ON financial_manual_transactions(category_id);

-- One override per Pluggy transaction. previous_category_original keeps what
-- Pluggy said at override time, purely for audit — it is never written back.
CREATE TABLE IF NOT EXISTS financial_category_overrides (
  pluggy_transaction_id       TEXT PRIMARY KEY REFERENCES financial_transactions(pluggy_transaction_id),
  category_id                 TEXT NOT NULL REFERENCES financial_categories(id),
  previous_category_original  TEXT,
  overridden_by                TEXT NOT NULL DEFAULT 'cognitive',
  created_at                  TEXT NOT NULL,
  updated_at                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_budgets (
  id                  TEXT PRIMARY KEY,
  month               TEXT NOT NULL, -- 'YYYY-MM'
  category_id         TEXT REFERENCES financial_categories(id), -- NULL = orçamento geral do mês
  limit_amount_cents  INTEGER NOT NULL CHECK (limit_amount_cents >= 0),
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  deleted_at          TEXT
);

-- Partial unique indexes: SQLite treats NULL as distinct in a plain UNIQUE
-- constraint (would allow many "general" budgets per month), so the NULL
-- case gets its own WHERE-scoped index instead of relying on the tuple.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_budgets_month_category
  ON financial_budgets(month, category_id) WHERE category_id IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_budgets_month_general
  ON financial_budgets(month) WHERE category_id IS NULL AND deleted_at IS NULL;

-- Stable starter set so manual entries/overrides/budgets have something to
-- point at immediately. IDs are deliberate slugs (not random) so seeding is
-- idempotent (INSERT OR IGNORE) and WhatsApp free-text matching is simple.
INSERT OR IGNORE INTO financial_categories (id, name, kind, created_at) VALUES
  ('cat_alimentacao',     'Alimentação',     'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_transporte',      'Transporte',      'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_moradia',         'Moradia',         'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_saude',           'Saúde',           'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_lazer',           'Lazer',           'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_combustivel',     'Combustível',     'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_compras',         'Compras',         'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_educacao',        'Educação',        'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_servicos',        'Serviços',        'expense', '2026-01-01T00:00:00.000Z'),
  ('cat_outros',          'Outros',          'both',    '2026-01-01T00:00:00.000Z'),
  ('cat_salario',         'Salário',         'income',  '2026-01-01T00:00:00.000Z'),
  ('cat_receita_outros',  'Outras receitas', 'income',  '2026-01-01T00:00:00.000Z');
