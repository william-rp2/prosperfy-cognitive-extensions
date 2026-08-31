-- F2B: first-class card statement cycles (our domain truth).
-- Deliberately NOT an extension of financial_credit_card_bills: that table stays a
-- read-only mirror of upstream Pluggy bills (PLAN.md decision D3). Cycles may be
-- created from a bill, an imported statement, a closing-date rule or the owner.
-- Money is INTEGER cents. Dates are ISO-8601 UTC TEXT. competence_month is 'YYYY-MM'.
-- Internal enums are English; user-facing text is pt-BR at the presentation layer.

CREATE TABLE IF NOT EXISTS financial_statement_cycles (
  id                    TEXT PRIMARY KEY,
  financial_account_id  TEXT NOT NULL REFERENCES financial_accounts(pluggy_account_id),
  source                TEXT NOT NULL,
  source_external_id    TEXT,
  cycle_label           TEXT NOT NULL,
  period_start          TEXT,
  period_end            TEXT,
  closing_date          TEXT,
  due_date              TEXT,
  competence_month      TEXT NOT NULL,
  statement_currency    TEXT NOT NULL,
  statement_total_cents INTEGER,
  effective_total_cents INTEGER,
  status                TEXT NOT NULL DEFAULT 'OPEN',
  reconciliation_status TEXT NOT NULL DEFAULT 'PENDING',
  imported_at           TEXT NOT NULL,
  closed_at             TEXT,
  metadata_json         TEXT,
  CHECK (status IN ('OPEN', 'CLOSED_SOURCE', 'RECONCILING', 'RECONCILED', 'DISCREPANT', 'ARCHIVED')),
  CHECK (reconciliation_status IN ('PENDING', 'IN_PROGRESS', 'MATCHED', 'DRIFT', 'DISCREPANT')),
  CHECK (source IN ('PLUGGY_BILL', 'STATEMENT_IMPORT', 'USER', 'RULE', 'INFERRED')),
  CHECK (competence_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]')
);

-- One cycle per (account, competence, source): a second import from the same source for the
-- same competence updates the existing cycle instead of forking a duplicate truth.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_statement_cycles_identity
  ON financial_statement_cycles(financial_account_id, competence_month, source);

CREATE INDEX IF NOT EXISTS ix_financial_statement_cycles_account
  ON financial_statement_cycles(financial_account_id);

CREATE INDEX IF NOT EXISTS ix_financial_statement_cycles_competence
  ON financial_statement_cycles(competence_month);

CREATE INDEX IF NOT EXISTS ix_financial_statement_cycles_status
  ON financial_statement_cycles(status);
