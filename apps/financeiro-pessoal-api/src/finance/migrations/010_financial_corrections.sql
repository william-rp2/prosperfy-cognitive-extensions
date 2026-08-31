-- F2B: append-only correction ledger (PLAN.md decision D4).
-- raw_data on financial_transactions is NEVER rewritten. The effective view is derived at
-- read time as RAW -> NORMALIZED -> CORRECTION/RULE -> EFFECTIVE.
-- A correction is superseded, never updated in place, so history stays auditable.

CREATE TABLE IF NOT EXISTS financial_corrections (
  -- Ordering key. created_at alone cannot order the ledger: two corrections applied inside the
  -- same millisecond tie, and tie-breaking on a random UUID makes the audit trail
  -- non-deterministic. AUTOINCREMENT is strictly increasing and never reused, so insertion
  -- order survives even if a row is ever removed.
  seq                   INTEGER PRIMARY KEY AUTOINCREMENT,
  id                    TEXT NOT NULL UNIQUE,
  pluggy_transaction_id TEXT NOT NULL REFERENCES financial_transactions(pluggy_transaction_id),
  field                 TEXT NOT NULL,
  old_effective_value   TEXT,
  new_effective_value   TEXT,
  reason                TEXT,
  source                TEXT NOT NULL,
  actor_id              TEXT,
  created_at            TEXT NOT NULL,
  superseded_at         TEXT,
  CHECK (field IN (
    'amount', 'currency', 'amount_in_account_currency', 'category', 'merchant',
    'economic_owner', 'responsible', 'reimbursement', 'competence_month',
    'statement_cycle', 'notes'
  )),
  CHECK (source IN ('USER', 'RULE', 'STATEMENT_IMPORT', 'SYSTEM'))
);

-- At most one active correction per (transaction, field). Superseded rows stay for audit.
CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_corrections_active
  ON financial_corrections(pluggy_transaction_id, field)
  WHERE superseded_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_financial_corrections_tx
  ON financial_corrections(pluggy_transaction_id);

CREATE INDEX IF NOT EXISTS ix_financial_corrections_field
  ON financial_corrections(field);

-- Reimbursement / economic-entity attribution.
-- DESIGN CHOICE: these live as typed columns on financial_transaction_enrichment, not as
-- correction-only fields. Rationale: enrichment is the existing derived/normalized projection
-- and must be SQL-queryable for aggregates and filters (who owes whom, what is outstanding),
-- while financial_corrections stays a pure append-only audit trail. Every write to these
-- columns that originates from an owner decision also emits a correction row
-- (field = economic_owner / responsible / reimbursement), so the audit trail is not lost.
ALTER TABLE financial_transaction_enrichment ADD COLUMN economic_owner TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN paid_by TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN receivable_from TEXT;
ALTER TABLE financial_transaction_enrichment ADD COLUMN receivable_status TEXT;

CREATE INDEX IF NOT EXISTS ix_enrichment_receivable_status
  ON financial_transaction_enrichment(receivable_status);
