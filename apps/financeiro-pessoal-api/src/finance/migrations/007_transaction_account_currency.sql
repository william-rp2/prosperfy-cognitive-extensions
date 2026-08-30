-- Original transaction amount/currency preserved; account-converted amount for aggregation.

ALTER TABLE financial_transactions ADD COLUMN amount_in_account_currency_cents INTEGER;
ALTER TABLE financial_transactions ADD COLUMN account_currency_code TEXT;
