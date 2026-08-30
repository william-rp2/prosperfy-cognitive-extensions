import type { FinanceAccount, FinanceTransaction } from '../../api/finance'
import {
  formatTransactionAccountContext,
  formatTransactionDisplay,
} from '../../lib/financePresentation'

/** Same rendering path used by ConnectedTransactionsScreen "Tipo" column. */
export function TransactionTypeCell({
  transaction,
  account,
}: {
  transaction: Pick<FinanceTransaction, 'enrichment' | 'type' | 'description' | 'accountId'>
  account?: Pick<
    FinanceAccount,
    'displayName' | 'name' | 'marketingName' | 'institutionName' | 'canonicalType' | 'last4' | 'cardBrand'
  > | null
}) {
  const label = formatTransactionDisplay(transaction.enrichment, transaction.type, {
    description: transaction.description,
    accountCanonicalType: account?.canonicalType,
  })
  const context =
    transaction.accountId && account
      ? formatTransactionAccountContext({
          displayName: account.displayName,
          name: account.name,
          marketingName: account.marketingName,
          institutionName: account.institutionName,
          canonicalType: account.canonicalType,
          last4: account.last4,
          cardBrand: account.cardBrand,
        })
      : null

  return (
    <div>
      <p className="font-semibold text-[#231529]">{label}</p>
      {context ? <p className="mt-0.5 text-xs text-[#76677d]">{context}</p> : null}
    </div>
  )
}

export function transactionTypeLabel(
  transaction: Pick<FinanceTransaction, 'enrichment' | 'type' | 'description' | 'accountId'>,
  account?: Pick<FinanceAccount, 'canonicalType'> | null,
): string {
  return formatTransactionDisplay(transaction.enrichment, transaction.type, {
    description: transaction.description,
    accountCanonicalType: account?.canonicalType,
  })
}
