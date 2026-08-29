-- F1: extend enrichment metadata + persistent finance clarifications.
-- Additive only — preserves raw Pluggy rows in financial_transactions.

ALTER TABLE financial_transaction_enrichment ADD COLUMN canonical_type TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN direction TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN raw_type TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN payment_method TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN classification_status TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE financial_transaction_enrichment ADD COLUMN classification_confidence REAL;
ALTER TABLE financial_transaction_enrichment ADD COLUMN classification_source TEXT;

CREATE TABLE IF NOT EXISTS finance_clarifications (
  id                     TEXT PRIMARY KEY,
  pluggy_transaction_id  TEXT NOT NULL REFERENCES financial_transactions(pluggy_transaction_id),
  question_type          TEXT NOT NULL,
  status                 TEXT NOT NULL DEFAULT 'open',
  question_text          TEXT,
  created_at             TEXT NOT NULL,
  resolved_at            TEXT,
  resolved_by            TEXT,
  resolution             TEXT,
  source_message_id      TEXT,
  quoted_message_id      TEXT
);

CREATE INDEX IF NOT EXISTS ix_finance_clarifications_tx ON finance_clarifications(pluggy_transaction_id);
CREATE INDEX IF NOT EXISTS ix_finance_clarifications_status ON finance_clarifications(status);

-- At most one OPEN clarification per transaction + question type.
CREATE UNIQUE INDEX IF NOT EXISTS ux_finance_clarifications_open
  ON finance_clarifications(pluggy_transaction_id, question_type)
  WHERE status = 'open';
