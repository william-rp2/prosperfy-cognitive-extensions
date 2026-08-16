import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import type { FinancialCreditCardBillRow, FinancialInvestmentRow } from './types.js'

export interface UpsertCreditCardBillInput {
  pluggyBillId: string
  pluggyAccountId: string
  dueDate?: string | null
  billClosingDate?: string | null
  totalAmountCents?: number | null
  minimumPaymentCents?: number | null
  currencyCode?: string | null
  rawData?: unknown
}

export interface UpsertInvestmentInput {
  pluggyInvestmentId: string
  pluggyItemId: string
  type?: string | null
  subtype?: string | null
  name?: string | null
  code?: string | null
  balanceCents?: number | null
  quantity?: string | null
  rate?: number | null
  rateType?: string | null
  referenceDate?: string | null
  rawData?: unknown
}

export class ProductsRepository {
  constructor(private readonly db: FinanceDb) {}

  upsertCreditCardBill(input: UpsertCreditCardBillInput): FinancialCreditCardBillRow {
    const now = new Date().toISOString()
    const existing = this.getBillByPluggyId(input.pluggyBillId)

    this.db
      .prepare(
        `INSERT INTO financial_credit_card_bills (id, pluggy_bill_id, pluggy_account_id, due_date, bill_closing_date, total_amount_cents, minimum_payment_cents, currency_code, created_at, updated_at, last_synced_at, raw_data)
         VALUES (@id, @pluggyBillId, @pluggyAccountId, @dueDate, @billClosingDate, @totalAmountCents, @minimumPaymentCents, @currencyCode, @createdAt, @updatedAt, @lastSyncedAt, @rawData)
         ON CONFLICT(pluggy_bill_id) DO UPDATE SET
           due_date = excluded.due_date,
           bill_closing_date = excluded.bill_closing_date,
           total_amount_cents = excluded.total_amount_cents,
           minimum_payment_cents = excluded.minimum_payment_cents,
           currency_code = excluded.currency_code,
           updated_at = excluded.updated_at,
           last_synced_at = excluded.last_synced_at,
           raw_data = excluded.raw_data`,
      )
      .run({
        id: existing?.id ?? randomUUID(),
        pluggyBillId: input.pluggyBillId,
        pluggyAccountId: input.pluggyAccountId,
        dueDate: input.dueDate ?? null,
        billClosingDate: input.billClosingDate ?? null,
        totalAmountCents: input.totalAmountCents ?? null,
        minimumPaymentCents: input.minimumPaymentCents ?? null,
        currencyCode: input.currencyCode ?? null,
        createdAt: existing?.created_at ?? now,
        updatedAt: now,
        lastSyncedAt: now,
        rawData: input.rawData !== undefined ? JSON.stringify(input.rawData) : null,
      })

    return this.getBillByPluggyId(input.pluggyBillId)!
  }

  getBillByPluggyId(pluggyBillId: string): FinancialCreditCardBillRow | undefined {
    return this.db.prepare('SELECT * FROM financial_credit_card_bills WHERE pluggy_bill_id = ?').get(pluggyBillId) as
      | FinancialCreditCardBillRow
      | undefined
  }

  upsertInvestment(input: UpsertInvestmentInput): FinancialInvestmentRow {
    const now = new Date().toISOString()
    const existing = this.getInvestmentByPluggyId(input.pluggyInvestmentId)

    this.db
      .prepare(
        `INSERT INTO financial_investments (id, pluggy_investment_id, pluggy_item_id, type, subtype, name, code, balance_cents, quantity, rate, rate_type, reference_date, created_at, updated_at, last_synced_at, raw_data)
         VALUES (@id, @pluggyInvestmentId, @pluggyItemId, @type, @subtype, @name, @code, @balanceCents, @quantity, @rate, @rateType, @referenceDate, @createdAt, @updatedAt, @lastSyncedAt, @rawData)
         ON CONFLICT(pluggy_investment_id) DO UPDATE SET
           type = excluded.type,
           subtype = excluded.subtype,
           name = excluded.name,
           code = excluded.code,
           balance_cents = excluded.balance_cents,
           quantity = excluded.quantity,
           rate = excluded.rate,
           rate_type = excluded.rate_type,
           reference_date = excluded.reference_date,
           updated_at = excluded.updated_at,
           last_synced_at = excluded.last_synced_at,
           raw_data = excluded.raw_data`,
      )
      .run({
        id: existing?.id ?? randomUUID(),
        pluggyInvestmentId: input.pluggyInvestmentId,
        pluggyItemId: input.pluggyItemId,
        type: input.type ?? null,
        subtype: input.subtype ?? null,
        name: input.name ?? null,
        code: input.code ?? null,
        balanceCents: input.balanceCents ?? null,
        quantity: input.quantity ?? null,
        rate: input.rate ?? null,
        rateType: input.rateType ?? null,
        referenceDate: input.referenceDate ?? null,
        createdAt: existing?.created_at ?? now,
        updatedAt: now,
        lastSyncedAt: now,
        rawData: input.rawData !== undefined ? JSON.stringify(input.rawData) : null,
      })

    return this.getInvestmentByPluggyId(input.pluggyInvestmentId)!
  }

  getInvestmentByPluggyId(pluggyInvestmentId: string): FinancialInvestmentRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_investments WHERE pluggy_investment_id = ?')
      .get(pluggyInvestmentId) as FinancialInvestmentRow | undefined
  }
}
