-- Personal finance sync schema (Pluggy -> local SQLite).
-- Money is stored as integer cents (no float) to avoid rounding drift.
-- Dates are stored as ISO-8601 UTC strings.

CREATE TABLE IF NOT EXISTS financial_items (
  id                     TEXT PRIMARY KEY,
  pluggy_item_id         TEXT NOT NULL UNIQUE,
  connector_id           INTEGER,
  connector_name         TEXT,
  status                 TEXT NOT NULL,
  execution_status       TEXT,
  last_successful_update TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  last_synced_at         TEXT,
  error_summary          TEXT,
  raw_metadata           TEXT
);

CREATE TABLE IF NOT EXISTS financial_accounts (
  id                          TEXT PRIMARY KEY,
  pluggy_account_id           TEXT NOT NULL UNIQUE,
  pluggy_item_id              TEXT NOT NULL REFERENCES financial_items(pluggy_item_id),
  type                        TEXT,
  subtype                     TEXT,
  name                        TEXT,
  marketing_name               TEXT,
  currency_code               TEXT,
  balance_cents               INTEGER,
  number_masked               TEXT,
  owner                       TEXT,
  credit_limit_cents          INTEGER,
  available_credit_limit_cents INTEGER,
  created_at                  TEXT NOT NULL,
  updated_at                  TEXT NOT NULL,
  last_synced_at              TEXT,
  raw_data                    TEXT
);

CREATE INDEX IF NOT EXISTS ix_financial_accounts_item ON financial_accounts(pluggy_item_id);

CREATE TABLE IF NOT EXISTS financial_transactions (
  id                     TEXT PRIMARY KEY,
  pluggy_transaction_id  TEXT NOT NULL UNIQUE,
  pluggy_account_id      TEXT NOT NULL REFERENCES financial_accounts(pluggy_account_id),
  description            TEXT,
  description_raw        TEXT,
  amount_cents           INTEGER NOT NULL,
  currency_code          TEXT,
  date                   TEXT NOT NULL,
  status                 TEXT,
  type                   TEXT,
  category_original      TEXT,
  merchant_original      TEXT,
  balance_cents          INTEGER,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  last_synced_at         TEXT,
  deleted_at             TEXT,
  raw_data               TEXT
);

CREATE INDEX IF NOT EXISTS ix_financial_transactions_account_date ON financial_transactions(pluggy_account_id, date);
CREATE INDEX IF NOT EXISTS ix_financial_transactions_date ON financial_transactions(date);

-- Internal classification, kept separate from the raw Pluggy record so our
-- enrichment (categoria, recorrencia, tags, etc.) never overwrites the
-- external/original data.
CREATE TABLE IF NOT EXISTS financial_transaction_enrichment (
  pluggy_transaction_id  TEXT PRIMARY KEY REFERENCES financial_transactions(pluggy_transaction_id),
  category_id            TEXT,
  category_name          TEXT,
  merchant_normalized    TEXT,
  is_recurring           INTEGER,
  cost_center            TEXT,
  tags                   TEXT,
  project                TEXT,
  responsible            TEXT,
  notes                  TEXT,
  updated_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_credit_card_bills (
  id                      TEXT PRIMARY KEY,
  pluggy_bill_id          TEXT NOT NULL UNIQUE,
  pluggy_account_id       TEXT NOT NULL REFERENCES financial_accounts(pluggy_account_id),
  due_date                TEXT,
  bill_closing_date       TEXT,
  total_amount_cents      INTEGER,
  minimum_payment_cents   INTEGER,
  currency_code           TEXT,
  created_at              TEXT NOT NULL,
  updated_at              TEXT NOT NULL,
  last_synced_at          TEXT,
  raw_data                TEXT
);

CREATE INDEX IF NOT EXISTS ix_financial_cc_bills_account ON financial_credit_card_bills(pluggy_account_id);

CREATE TABLE IF NOT EXISTS financial_investments (
  id                     TEXT PRIMARY KEY,
  pluggy_investment_id   TEXT NOT NULL UNIQUE,
  pluggy_item_id         TEXT NOT NULL REFERENCES financial_items(pluggy_item_id),
  type                   TEXT,
  subtype                TEXT,
  name                   TEXT,
  code                   TEXT,
  balance_cents          INTEGER,
  quantity               TEXT,
  rate                   REAL,
  rate_type              TEXT,
  reference_date         TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  last_synced_at         TEXT,
  raw_data               TEXT
);

CREATE INDEX IF NOT EXISTS ix_financial_investments_item ON financial_investments(pluggy_item_id);

CREATE TABLE IF NOT EXISTS financial_sync_runs (
  id                     TEXT PRIMARY KEY,
  provider               TEXT NOT NULL DEFAULT 'pluggy',
  started_at             TEXT NOT NULL,
  finished_at            TEXT,
  status                 TEXT NOT NULL, -- running | success | partial | failed
  trigger                TEXT NOT NULL, -- manual | cron | initial
  items_processed        INTEGER NOT NULL DEFAULT 0,
  accounts_processed     INTEGER NOT NULL DEFAULT 0,
  transactions_created   INTEGER NOT NULL DEFAULT 0,
  transactions_updated   INTEGER NOT NULL DEFAULT 0,
  error_count            INTEGER NOT NULL DEFAULT 0,
  error_summary          TEXT,
  metadata               TEXT
);

-- DB-level execution lock: only one 'running' row per provider allowed at a
-- time. INSERT that violates this constraint means a sync is already going.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_sync_runs_running
  ON financial_sync_runs(provider)
  WHERE status = 'running';

CREATE INDEX IF NOT EXISTS ix_financial_sync_runs_started ON financial_sync_runs(started_at);
