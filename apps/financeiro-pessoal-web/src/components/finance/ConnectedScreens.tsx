import { AlertCircle, Landmark, Plug, RefreshCw, Star } from 'lucide-react'
import { useMemo, useState } from 'react'
import { PluggyConnect } from 'react-pluggy-connect'

import {
  addExistingConnection,
  deleteTransactionAnnotation,
  fetchAccounts,
  fetchBills,
  fetchBudgets,
  fetchIntegrations,
  fetchSummary,
  fetchTransactions,
  triggerSync,
  updateAccountPreferences,
  upsertTransactionAnnotation,
  type FinanceAccount,
  type FinanceBill,
  type FinanceBudget,
  type FinanceIntegrationItem,
  type FinanceTransaction,
} from '../../api/finance'
import { apiRequest } from '../../lib/api'
import { FinanceFilterBar, SearchableSelect } from './FinanceFilterBar'
import { TransactionTypeCell, transactionTypeLabel } from './TransactionTypeCell'
import {
  formatAssetType,
  formatAccountDisplayName,
  formatBudgetStatus,
  formatClassificationStatus,
  formatItemStatus,
  formatMaskedNumber,
  formatSyncStatus,
  isInfrastructureConnectorName,
  onboardingMessage,
  onboardingStateLabel,
} from '../../lib/financePresentation'
import {
  accountFilterLabel,
  filterAccounts,
  filterTransactions,
  uniqueInstitutions,
  type TransactionFilterState,
} from '../../lib/transactionFilters'
import { formatMoney, formatTransactionAmount } from '../../lib/moneyFormat'
import { useAsyncData } from '../../hooks/useAsyncData'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { Input } from '../ui/input'

export const financeDemoMode = import.meta.env.VITE_FINANCE_DEMO_MODE === 'true'

function money(value: number | null | undefined, currencyCode = 'BRL') {
  return formatMoney(value, currencyCode)
}

function TransactionAmountCell({ transaction }: { transaction: FinanceTransaction }) {
  const { primary, secondary } = formatTransactionAmount(transaction)
  return (
    <div className="font-bold">
      <p>{primary}</p>
      {secondary ? <p className="mt-0.5 text-xs font-normal text-[#76677d]">{secondary}</p> : null}
    </div>
  )
}

function formatDate(value: string) {
  return value.slice(0, 10).split('-').reverse().join('/')
}

function LoadingCard({ label }: { label: string }) {
  return <Card className="p-6 text-sm font-semibold text-[#76677d]">Carregando {label}…</Card>
}

