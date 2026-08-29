import { AlertCircle, Landmark, Plug, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { PluggyConnect } from 'react-pluggy-connect'

import {
  fetchAccounts,
  fetchBills,
  fetchBudgets,
  fetchIntegrations,
  fetchSummary,
  fetchTransactions,
  triggerSync,
  type FinanceAccount,
  type FinanceBill,
  type FinanceBudget,
  type FinanceTransaction,
} from '../../api/finance'
import { apiRequest } from '../../lib/api'
import { useAsyncData } from '../../hooks/useAsyncData'
import { Button } from '../ui/button'
import { Card } from '../ui/card'

export const financeDemoMode = import.meta.env.VITE_FINANCE_DEMO_MODE === 'true'

function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toLocaleString('pt-BR', { currency: 'BRL', style: 'currency' })
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
      <p className="text-xs font-black uppercase tracking-[0.18em] text-[#76677d]">Fora do escopo F1</p>
      <h3 className="mt-2 text-xl font-black text-[#231529]">{title}</h3>
      <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-[#76677d]">{description}</p>
    </Card>
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
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Saldo total" value={money(summary.totalBalance)} helper="Contas bancárias (exclui cartão)" tone="blue" />
        <MetricCard label="Receitas do mês" value={money(summary.monthIncome)} helper={`Referência ${summary.month}`} tone="green" />
        <MetricCard label="Despesas do mês" value={money(summary.monthExpense)} helper="Pluggy + manual" tone="red" />
        <MetricCard label="Resultado do mês" value={money(summary.monthResult)} helper={summary.lastSync ? `Último sync ${formatDate(summary.lastSync)}` : 'Aguardando sync'} tone={(summary.monthResult ?? 0) < 0 ? 'red' : 'green'} />
      </div>
      <Card className="p-5">
        <p className="text-sm font-bold uppercase tracking-[0.18em] text-[#009688]">Contas conectadas</p>
        {accounts.length === 0 ? (
          <p className="mt-4 text-sm text-[#76677d]">Nenhuma conta sincronizada ainda. Conecte um banco em Contas e Integrações.</p>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {accounts.map(account => (
              <div key={account.id} className="rounded-2xl border border-[#eadfec] bg-white/75 px-4 py-3">
                <p className="text-xs font-black uppercase tracking-[0.14em] text-[#76677d]">{account.type ?? 'conta'}</p>
                <p className="font-black text-[#231529]">{account.name ?? account.id}</p>
                <p className="mt-1 text-lg font-black text-[#341539]">{money(account.balance)}</p>
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
                  <td className="px-4 py-3">{budget.status}</td>
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
  const { data, loading, error, refresh } = useAsyncData(() => fetchTransactions({ limit: 200 }), [])

  if (loading) return <LoadingCard label="movimentações" />
  if (error) return <ErrorCard message={error} onRetry={refresh} />

  const rows = data ?? []
  return (
    <Card className="overflow-hidden p-0">
      {rows.length === 0 ? (
        <p className="p-6 text-sm text-[#76677d]">Nenhuma movimentação sincronizada ainda.</p>
      ) : (
        <div className="overflow-auto max-h-[520px]">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[#fffafd] text-xs uppercase tracking-[0.14em] text-[#76677d]">
              <tr>
                {['Data', 'Descrição', 'Merchant', 'Tipo', 'Categoria', 'Status', 'Valor'].map(col => (
                  <th key={col} className="px-4 py-3 font-black">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(tx => (
                <tr key={`${tx.source}-${tx.id}`} className="border-t border-[#eadfec]">
                  <td className="px-4 py-3 whitespace-nowrap">{formatDate(tx.date)}</td>
                  <td className="px-4 py-3">{tx.description ?? '—'}</td>
                  <td className="px-4 py-3">{tx.merchant ?? tx.enrichment?.merchantNormalized ?? '—'}</td>
                  <td className="px-4 py-3">{tx.enrichment?.canonicalType ?? tx.type ?? '—'}</td>
                  <td className="px-4 py-3">{tx.category?.name ?? tx.enrichment?.categoryName ?? '—'}</td>
                  <td className="px-4 py-3">{tx.enrichment?.classificationStatus ?? '—'}</td>
                  <td className="px-4 py-3 font-bold">{money(tx.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

export function ConnectedCardsScreen() {
  const { data, loading, error, refresh } = useAsyncData(async () => {
    const [bills, accounts] = await Promise.all([fetchBills(), fetchAccounts()])
    return { bills, creditAccounts: accounts.filter(a => a.type === 'CREDIT') }
  }, [])

  if (loading) return <LoadingCard label="cartões e faturas" />
  if (error || !data) return <ErrorCard message={error ?? 'Sem dados'} onRetry={refresh} />

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        {data.creditAccounts.length === 0 ? (
          <Card className="p-5 text-sm text-[#76677d]">Nenhum cartão sincronizado.</Card>
        ) : data.creditAccounts.map(card => (
          <Card key={card.id} className="p-5">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-[#83358F]">Cartão</p>
            <h3 className="mt-2 text-xl font-black text-[#231529]">{card.name ?? card.id}</h3>
            <p className="mt-3 text-sm text-[#76677d]">Limite {money(card.creditLimit)}</p>
            <p className="mt-2 text-3xl font-black text-[#341539]">{money(card.balance)}</p>
          </Card>
        ))}
      </div>
      <Card className="overflow-hidden p-0">
        <div className="overflow-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[#fffafd] text-xs uppercase tracking-[0.14em] text-[#76677d]">
              <tr>
                {['Vencimento', 'Conta', 'Total', 'Mínimo'].map(col => (
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
                  <td className="px-4 py-3">{bill.accountId}</td>
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
  const [syncing, setSyncing] = useState(false)

  const { data, loading, error, refresh } = useAsyncData(() => fetchIntegrations(), [])

  async function openConnect() {
    setActionError(null)
    try {
      const response = await apiRequest<{ accessToken: string }>('/api/connect-token', { method: 'POST', body: JSON.stringify({}) })
      setConnectToken(response.accessToken)
      setWidgetOpen(true)
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Erro ao abrir Pluggy Connect.')
    }
  }

  async function handleConnectSuccess(itemData: unknown) {
    const itemId = (itemData as { item?: { id?: string } })?.item?.id
    if (!itemId) {
      setActionError('Connect retornou sem item.id')
      return
    }
    await apiRequest('/api/pluggy/items', { method: 'POST', body: JSON.stringify({ itemId }) })
    setWidgetOpen(false)
    await refresh()
  }

  async function syncNow() {
    setSyncing(true)
    setActionError(null)
    try {
      await triggerSync()
      await refresh()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Falha ao sincronizar.')
    } finally {
      setSyncing(false)
    }
  }

  if (loading) return <LoadingCard label="integrações" />
  if (error || !data) return <ErrorCard message={error ?? 'Sem dados'} onRetry={refresh} />

  return (
    <div className="space-y-5">
      <Card className="flex flex-wrap items-center gap-3 p-5">
        <Button onClick={() => void openConnect()} type="button"><Plug className="h-4 w-4" />Conectar conta</Button>
        <Button disabled={syncing} onClick={() => void syncNow()} type="button" variant="secondary"><RefreshCw className="h-4 w-4" />Atualizar agora</Button>
        <p className="text-sm text-[#76677d]">Sync automático: {data.sync.enabled ? `a cada ${data.sync.intervalMinutes} min` : 'desligado'}</p>
      </Card>
      {actionError ? <ErrorCard message={actionError} /> : null}
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
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.items.length === 0 ? (
          <Card className="p-5 text-sm text-[#76677d]">Nenhum Item Pluggy conectado.</Card>
        ) : data.items.map(item => (
          <Card key={item.id} className="p-5">
            <Landmark className="h-6 w-6 text-[#83358F]" />
            <h3 className="mt-4 text-xl font-black text-[#231529]">{item.connectorName ?? item.id}</h3>
            <p className="mt-1 text-sm font-semibold text-[#009688]">{item.status}</p>
            <p className="mt-4 text-sm text-[#76677d]">Contas: {item.accountCount}</p>
            <p className="text-sm text-[#76677d]">Última sync: {item.lastSyncedAt ? formatDate(item.lastSyncedAt) : '—'}</p>
            {item.errorSummary ? <p className="mt-2 text-sm font-semibold text-rose-700">{item.errorSummary}</p> : null}
          </Card>
        ))}
      </div>
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
