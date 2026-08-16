export interface FinancialItemRow {
  id: string
  pluggy_item_id: string
  connector_id: number | null
  connector_name: string | null
  status: string
  execution_status: string | null
  last_successful_update: string | null
  created_at: string
  updated_at: string
  last_synced_at: string | null
  error_summary: string | null
  raw_metadata: string | null
}

export interface FinancialAccountRow {
  id: string
  pluggy_account_id: string
  pluggy_item_id: string
  type: string | null
  subtype: string | null
  name: string | null
  marketing_name: string | null
  currency_code: string | null
  balance_cents: number | null
  number_masked: string | null
  owner: string | null
  credit_limit_cents: number | null
  available_credit_limit_cents: number | null
  created_at: string
  updated_at: string
  last_synced_at: string | null
  raw_data: string | null
}

export interface FinancialTransactionRow {
  id: string
  pluggy_transaction_id: string
  pluggy_account_id: string
  description: string | null
  description_raw: string | null
  amount_cents: number
  currency_code: string | null
  date: string
  status: string | null
  type: string | null
  category_original: string | null
  merchant_original: string | null
  balance_cents: number | null
  created_at: string
  updated_at: string
  last_synced_at: string | null
  deleted_at: string | null
  raw_data: string | null
}

export interface FinancialCreditCardBillRow {
  id: string
  pluggy_bill_id: string
  pluggy_account_id: string
  due_date: string | null
  bill_closing_date: string | null
  total_amount_cents: number | null
  minimum_payment_cents: number | null
  currency_code: string | null
  created_at: string
  updated_at: string
  last_synced_at: string | null
  raw_data: string | null
}

export interface FinancialInvestmentRow {
  id: string
  pluggy_investment_id: string
  pluggy_item_id: string
  type: string | null
  subtype: string | null
  name: string | null
  code: string | null
  balance_cents: number | null
  quantity: string | null
  rate: number | null
  rate_type: string | null
  reference_date: string | null
  created_at: string
  updated_at: string
  last_synced_at: string | null
  raw_data: string | null
}

export type SyncTrigger = 'manual' | 'cron' | 'initial'
export type SyncStatus = 'running' | 'success' | 'partial' | 'failed'

export interface FinancialSyncRunRow {
  id: string
  provider: string
  started_at: string
  finished_at: string | null
  status: SyncStatus
  trigger: SyncTrigger
  items_processed: number
  accounts_processed: number
  transactions_created: number
  transactions_updated: number
  error_count: number
  error_summary: string | null
  metadata: string | null
}

export function toCents(amount: number): number {
  return Math.round(amount * 100)
}

export function fromCents(cents: number | null): number | null {
  if (cents === null || cents === undefined) return null
  return cents / 100
}
