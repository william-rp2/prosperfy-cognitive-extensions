-- Transaction notes (user context) + optional responsible label on account preferences.

ALTER TABLE financial_account_preferences ADD COLUMN responsible_label TEXT;

CREATE TABLE IF NOT EXISTS financial_transaction_annotations (
  pluggy_transaction_id  TEXT PRIMARY KEY REFERENCES financial_transactions(pluggy_transaction_id),
  note                   TEXT NOT NULL,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_financial_transaction_annotations_updated
  ON financial_transaction_annotations(updated_at);
