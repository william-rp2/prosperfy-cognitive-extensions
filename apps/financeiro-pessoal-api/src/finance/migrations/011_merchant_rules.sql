-- F2B: learned merchant rules.
-- match_kind never allows loose substring matching: a broad substring contaminates unrelated
-- merchants. Only exact, normalized-identity or anchored-with-token-boundary matches exist.
-- New semantic rules default to SUGGEST; only an explicit owner promotion makes them TRUSTED.

CREATE TABLE IF NOT EXISTS finance_merchant_rules (
  id               TEXT PRIMARY KEY,
  merchant_pattern TEXT NOT NULL,
  match_kind       TEXT NOT NULL DEFAULT 'normalized',
  scope_account_id TEXT REFERENCES financial_accounts(pluggy_account_id),
  rule_type        TEXT NOT NULL,
  target_value     TEXT NOT NULL,
  mode             TEXT NOT NULL DEFAULT 'SUGGEST',
  active           INTEGER NOT NULL DEFAULT 1,
  created_by       TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  evidence_json    TEXT,
  CHECK (match_kind IN ('exact', 'normalized', 'anchored')),
  CHECK (mode IN ('SUGGEST', 'TRUSTED')),
  CHECK (active IN (0, 1)),
  CHECK (rule_type IN (
    'CURRENCY_HINT', 'CATEGORY', 'ECONOMIC_OWNER', 'RESPONSIBLE', 'REIMBURSEMENT', 'COMPETENCE'
  )),
  CHECK (length(trim(merchant_pattern)) > 0)
);

-- One active rule per (pattern, match kind, rule type, scope). Re-creating updates in place.
-- IFNULL keeps the global scope ('*') distinct from any real account id.
CREATE UNIQUE INDEX IF NOT EXISTS ux_finance_merchant_rules_identity
  ON finance_merchant_rules(merchant_pattern, match_kind, rule_type, IFNULL(scope_account_id, '*'))
  WHERE active = 1;

CREATE INDEX IF NOT EXISTS ix_finance_merchant_rules_type
  ON finance_merchant_rules(rule_type, active);

CREATE INDEX IF NOT EXISTS ix_finance_merchant_rules_scope
  ON finance_merchant_rules(scope_account_id);
