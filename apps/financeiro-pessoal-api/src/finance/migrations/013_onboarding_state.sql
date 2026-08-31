-- F2B: incremental historical-onboarding state per institution/item (SUBAGENT_B).
-- Onboarding is per pluggy_item_id (institution connection), not global and not
-- hard-coded: a bank enters HISTORICAL_IMPORT the moment its item is registered
-- and moves to ONGOING only on an explicit owner-driven cutover. A second bank
-- added later gets its own row and never touches an existing one (06 doc: banks
-- run independently, older banks may already be ONGOING).

CREATE TABLE IF NOT EXISTS finance_onboarding_state (
  id                       TEXT PRIMARY KEY,
  pluggy_item_id           TEXT NOT NULL UNIQUE REFERENCES financial_items(pluggy_item_id),
  mode                     TEXT NOT NULL DEFAULT 'HISTORICAL_IMPORT',
  onboarding_started_at    TEXT NOT NULL,
  historical_cutoff_at     TEXT,
  onboarding_completed_at  TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL,
  CHECK (mode IN ('HISTORICAL_IMPORT', 'ONGOING'))
);

CREATE INDEX IF NOT EXISTS ix_finance_onboarding_state_mode
  ON finance_onboarding_state(mode);

-- Per-row export/import bookkeeping for the spreadsheet round-trip (06 doc: stale
-- spreadsheet protection). One row per batch produced by POST .../onboarding/export.
CREATE TABLE IF NOT EXISTS finance_onboarding_exports (
  id             TEXT PRIMARY KEY,
  pluggy_item_id TEXT REFERENCES financial_items(pluggy_item_id),
  export_version INTEGER NOT NULL,
  filters_json   TEXT,
  row_count      INTEGER NOT NULL,
  created_at     TEXT NOT NULL
);

-- Per-row import audit trail (06 doc: batch idempotency — reimporting an
-- already-applied file must not duplicate corrections/resolutions).
-- import_batch_id + transaction_id is the idempotency key: the same row from the
-- same import run is applied at most once.
CREATE TABLE IF NOT EXISTS finance_onboarding_import_rows (
  id                    TEXT PRIMARY KEY,
  import_batch_id       TEXT NOT NULL,
  pluggy_transaction_id TEXT NOT NULL,
  action                TEXT NOT NULL,
  status                TEXT NOT NULL,
  error_code            TEXT,
  applied_at            TEXT,
  created_at            TEXT NOT NULL,
  CHECK (status IN ('applied', 'rejected', 'conflict', 'skipped'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_finance_onboarding_import_rows_idempotent
  ON finance_onboarding_import_rows(import_batch_id, pluggy_transaction_id);

CREATE INDEX IF NOT EXISTS ix_finance_onboarding_import_rows_batch
  ON finance_onboarding_import_rows(import_batch_id);
