-- F2B: typed temporal semantics on transactions (PLAN.md decision D2 — typed columns, not opaque JSON).
-- A transaction date does not answer every question: purchase month, competence month,
-- cashflow month and statement cycle are separate, auditable facts.

ALTER TABLE financial_transactions ADD COLUMN posted_date TEXT;
ALTER TABLE financial_transactions ADD COLUMN purchase_month TEXT;
ALTER TABLE financial_transactions ADD COLUMN competence_month TEXT;
ALTER TABLE financial_transactions ADD COLUMN cashflow_month TEXT;
ALTER TABLE financial_transactions ADD COLUMN statement_cycle_id TEXT REFERENCES financial_statement_cycles(id);
ALTER TABLE financial_transactions ADD COLUMN cycle_assignment_source TEXT;
ALTER TABLE financial_transactions ADD COLUMN cycle_assignment_confidence REAL;
ALTER TABLE financial_transactions ADD COLUMN cycle_assignment_updated_at TEXT;

-- Backfill: purchase_month is a pure derivation of the stored transaction date, so it is safe.
UPDATE financial_transactions
   SET purchase_month = substr(date, 1, 7)
 WHERE purchase_month IS NULL AND date IS NOT NULL;

-- Backfill: default competence for existing rows is the purchase month. This is the documented
-- default policy, not an invention; cycle assignment or an owner correction overrides it later.
UPDATE financial_transactions
   SET competence_month = purchase_month
 WHERE competence_month IS NULL AND purchase_month IS NOT NULL;

-- Backfill: cash actually moves on the transaction date only for non-credit accounts.
-- Credit-card rows keep cashflow_month NULL until a statement payment is known.
UPDATE financial_transactions
   SET cashflow_month = purchase_month
 WHERE cashflow_month IS NULL
   AND purchase_month IS NOT NULL
   AND pluggy_account_id IN (
     SELECT pluggy_account_id FROM financial_accounts
      WHERE type IS NULL OR UPPER(type) <> 'CREDIT'
   );

-- statement_cycle_id is deliberately left NULL for all history: never fabricate a cycle
-- without evidence. Cycles arrive from bills, statement imports, rules or the owner.

CREATE INDEX IF NOT EXISTS ix_financial_transactions_competence_month
  ON financial_transactions(competence_month);

CREATE INDEX IF NOT EXISTS ix_financial_transactions_statement_cycle
  ON financial_transactions(statement_cycle_id);

CREATE INDEX IF NOT EXISTS ix_financial_transactions_purchase_month
  ON financial_transactions(purchase_month);

CREATE INDEX IF NOT EXISTS ix_financial_transactions_cashflow_month
  ON financial_transactions(cashflow_month);
