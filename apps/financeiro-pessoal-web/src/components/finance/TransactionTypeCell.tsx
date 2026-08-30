import type { FinanceAccount, FinanceTransaction } from '../../api/finance'
import {
  formatTransactionAccountContext,
  formatTransactionDisplay,
  normalizeFinanceEnrichment,
} from '../../lib/financePresentation'

/** Same rendering path used by ConnectedTransactionsScreen "Tipo" column. */
export function TransactionTypeCell({
  transaction,
  account,
}: {
  transaction: Pick<
    FinanceTransaction,
    'enrichment' | 'type' | 'description' | 'descriptionRaw' | 'accountId'
  >
  account?: Pick<
    FinanceAccount,
    | 'displayAlias'
    | 'displayName'
    | 'name'
    | 'marketingName'
    | 'institutionName'
    | 'canonicalType'
    | 'last4'
    | 'cardBrand'
  > | null
}) {
  const enrichment = normalizeFinanceEnrichment(transaction.enrichment) ?? transaction.enrichment ?? null
  const label = formatTransactionDisplay(enrichment, transaction.type, {
    description: transaction.description,
    descriptionRaw: transaction.descriptionRaw,
    accountCanonicalType: account?.canonicalType,
  })
  const context =
    transaction.accountId && account
      ? formatTransactionAccountContext({
          displayAlias: account.displayAlias,
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
    <div data-testid="transaction-type-cell">
      <p className="font-semibold text-[#231529]" data-testid="transaction-type-label">
        {label}
      </p>
      {context ? (
        <p className="mt-0.5 text-xs text-[#76677d]" data-testid="transaction-account-context">
          {context}
        </p>
      ) : null}
    </div>
  )
}

export function transactionTypeLabel(
  transaction: Pick<
    FinanceTransaction,
    'enrichment' | 'type' | 'description' | 'descriptionRaw' | 'accountId'
  >,
  account?: Pick<FinanceAccount, 'canonicalType'> | null,
): string {
  const enrichment = normalizeFinanceEnrichment(transaction.enrichment) ?? transaction.enrichment ?? null
  return formatTransactionDisplay(enrichment, transaction.type, {
    description: transaction.description,
    descriptionRaw: transaction.descriptionRaw,
    accountCanonicalType: account?.canonicalType,
  })
}
