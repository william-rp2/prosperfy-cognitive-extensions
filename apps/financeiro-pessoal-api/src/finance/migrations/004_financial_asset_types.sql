-- F2A: canonical financial asset classification (additive, backward compatible).

ALTER TABLE financial_accounts ADD COLUMN canonical_type TEXT;
ALTER TABLE financial_accounts ADD COLUMN asset_classification_confidence REAL;
ALTER TABLE financial_accounts ADD COLUMN asset_classification_uncertain INTEGER NOT NULL DEFAULT 0;

ALTER TABLE financial_investments ADD COLUMN canonical_type TEXT;
ALTER TABLE financial_investments ADD COLUMN asset_classification_confidence REAL;
