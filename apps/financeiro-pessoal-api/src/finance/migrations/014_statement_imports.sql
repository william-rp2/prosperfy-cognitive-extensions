-- F2B: closed statement imports, their line items and the reconciliation link
-- statement-line <-> app transaction (SUBAGENT_D).
--
-- Invariants encoded here:
--  * These tables are a SEPARATE evidence layer. `financial_transactions.raw_data` is never
--    written by this feature; a statement never overwrites nor deletes provider evidence.
--  * Statement text is UNTRUSTED DATA. `description_raw` / `raw_text` are opaque payload
--    columns, never interpreted as instructions and never used to derive a path or a decision.
--  * Re-importing the same statement is idempotent: identity is a content hash, and every
--    child row carries a stable natural key so a second import updates instead of duplicating.
--  * A divergence is RECORDED, never silently repaired by deleting data.
-- Money is INTEGER cents. Dates are ISO-8601 UTC TEXT. competence_month is 'YYYY-MM'.

CREATE TABLE IF NOT EXISTS financial_statement_imports (
  id                    TEXT PRIMARY KEY,
  financial_account_id  TEXT NOT NULL REFERENCES financial_accounts(pluggy_account_id),
  statement_cycle_id    TEXT REFERENCES financial_statement_cycles(id),
  source                TEXT NOT NULL,
  content_hash          TEXT NOT NULL,
  file_name             TEXT,
  institution_hint      TEXT,
  card_last4            TEXT,
  competence_month      TEXT NOT NULL,
  statement_currency    TEXT NOT NULL,
  period_start          TEXT,
  period_end            TEXT,
  closing_date          TEXT,
  due_date              TEXT,
  statement_total_cents INTEGER,
  parsed_total_cents    INTEGER,
  status                TEXT NOT NULL DEFAULT 'PARSED',
  raw_text              TEXT,
  metadata_json         TEXT,
  imported_at           TEXT NOT NULL,
  reconciled_at         TEXT,
  CHECK (source IN ('HERMES_ATTACHMENT', 'FINANCE_EMAIL_ATTACHMENT', 'MANUAL_UPLOAD', 'PLUGGY_BILL', 'PDF_UPLOAD')),
  CHECK (status IN ('PARSED', 'RECONCILING', 'RECONCILED', 'DISCREPANT')),
  CHECK (competence_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]')
);

-- Idempotency anchor: same account + same bytes => same import row.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_statement_imports_content
  ON financial_statement_imports(financial_account_id, content_hash);

CREATE INDEX IF NOT EXISTS ix_financial_statement_imports_cycle
  ON financial_statement_imports(statement_cycle_id);

CREATE TABLE IF NOT EXISTS financial_statement_lines (
  id                   TEXT PRIMARY KEY,
  statement_import_id  TEXT NOT NULL REFERENCES financial_statement_imports(id) ON DELETE CASCADE,
  statement_cycle_id   TEXT REFERENCES financial_statement_cycles(id),
  line_index           INTEGER NOT NULL,
  line_hash            TEXT NOT NULL,
  date                 TEXT,
  description_raw      TEXT NOT NULL,
  amount_cents         INTEGER NOT NULL,
  currency_code        TEXT NOT NULL,
  line_type            TEXT NOT NULL DEFAULT 'UNKNOWN',
  card_hint            TEXT,
  source_page          INTEGER,
  created_at           TEXT NOT NULL,
  CHECK (line_type IN ('PURCHASE', 'PAYMENT', 'REFUND', 'FEE', 'IOF', 'INTEREST', 'ADJUSTMENT', 'UNKNOWN'))
);

-- Natural key for a line inside its statement: re-import updates, never duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_statement_lines_identity
  ON financial_statement_lines(statement_import_id, line_hash);

CREATE INDEX IF NOT EXISTS ix_financial_statement_lines_import
  ON financial_statement_lines(statement_import_id);

-- The reconciliation link. A row with a NULL transaction is "só no extrato"; a row with a NULL
-- line is "só no app". Both are first-class recorded outcomes, not errors to be swept away.
CREATE TABLE IF NOT EXISTS financial_statement_reconciliations (
  id                    TEXT PRIMARY KEY,
  statement_import_id   TEXT NOT NULL REFERENCES financial_statement_imports(id) ON DELETE CASCADE,
  statement_cycle_id    TEXT REFERENCES financial_statement_cycles(id),
  statement_line_id     TEXT REFERENCES financial_statement_lines(id) ON DELETE CASCADE,
  pluggy_transaction_id TEXT,
  match_status          TEXT NOT NULL,
  confidence            REAL NOT NULL DEFAULT 0,
  amount_delta_cents    INTEGER NOT NULL DEFAULT 0,
  assignment_applied    INTEGER NOT NULL DEFAULT 0,
  assignment_rejected   TEXT,
  evidence_json         TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  CHECK (match_status IN ('EXACT', 'HIGH', 'AMBIGUOUS', 'CONFLICT', 'STATEMENT_ONLY', 'APP_ONLY')),
  CHECK (statement_line_id IS NOT NULL OR pluggy_transaction_id IS NOT NULL)
);

-- SQLite treats NULLs as distinct in unique indexes, so the key is coalesced.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_statement_reconciliations_pair
  ON financial_statement_reconciliations(
    statement_import_id,
    COALESCE(statement_line_id, ''),
    COALESCE(pluggy_transaction_id, '')
  );

CREATE INDEX IF NOT EXISTS ix_financial_statement_reconciliations_import
  ON financial_statement_reconciliations(statement_import_id);

CREATE INDEX IF NOT EXISTS ix_financial_statement_reconciliations_status
  ON financial_statement_reconciliations(match_status);

-- Divergences are persisted so they stay visible after the run that found them.
CREATE TABLE IF NOT EXISTS financial_statement_discrepancies (
  id                  TEXT PRIMARY KEY,
  statement_import_id TEXT NOT NULL REFERENCES financial_statement_imports(id) ON DELETE CASCADE,
  statement_cycle_id  TEXT REFERENCES financial_statement_cycles(id),
  kind                TEXT NOT NULL,
  subject_key         TEXT NOT NULL,
  delta_cents         INTEGER,
  detail_json         TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  resolved_at         TEXT,
  CHECK (kind IN ('TOTAL_MISMATCH', 'STATEMENT_ONLY', 'APP_ONLY', 'AMOUNT_MISMATCH', 'AMBIGUOUS'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_statement_discrepancies_identity
  ON financial_statement_discrepancies(statement_import_id, kind, subject_key);

CREATE INDEX IF NOT EXISTS ix_financial_statement_discrepancies_import
  ON financial_statement_discrepancies(statement_import_id);