function ErrorCard({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card className="border-rose-100 bg-rose-50 p-6 text-sm text-rose-800">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="font-bold">Não foi possível carregar dados reais</p>
          <p className="mt-1">{message}</p>
          {onRetry ? (
            <Button className="mt-4" onClick={() => void onRetry()} size="sm" type="button" variant="secondary">
              Tentar novamente
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  )
}

export function DeferredEmptyScreen({ title, description }: { title: string; description: string }) {
  return (
    <Card className="p-8 text-center">
      <p className="text-xs font-black uppercase tracking-[0.18em] text-[#76677d]">Em breve</p>
      <h3 className="mt-2 text-xl font-black text-[#231529]">{title}</h3>
      <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-[#76677d]">{description}</p>
    </Card>
  )
}

function AssetPreferenceActions({
  account,
  onUpdated,
}: {
  account: FinanceAccount
  onUpdated: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [alias, setAlias] = useState(account.displayName ?? '')
  const [responsible, setResponsible] = useState(account.responsibleLabel ?? '')
  const [busy, setBusy] = useState(false)

  const institution =
    account.institutionName && !isInfrastructureConnectorName(account.institutionName)
      ? account.institutionName
      : '—'
  const masked = account.last4 ? `•••• ${account.last4}` : formatMaskedNumber(account.numberMasked)

  async function toggleFavorite() {
    setBusy(true)
    try {
      await updateAccountPreferences(account.id, { isFavorite: !account.isFavorite })
      await onUpdated()
    } finally {
      setBusy(false)
    }
  }

  async function savePreferences() {
    setBusy(true)
    try {
      await updateAccountPreferences(account.id, {
        displayAlias: alias.trim() || null,
        responsibleLabel: responsible.trim() || null,
      })
      setEditing(false)
      await onUpdated()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 space-y-3">
      {editing ? (
        <div className="rounded-xl border border-[#eadfec] bg-[#fffafd] p-3 text-xs text-[#76677d]">
          <p><span className="font-bold">Instituição:</span> {institution}</p>
          <p className="mt-1"><span className="font-bold">Tipo:</span> {formatAssetType(account.canonicalType)}</p>
          {masked ? <p className="mt-1"><span className="font-bold">Final:</span> {masked}</p> : null}
          {account.cardBrand ? <p className="mt-1"><span className="font-bold">Bandeira:</span> {account.cardBrand}</p> : null}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button aria-label={account.isFavorite ? 'Remover dos favoritos' : 'Favoritar'} disabled={busy} onClick={() => void toggleFavorite()} size="sm" type="button" variant="secondary">
          <Star className={`h-4 w-4 ${account.isFavorite ? 'fill-amber-400 text-amber-500' : ''}`} />
          {account.isFavorite ? 'Favorito' : 'Favoritar'}
        </Button>
        {editing ? (
          <>
            <Input aria-label="Apelido" className="max-w-[220px]" onChange={event => setAlias(event.target.value)} placeholder="Apelido" value={alias} />
            <Input aria-label="Responsável" className="max-w-[160px]" onChange={event => setResponsible(event.target.value)} placeholder="Responsável" value={responsible} />
            <Button disabled={busy} onClick={() => void savePreferences()} size="sm" type="button">Salvar</Button>
            <Button disabled={busy} onClick={() => setEditing(false)} size="sm" type="button" variant="secondary">Cancelar</Button>
          </>
        ) : (
          <Button disabled={busy} onClick={() => { setAlias(account.displayName ?? ''); setResponsible(account.responsibleLabel ?? ''); setEditing(true) }} size="sm" type="button" variant="secondary">
            Editar nome
          </Button>
        )}
      </div>
    </div>
  )
}

function MetricCard({ label, value, helper, tone }: { label: string; value: string; helper: string; tone?: string }) {
  const cls =
    tone === 'green'
      ? 'text-emerald-700 border-emerald-100 bg-emerald-50'
      : tone === 'red'
        ? 'text-rose-700 border-rose-100 bg-rose-50'
        : tone === 'blue'
          ? 'text-sky-700 border-sky-100 bg-sky-50'
          : 'text-[#341539] border-[#eadfec] bg-white'
  return (
    <Card className={`p-5 ${cls}`}>
      <p className="text-xs font-black uppercase tracking-[0.18em] opacity-70">{label}</p>
      <p className="mt-3 text-3xl font-black tracking-[-0.04em]">{value}</p>
      <p className="mt-2 text-sm font-medium opacity-78">{helper}</p>
    </Card>
  )
}

export function ConnectedDashboardScreen() {
  const { data, loading, error, refresh } = useAsyncData(async () => {
    const [summary, accounts] = await Promise.all([fetchSummary(), fetchAccounts()])
    return { summary, accounts }
  }, [])

  if (loading) return <LoadingCard label="dashboard" />
  if (error || !data) return <ErrorCard message={error ?? 'Sem dados'} onRetry={refresh} />

  const { summary, accounts } = data
  const cashAccounts = accounts.filter(account => account.canonicalType !== 'CREDIT_CARD' && account.canonicalType !== 'INVESTMENT')
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Saldo em contas" value={money(summary.cashBalance ?? summary.totalBalance)} helper="Conta corrente, pagamento e poupança" tone="blue" />
        <MetricCard label="Investimentos" value={money(summary.investmentBalance)} helper="Patrimônio financeiro separado do caixa" tone="purple" />
        <MetricCard label="Patrimônio financeiro" value={money(summary.financialWealth)} helper="Caixa + investimentos (sem limites de cartão)" tone="green" />
        <MetricCard label="Faturas em cartão" value={money(summary.openCardBalance)} helper="Valor em aberto — não é saldo bancário" tone="red" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="Receitas do mês" value={money(summary.monthIncome)} helper={`Referência ${summary.month}`} tone="green" />
        <MetricCard label="Despesas do mês" value={money(summary.monthExpense)} helper="Pluggy + manual" tone="red" />
        <MetricCard label="Resultado do mês" value={money(summary.monthResult)} helper={summary.lastSync ? `Última sync ${formatDate(summary.lastSync)}` : 'Aguardando sync'} tone={(summary.monthResult ?? 0) < 0 ? 'red' : 'green'} />
      </div>
      <Card className="p-5">
        <p className="text-sm font-bold uppercase tracking-[0.18em] text-[#009688]">Contas conectadas</p>
        {cashAccounts.length === 0 ? (
          <p className="mt-4 text-sm text-[#76677d]">Nenhuma conta bancária sincronizada ainda. Conecte um banco em Contas e Integrações.</p>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {cashAccounts.map(account => (
              <div key={account.id} className="rounded-2xl border border-[#eadfec] bg-white/75 px-4 py-3">
                <p className="text-xs font-black uppercase tracking-[0.14em] text-[#76677d]">{formatAssetType(account.canonicalType)}</p>
                <p className="font-black text-[#231529]">{formatAccountDisplayName(account)}</p>
                <p className="mt-1 text-lg font-black text-[#341539]">{money(account.balance)}</p>
                <AssetPreferenceActions account={account} onUpdated={() => void refresh()} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

export function ConnectedMonthlyScreen({ month }: { month: string }) {
  const { data, loading, error, refresh } = useAsyncData(async () => {
    const [summary, budgets, transactions] = await Promise.all([
      fetchSummary(month),
      fetchBudgets(month),
      fetchTransactions({ startDate: `${month}-01`, endDate: `${month}-31`, limit: 500 }),
    ])
    return { summary, budgets, transactions }
  }, [month])

  if (loading) return <LoadingCard label="visão mensal" />
  if (error || !data) return <ErrorCard message={error ?? 'Sem dados'} onRetry={refresh} />

  const { summary, budgets, transactions } = data
  const totalPlanned = budgets.reduce((acc, b) => acc + (b.limitAmount ?? 0), 0)
  const totalSpent = budgets.reduce((acc, b) => acc + (b.spentAmount ?? 0), 0)

  return (
    <div className="space-y-6">
      <div className="flex gap-3 overflow-x-auto pb-1">
        <MetricCard label="Receitas" value={money(summary.monthIncome)} helper="Backend real" tone="green" />
        <MetricCard label="Despesas" value={money(summary.monthExpense)} helper="Backend real" tone="red" />
        <MetricCard label="Resultado" value={money(summary.monthResult)} helper="Receitas − despesas" tone={(summary.monthResult ?? 0) < 0 ? 'red' : 'green'} />
        <MetricCard label="Orçamento planejado" value={money(totalPlanned)} helper={`${budgets.length} categorias`} tone="blue" />
        <MetricCard label="Orçamento realizado" value={money(totalSpent)} helper="Soma spent dos budgets" tone="purple" />
      </div>
      <Card className="overflow-hidden p-0">
        <div className="overflow-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[#fffafd] text-xs uppercase tracking-[0.14em] text-[#76677d]">
              <tr>
                {['Categoria', 'Limite', 'Gasto', 'Restante', 'Status'].map(col => (
                  <th key={col} className="px-4 py-3 font-black">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {budgets.length === 0 ? (
                <tr><td className="px-4 py-6 text-[#76677d]" colSpan={5}>Nenhum orçamento cadastrado para {month}.</td></tr>
              ) : budgets.map((budget: FinanceBudget) => (
                <tr key={budget.id} className="border-t border-[#eadfec]">
                  <td className="px-4 py-3 font-semibold">{budget.category?.name ?? 'Geral'}</td>
                  <td className="px-4 py-3">{money(budget.limitAmount)}</td>
                  <td className="px-4 py-3">{money(budget.spentAmount)}</td>
                  <td className="px-4 py-3">{money(budget.remainingAmount)}</td>
                  <td className="px-4 py-3">{formatBudgetStatus(budget.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card className="p-5">
        <p className="text-sm font-bold uppercase tracking-[0.18em] text-[#009688]">Movimentações do mês ({transactions.length})</p>
        {transactions.length === 0 ? (
          <p className="mt-3 text-sm text-[#76677d]">Nenhuma movimentação no período.</p>
        ) : (
          <div className="mt-4 space-y-2">
            {transactions.slice(0, 8).map((tx: FinanceTransaction) => (
              <div key={`${tx.source}-${tx.id}`} className="flex items-center justify-between rounded-2xl border border-[#eadfec] px-4 py-3 text-sm">
                <div>
                  <p className="font-semibold text-[#231529]">{tx.description ?? '—'}</p>
                  <p className="text-xs text-[#76677d]">{formatDate(tx.date)} • {tx.category?.name ?? tx.enrichment?.categoryName ?? 'Sem categoria'}</p>
                </div>
                <p className="font-black text-[#341539]">{money(tx.amount)}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

export function ConnectedTransactionsScreen() {
  const [filters, setFilters] = useState<TransactionFilterState>({
    q: '',
    institution: '',
    accountId: '',
    movementType: '',
    category: '',
    direction: '',
    dateFrom: '',
    dateTo: '',
    minAmount: '',
    maxAmount: '',
  })
  const [noteDraft, setNoteDraft] = useState<{ id: string; text: string } | null>(null)

  const { data, loading, error, refresh } = useAsyncData(async () => {
    const [transactions, accounts] = await Promise.all([
      fetchTransactions({ limit: 5000 }),
      fetchAccounts(),
    ])
    const accountById = new Map(accounts.map(account => [account.id, account]))
    return { transactions, accounts, accountById }
  }, [])

  const movementTypes = useMemo(() => {
    if (!data) return []
    const set = new Set<string>()
    for (const tx of data.transactions) {
      const account = tx.accountId ? data.accountById.get(tx.accountId) : undefined
      set.add(transactionTypeLabel(tx, account))
    }
    return [...set].sort((a, b) => a.localeCompare(b, 'pt-BR'))
  }, [data])

  const categories = useMemo(() => {
    if (!data) return []
    const set = new Set<string>()
    for (const tx of data.transactions) {
      const cat = tx.category?.name ?? tx.enrichment?.categoryName
      if (cat) set.add(cat)
    }
    return [...set].sort((a, b) => a.localeCompare(b, 'pt-BR'))
  }, [data])

  const filteredRows = useMemo(() => {
    if (!data) return []
    return filterTransactions(data.transactions, filters, data.accountById)
  }, [data, filters])

  if (loading) return <LoadingCard label="movimentações" />
  if (error) return <ErrorCard message={error} onRetry={refresh} />

  const accounts = data?.accounts ?? []
  const accountById = data?.accountById ?? new Map<string, FinanceAccount>()

  async function saveNote() {
    if (!noteDraft) return
    if (noteDraft.text.trim()) {
      await upsertTransactionAnnotation(noteDraft.id, noteDraft.text.trim())
    } else {
      await deleteTransactionAnnotation(noteDraft.id)
    }
    setNoteDraft(null)
    await refresh()
  }

  return (
    <Card className="overflow-hidden p-0">
      <FinanceFilterBar freeText={filters.q} onFreeTextChange={value => setFilters(prev => ({ ...prev, q: value }))}>
        <SearchableSelect
          label="Instituição"
          onChange={value => setFilters(prev => ({ ...prev, institution: value }))}
          options={uniqueInstitutions(accounts).map(name => ({ value: name, label: name }))}
          value={filters.institution}
        />
        <SearchableSelect
          label="Conta / cartão"
          onChange={value => setFilters(prev => ({ ...prev, accountId: value }))}
          options={accounts.map(account => ({ value: account.id, label: accountFilterLabel(account) }))}
          value={filters.accountId}
        />
        <SearchableSelect
          label="Tipo de movimentação"
          onChange={value => setFilters(prev => ({ ...prev, movementType: value }))}
          options={movementTypes.map(label => ({ value: label, label }))}
          value={filters.movementType}
        />
        <SearchableSelect
          label="Categoria"
          onChange={value => setFilters(prev => ({ ...prev, category: value }))}
          options={categories.map(label => ({ value: label, label }))}
          value={filters.category}
        />
        <label className="block text-xs font-semibold text-[#76677d]">
          Direção
          <select
            className="mt-1 w-full rounded-xl border border-[#eadfec] bg-white px-3 py-2 text-sm"
            onChange={event => setFilters(prev => ({ ...prev, direction: event.target.value as TransactionFilterState['direction'] }))}
            value={filters.direction}
          >
            <option value="">Todas</option>
            <option value="IN">Entrada</option>
            <option value="OUT">Saída</option>
          </select>
        </label>
        <label className="block text-xs font-semibold text-[#76677d]">
          De
          <Input className="mt-1" onChange={event => setFilters(prev => ({ ...prev, dateFrom: event.target.value }))} type="date" value={filters.dateFrom} />
        </label>
        <label className="block text-xs font-semibold text-[#76677d]">
          Até
          <Input className="mt-1" onChange={event => setFilters(prev => ({ ...prev, dateTo: event.target.value }))} type="date" value={filters.dateTo} />
        </label>
      </FinanceFilterBar>

      <p className="px-4 py-2 text-xs text-[#76677d]">
        Exibindo {filteredRows.length} de {data?.transactions.length ?? 0} movimentações
      </p>

      {filteredRows.length === 0 ? (
        <p className="p-6 text-sm text-[#76677d]">Nenhuma movimentação encontrada com os filtros atuais.</p>
      ) : (
        <div className="overflow-auto max-h-[520px]">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[#fffafd] text-xs uppercase tracking-[0.14em] text-[#76677d]">
              <tr>
                {['Data', 'Descrição', 'Merchant', 'Tipo', 'Categoria', 'Obs.', 'Status', 'Valor'].map(col => (
                  <th key={col} className="px-4 py-3 font-black">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredRows.map(tx => (
                <tr key={`${tx.source}-${tx.id}`} className="border-t border-[#eadfec]">
                  <td className="px-4 py-3 whitespace-nowrap">{formatDate(tx.date)}</td>
                  <td className="px-4 py-3">{tx.description ?? '—'}</td>
                  <td className="px-4 py-3">{tx.merchant ?? tx.enrichment?.merchantNormalized ?? '—'}</td>
                  <td className="px-4 py-3">
                    <TransactionTypeCell account={tx.accountId ? accountById.get(tx.accountId) : null} transaction={tx} />
                  </td>
                  <td className="px-4 py-3">{tx.category?.name ?? tx.enrichment?.categoryName ?? '—'}</td>
                  <td className="px-4 py-3">
                    {tx.note ? <span className="text-xs text-[#009688]" title={tx.note}>●</span> : null}
                    <Button
                      onClick={() => setNoteDraft({ id: tx.id, text: tx.note ?? '' })}
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      {tx.note ? 'Editar obs.' : 'Obs.'}
                    </Button>
                  </td>
                  <td className="px-4 py-3">{formatClassificationStatus(tx.enrichment?.classificationStatus)}</td>
                  <td className="px-4 py-3">
                    <TransactionAmountCell transaction={tx} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {noteDraft ? (
        <div className="border-t border-[#eadfec] bg-[#fffafd] p-4">
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#76677d]">Observação</p>
          <textarea
            className="mt-2 min-h-[80px] w-full rounded-xl border border-[#eadfec] bg-white px-3 py-2 text-sm"
            maxLength={500}
            onChange={event => setNoteDraft({ ...noteDraft, text: event.target.value })}
            value={noteDraft.text}
          />
          <div className="mt-2 flex gap-2">
            <Button onClick={() => void saveNote()} size="sm" type="button">Salvar</Button>
            <Button onClick={() => setNoteDraft(null)} size="sm" type="button" variant="secondary">Cancelar</Button>
          </div>
        </div>
      ) : null}
    </Card>
  )
}

export function ConnectedCardsScreen() {
  const [filterQ, setFilterQ] = useState('')

  const { data, loading, error, refresh } = useAsyncData(async () => {
    const [bills, accounts] = await Promise.all([fetchBills(), fetchAccounts()])
    return {
      bills,
      creditAccounts: accounts.filter(a => a.canonicalType === 'CREDIT_CARD'),
      accountNames: new Map(accounts.map(account => [account.id, formatAccountDisplayName(account)])),
    }
  }, [])

  const filteredCards = useMemo(() => {
    if (!data) return []
    return filterAccounts(data.creditAccounts, filterQ)
  }, [data, filterQ])

  if (loading) return <LoadingCard label="cartões e faturas" />
  if (error || !data) return <ErrorCard message={error ?? 'Sem dados'} onRetry={refresh} />

  const knownInvoiceTotal = data.bills.reduce((sum, bill) => sum + (bill.totalAmount ?? 0), 0)

  return (
    <div className="space-y-5">
      {data.bills.length > 0 ? (
        <Card className="p-5">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-[#76677d]">Faturas atuais conhecidas</p>
          <p className="mt-2 text-2xl font-black text-[#341539]">{money(knownInvoiceTotal)}</p>
          <p className="mt-1 text-sm text-[#76677d]">Soma apenas de faturas sincronizadas com vencimento informado.</p>
        </Card>
      ) : null}
      <Card className="overflow-hidden p-0">
        <FinanceFilterBar freeText={filterQ} onFreeTextChange={setFilterQ}>
          <SearchableSelect
            label="Instituição"
            onChange={value => setFilterQ(value)}
            options={uniqueInstitutions(data.creditAccounts).map(name => ({ value: name, label: name }))}
            value=""
          />
        </FinanceFilterBar>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {data.creditAccounts.length === 0 ? (
          <Card className="p-5 text-sm text-[#76677d]">Nenhum cartão sincronizado.</Card>
        ) : filteredCards.length === 0 ? (
          <Card className="p-5 text-sm text-[#76677d]">Nenhum cartão corresponde à busca.</Card>
        ) : filteredCards.map(card => {
          const institution =
            card.institutionName && !isInfrastructureConnectorName(card.institutionName)
              ? card.institutionName
              : null
          const masked = card.last4 ? `•••• ${card.last4}` : formatMaskedNumber(card.numberMasked)
          const brandLine = [card.cardBrand, masked].filter(Boolean).join(' · ')
          const openBalance = card.balance != null ? Math.abs(card.balance) : null
          return (
            <Card key={card.id} className="p-5">
              {institution ? (
                <p className="text-xs font-black uppercase tracking-[0.18em] text-[#83358F]">{institution}</p>
              ) : null}
              <h3 className="mt-2 text-xl font-black text-[#231529]">{formatAccountDisplayName(card)}</h3>
              <p className="mt-1 text-sm font-semibold text-[#009688]">{formatAssetType(card.canonicalType)}</p>
              {brandLine ? <p className="mt-2 text-sm text-[#76677d]">{brandLine}</p> : null}
              {card.responsibleLabel ? (
                <p className="mt-1 text-xs text-[#76677d]">Responsável: {card.responsibleLabel}</p>
              ) : null}
              <div className="mt-4 space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#76677d]">Limite total</span>
                  <span className="font-bold text-[#341539]">{money(card.creditLimit)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#76677d]">Limite disponível</span>
                  <span className="font-bold text-[#341539]">{money(card.availableCreditLimit)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#76677d]">Valor utilizado</span>
                  <span className="font-bold text-[#341539]">{openBalance != null ? money(openBalance) : '—'}</span>
                </div>
              </div>
              <p className="mt-3 text-xs text-[#76677d]">
                {data.bills.some(bill => bill.accountId === card.id)
                  ? 'Consulte a tabela abaixo para fatura e vencimento deste cartão.'
                  : 'Fatura não disponível — exibindo apenas dados seguros do cartão.'}
              </p>
              <AssetPreferenceActions account={card} onUpdated={() => void refresh()} />
            </Card>
          )
        })}
      </div>
      <Card className="overflow-hidden p-0">
        <div className="overflow-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[#fffafd] text-xs uppercase tracking-[0.14em] text-[#76677d]">
              <tr>
                {['Vencimento', 'Cartão', 'Total da fatura', 'Pagamento mínimo'].map(col => (
                  <th key={col} className="px-4 py-3 font-black">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.bills.length === 0 ? (
                <tr><td className="px-4 py-6 text-[#76677d]" colSpan={4}>Nenhuma fatura sincronizada.</td></tr>
              ) : data.bills.map((bill: FinanceBill) => (
                <tr key={bill.id} className="border-t border-[#eadfec]">
                  <td className="px-4 py-3">{bill.dueDate ? formatDate(bill.dueDate) : '—'}</td>
                  <td className="px-4 py-3">{data.accountNames.get(bill.accountId) ?? 'Cartão'}</td>
                  <td className="px-4 py-3 font-bold">{money(bill.totalAmount)}</td>
                  <td className="px-4 py-3">{money(bill.minimumPayment)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

export function ConnectedIntegrationsScreen() {
  const [connectToken, setConnectToken] = useState<string | null>(null)
  const [widgetOpen, setWidgetOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [existingItemId, setExistingItemId] = useState('')
  const [onboardingState, setOnboardingState] = useState<'idle' | 'validating' | 'syncing' | 'done' | 'error'>('idle')

  const { data, loading, error, refresh } = useAsyncData(() => fetchIntegrations(), [])

  async function openConnect() {
    setActionError(null)
    setActionSuccess(null)
    try {
      const response = await apiRequest<{ accessToken: string }>('/api/connect-token', { method: 'POST', body: JSON.stringify({}) })
      setConnectToken(response.accessToken)
      setWidgetOpen(true)
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Erro ao abrir conexão Pluggy.')
    }
  }

  async function handleConnectSuccess(itemData: unknown) {
    const itemId = (itemData as { item?: { id?: string } })?.item?.id
    if (!itemId) {
      setActionError('Não foi possível concluir a conexão.')
      return
    }
    setOnboardingState('syncing')
    try {
      await apiRequest('/api/pluggy/items', { method: 'POST', body: JSON.stringify({ itemId }) })
      setWidgetOpen(false)
      setActionSuccess('Conexão adicionada.')
      setOnboardingState('done')
      await refresh()
    } catch (caught) {
      setOnboardingState('error')
      setActionError(caught instanceof Error ? caught.message : 'Falha temporária ao sincronizar.')
    }
  }

  async function addExistingItem() {
    const trimmed = existingItemId.trim()
    if (!trimmed) {
      setActionError('Informe o ID da conexão Pluggy.')
      return
    }
    setActionError(null)
    setActionSuccess(null)
    setOnboardingState('validating')
    try {
      const result = await addExistingConnection(trimmed)
      setOnboardingState(result.success ? 'done' : 'error')
      setActionSuccess(result.message || onboardingMessage(result.outcome))
      setExistingItemId('')
      await refresh()
    } catch (caught) {
      setOnboardingState('error')
      const message = caught instanceof Error ? caught.message : 'Não foi possível acessar essa conexão.'
      setActionError(message)
    }
  }

  async function syncNow() {
    setSyncing(true)
    setActionError(null)
    setActionSuccess(null)
    try {
      await triggerSync()
      setActionSuccess('Sincronização iniciada.')
      await refresh()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Falha temporária ao sincronizar.')
    } finally {
      setSyncing(false)
    }
  }

  if (loading) return <LoadingCard label="integrações" />
  if (error || !data) return <ErrorCard message={error ?? 'Sem dados'} onRetry={refresh} />

  return (
    <div className="space-y-5">
      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void openConnect()} type="button"><Plug className="h-4 w-4" />Conectar nova conta</Button>
          <Button disabled={syncing} onClick={() => void syncNow()} type="button" variant="secondary">
            <RefreshCw className="h-4 w-4" />{syncing ? 'Sincronizando...' : 'Atualizar agora'}
          </Button>
          <p className="text-sm text-[#76677d]">
            Sync automático: {data.sync.enabled ? `a cada ${data.sync.intervalMinutes} min` : 'desligado'}
            {data.sync.latestRun ? ` • ${formatSyncStatus(data.sync.latestRun.status)}` : ''}
          </p>
        </div>
        <div className="rounded-2xl border border-[#eadfec] bg-[#fffafd] p-4">
          <p className="text-sm font-bold text-[#341539]">Adicionar conexão existente</p>
          <p className="mt-1 text-xs text-[#76677d]">Conecte o banco no portal Pluggy e cole aqui o ID da conexão.</p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row">
            <Input
              aria-label="ID da conexão Pluggy"
              onChange={event => setExistingItemId(event.target.value)}
              placeholder="ID da conexão Pluggy"
              value={existingItemId}
            />
            <Button disabled={onboardingState === 'validating' || onboardingState === 'syncing'} onClick={() => void addExistingItem()} type="button">
              Adicionar conexão
            </Button>
          </div>
          {onboardingState !== 'idle' ? (
            <p className="mt-2 text-xs font-semibold text-[#009688]">{onboardingStateLabel(onboardingState)}</p>
          ) : null}
        </div>
      </Card>
      {actionError ? <ErrorCard message={actionError} /> : null}
      {actionSuccess ? (
        <Card className="border-emerald-100 bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">{actionSuccess}</Card>
      ) : null}
      {connectToken && widgetOpen ? (
        <PluggyConnect
          connectToken={connectToken}
          includeSandbox
          onClose={() => setWidgetOpen(false)}
          onError={caught => {
            setWidgetOpen(false)
            setActionError(caught instanceof Error ? caught.message : 'Erro no widget Pluggy.')
          }}
          onSuccess={itemData => void handleConnectSuccess(itemData)}
        />
      ) : null}
      <div className="space-y-4">
        {data.items.length === 0 ? (
          <Card className="p-5 text-sm text-[#76677d]">Nenhuma instituição conectada.</Card>
        ) : data.items.map(item => (
          <IntegrationItemCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  )
}

function resolveIntegrationInstitutionLabel(item: FinanceIntegrationItem): string {
  const assets = [
    ...item.groups.cashAccounts,
    ...item.groups.creditCards,
    ...item.groups.investments,
    ...item.groups.other,
  ]
  for (const asset of assets) {
    const name = asset.institutionName?.trim()
    if (name && !isInfrastructureConnectorName(name)) return name
  }
  const connector = item.connectorName?.trim()
  if (connector && !isInfrastructureConnectorName(connector)) return connector
  return 'Instituição conectada'
}

function IntegrationItemCard({ item }: { item: FinanceIntegrationItem }) {
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Landmark className="h-6 w-6 text-[#83358F]" />
          <h3 className="mt-4 text-xl font-black text-[#231529]">{resolveIntegrationInstitutionLabel(item)}</h3>
          <p className="mt-1 text-sm font-semibold text-[#009688]">{formatItemStatus(item.status)}</p>
          <p className="mt-2 text-xs text-[#76677d]">Ref. {item.idMasked}</p>
        </div>
        <div className="text-right text-sm text-[#76677d]">
          <p>Última sync: {item.lastSyncedAt ? formatDate(item.lastSyncedAt) : '—'}</p>
        </div>
      </div>
      {item.errorSummary ? <p className="mt-3 text-sm font-semibold text-rose-700">Erro na sincronização. Tente reconectar.</p> : null}
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <AssetGroup title="Contas" assets={item.groups.cashAccounts} valueLabel="Saldo" />
        <AssetGroup title="Cartões" assets={item.groups.creditCards} valueLabel="Fatura em aberto" showLimit />
        <AssetGroup title="Investimentos" assets={item.groups.investments} valueLabel="Valor" />
        {item.groups.other.length > 0 ? <AssetGroup title="Outros" assets={item.groups.other} valueLabel="Saldo" /> : null}
      </div>
    </Card>
  )
}

function AssetGroup({
  title,
  assets,
  valueLabel,
  showLimit = false,
}: {
  title: string
  assets: FinanceIntegrationItem['groups']['cashAccounts']
  valueLabel: string
  showLimit?: boolean
}) {
  if (assets.length === 0) return null
  return (
    <div className="rounded-2xl border border-[#eadfec] bg-white/70 p-4">
      <p className="text-xs font-black uppercase tracking-[0.14em] text-[#76677d]">{title}</p>
      <div className="mt-3 space-y-2">
        {assets.map(asset => (
          <div key={asset.id} className="flex items-start justify-between gap-3 text-sm">
            <div>
              <p className="font-semibold text-[#231529]">{formatAccountDisplayName(asset)}</p>
              <p className="text-xs text-[#76677d]">{formatAssetType(asset.canonicalType)}</p>
            </div>
            <div className="text-right">
              <p className="font-bold text-[#341539]">{money(showLimit ? Math.abs(asset.balance ?? 0) : asset.balance)}</p>
              {showLimit && asset.creditLimit != null ? (
                <p className="text-xs text-[#76677d]">Limite {money(asset.creditLimit)}</p>
              ) : null}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] uppercase tracking-[0.12em] text-[#76677d]">{valueLabel}</p>
    </div>
  )
}

export function useCurrentMonthLabel(monthOffset: number) {
  return useMemo(() => {
    const now = new Date()
    now.setMonth(now.getMonth() + monthOffset)
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  }, [monthOffset])
}
