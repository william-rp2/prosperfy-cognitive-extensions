import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import {
  effectiveAccountAmountCents,
  historicalRawHasAccountAmount,
  isCurrencyConversionMissing,
} from './transactionAmount.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let transactions: TransactionsRepository
let accounts: AccountsRepository
let items: ItemsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  transactions = new TransactionsRepository(db)
  accounts = new AccountsRepository(db)
  items = new ItemsRepository(db)
  items.upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
  accounts.upsertAccount({
    pluggyAccountId: 'acc-1',
    pluggyItemId: 'item-1',
    type: 'BANK',
    subtype: 'CHECKING_ACCOUNT',
    name: 'Conta',
    currencyCode: 'BRL',
    balanceCents: 0,
  })
})

afterEach(() => db.close())

describe('transactionAmount — effective account amount', () => {
  it('A. USD 20 + account 109.54 BRL agrega 10954 centavos', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-usd',
      pluggyAccountId: 'acc-1',
      amountCents: -2000,
      currencyCode: 'USD',
      amountInAccountCurrencyCents: 10954,
      accountCurrencyCode: 'BRL',
      type: 'DEBIT',
      date: '2026-08-01T12:00:00.000Z',
    })
    const row = transactions.getByPluggyId('tx-usd')!
    expect(effectiveAccountAmountCents(row)).toBe(10954)
    const sum = transactions.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z')
    expect(sum.expense).toBe(10954)
    expect(sum.expense).not.toBe(2000)
  })

  it('B. BRL 100 agrega 10000 centavos', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-brl',
      pluggyAccountId: 'acc-1',
      amountCents: -10000,
      currencyCode: 'BRL',
      accountCurrencyCode: 'BRL',
      type: 'DEBIT',
      date: '2026-08-02T12:00:00.000Z',
    })
    expect(effectiveAccountAmountCents(transactions.getByPluggyId('tx-brl')!)).toBe(10000)
    const sum = transactions.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z')
    expect(sum.expense).toBe(10000)
  })

  it('C. USD sem conversão é excluída do agregado', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-missing',
      pluggyAccountId: 'acc-1',
      amountCents: -2000,
      currencyCode: 'USD',
      accountCurrencyCode: 'BRL',
      type: 'DEBIT',
      date: '2026-08-03T12:00:00.000Z',
    })
    const row = transactions.getByPluggyId('tx-missing')!
    expect(effectiveAccountAmountCents(row)).toBeNull()
    expect(isCurrencyConversionMissing(row)).toBe(true)
    const sum = transactions.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z')
    expect(sum.expense).toBe(0)
  })

  it('HISTORICAL_RAW_HAS_ACCOUNT_AMOUNT detecta raw Pluggy', () => {
    expect(
      historicalRawHasAccountAmount(
        JSON.stringify({ amount: 20, currencyCode: 'USD', amountInAccountCurrency: 109.54 }),
      ),
    ).toBe(true)
    expect(historicalRawHasAccountAmount(JSON.stringify({ amount: 100, currencyCode: 'BRL' }))).toBe(false)
  })

  it('backfillCurrencyFromRaw preenche colunas a partir do raw persistido', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-backfill',
      pluggyAccountId: 'acc-1',
      amountCents: -2000,
      currencyCode: 'USD',
      type: 'DEBIT',
      date: '2026-08-04T12:00:00.000Z',
      rawData: { amount: 20, currencyCode: 'USD', amountInAccountCurrency: 109.54 },
    })
    expect(transactions.backfillCurrencyFromRaw('tx-backfill', 'BRL')).toBe(true)
    const row = transactions.getByPluggyId('tx-backfill')!
    expect(row.amount_in_account_currency_cents).toBe(10954)
    expect(row.account_currency_code).toBe('BRL')
  })
})
