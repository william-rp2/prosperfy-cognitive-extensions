import {
  AlertTriangle,
  ArrowLeftRight,
  BarChart3,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  ClipboardList,
  CreditCard,
  FileText,
  Goal,
  Home,
  Landmark,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Menu,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  PiggyBank,
  Plug,
  ReceiptText,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  UserRound,
  WalletCards,
  X,
  type LucideIcon,
} from 'lucide-react'
import React, { FormEvent, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

import { Button } from './components/ui/button'
import { Card } from './components/ui/card'
import { Input } from './components/ui/input'
import { PluggyPocPage } from './components/PluggyPocPage'
import {
  ConnectedCardsScreen,
  ConnectedDashboardScreen,
  ConnectedIntegrationsScreen,
  ConnectedMonthlyScreen,
  ConnectedTransactionsScreen,
  DeferredEmptyScreen,
  financeDemoMode,
  useCurrentMonthLabel,
} from './components/finance/ConnectedScreens'
import {
  cardBills,
  cardPurchases,
  categories,
  decisions,
  documents,
  financeSeedMetadata,
  financialDestinations,
  institutionBalances,
  integrations,
  loans,
  metrics,
  monthlyItems,
  receivables,
  reserves,
  debtsPayable,
  seedFinanceData,
  transactions,
  type Metric,
} from './data/finance-seed'
import { authenticate, getCurrentSession, getStoredAuthRecord, logout, resetLocalCredentials, type AuthSession } from './lib/auth'

type ScreenId =
  | 'dashboard'
  | 'monthly'
  | 'decisions'
  | 'reserves'
  | 'transactions'
  | 'debts'
  | 'cards'
  | 'documents'
  | 'integrations'
  | 'settings'

type UiMode = 'normal' | 'loading' | 'empty' | 'error' | 'success'

interface NavItem {
  id: ScreenId
  label: string
  icon: LucideIcon
  subtitle: string
}

const navItems: NavItem[] = [
  { id: 'monthly', label: 'Visão Mensal', icon: CalendarDays, subtitle: 'Planejamento operacional' },
  { id: 'dashboard', label: 'Dashboard Geral', icon: LayoutDashboard, subtitle: 'Resumo executivo' },
  { id: 'decisions', label: 'Central de Decisões', icon: ClipboardList, subtitle: 'Autorizações pendentes' },
  { id: 'reserves', label: 'Reservas e Metas', icon: Goal, subtitle: 'Finalidade do dinheiro' },
  { id: 'transactions', label: 'Movimentações', icon: ArrowLeftRight, subtitle: 'Lista neutra' },
  { id: 'debts', label: 'Dívidas e Empréstimos', icon: PiggyBank, subtitle: 'Receber e pagar' },
  { id: 'cards', label: 'Cartões e Faturas', icon: CreditCard, subtitle: 'Compromissos no cartão' },
  { id: 'documents', label: 'Notas e Documentos', icon: ReceiptText, subtitle: 'OCR e rateio' },
  { id: 'integrations', label: 'Contas e Integrações', icon: Plug, subtitle: 'Bancos e canais' },
  { id: 'settings', label: 'Configurações do Sistema', icon: Settings, subtitle: 'Regras e segurança' },
]

const monthNames = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

function money(value: number) {
  return value.toLocaleString('pt-BR', { currency: 'BRL', style: 'currency' })
}

function toneClass(tone: Metric['tone']) {
  if (tone === 'green') return 'bg-emerald-50 text-emerald-700 border-emerald-100'
  if (tone === 'yellow') return 'bg-amber-50 text-amber-700 border-amber-100'
  if (tone === 'red') return 'bg-rose-50 text-rose-700 border-rose-100'
  if (tone === 'blue') return 'bg-sky-50 text-sky-700 border-sky-100'
  if (tone === 'purple') return 'bg-purple-50 text-purple-700 border-purple-100'
  return 'bg-[#fffafd] text-[#341539] border-[#eadfec]'
}

function ProsperfyMark({ dark = false, collapsed = false }: { dark?: boolean; collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg font-black shadow-lg ${dark ? 'bg-white text-[#341539] shadow-black/20' : 'bg-[#341539] text-white shadow-[#341539]/25'}`}>
        P
      </div>
      {!collapsed ? (
        <div>
          <p className={`text-sm font-black uppercase tracking-[0.28em] ${dark ? 'text-white' : 'text-[#341539]'}`}>Prosperfy</p>
          <p className={`text-xs font-medium ${dark ? 'text-white/62' : 'text-[#76677d]'}`}>Financeiro Pessoal</p>
        </div>
      ) : null}
    </div>
  )
}

function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasLocalUser = Boolean(getStoredAuthRecord())

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsLoading(true)

    try {
      const session = await authenticate(username, password)
      onAuthenticated(session)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Não foi possível entrar.')
    } finally {
      setIsLoading(false)
    }
  }

  function handleReset() {
    resetLocalCredentials()
    setUsername('')
    setPassword('')
    setError('Credenciais locais removidas. O próximo login criará um novo usuário local.')
  }

  return (
    <main className="grid min-h-screen px-4 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(420px,520px)] lg:px-8">
      <section className="hidden min-h-[calc(100vh-3rem)] items-center justify-center rounded-[2.5rem] bg-[#341539] p-10 text-white shadow-2xl shadow-[#341539]/25 lg:flex">
        <div className="max-w-2xl">
          <div className="mb-8 inline-flex rounded-full border border-white/15 bg-white/10 px-4 py-2 text-sm font-semibold text-white/88 backdrop-blur">
            Protótipo navegável • dados fictícios
          </div>
          <h1 className="text-5xl font-black leading-tight tracking-[-0.04em] xl:text-6xl">
            Controle financeiro familiar com Hermes no centro das decisões.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-8 text-white/72">
            Planeje destinos, acompanhe reservas, trate notas e aprove remanejamentos com segurança antes de qualquer automação real.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {['Responsivo', 'Autorizado', 'Sem dados reais'].map(item => (
              <div key={item} className="rounded-3xl border border-white/12 bg-white/8 p-5 backdrop-blur">
                <ShieldCheck className="mb-3 h-5 w-5 text-[#61d5e4]" />
                <p className="font-bold">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="flex min-h-[calc(100vh-3rem)] items-center justify-center lg:pl-8">
        <Card className="glass-panel w-full max-w-md p-7 sm:p-9">
          <ProsperfyMark />
          <div className="mt-10">
            <p className="text-sm font-bold uppercase tracking-[0.22em] text-[#83358F]">Acesso administrativo</p>
            <h2 className="mt-3 text-3xl font-black tracking-[-0.04em] text-[#231529]">
              {hasLocalUser ? 'Entre para continuar' : 'Crie o primeiro acesso'}
            </h2>
            <p className="mt-3 text-sm leading-6 text-[#76677d]">
              {hasLocalUser
                ? 'As credenciais são validadas contra o registro criptografado neste navegador.'
                : 'Neste protótipo, o primeiro login cria um usuário local criptografado com AES-GCM.'}
            </p>
          </div>

          <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
            <label className="block space-y-2">
              <span className="text-sm font-semibold text-[#341539]">Usuário</span>
              <Input autoComplete="username" onChange={event => setUsername(event.target.value)} placeholder="will@prosperfy" value={username} />
            </label>
            <label className="block space-y-2">
              <span className="text-sm font-semibold text-[#341539]">Senha</span>
              <Input autoComplete={hasLocalUser ? 'current-password' : 'new-password'} onChange={event => setPassword(event.target.value)} placeholder="••••••••" type="password" value={password} />
            </label>

            {error ? <div className="rounded-2xl border border-[#f3d0d7] bg-[#fff4f6] px-4 py-3 text-sm font-medium text-[#8f1d39]">{error}</div> : null}

            <Button className="w-full" disabled={isLoading} size="lg" type="submit">
              <LockKeyhole className="h-4 w-4" />
              {isLoading ? 'Validando...' : hasLocalUser ? 'Entrar' : 'Criar acesso seguro'}
            </Button>
          </form>

          <div className="mt-6 flex flex-col gap-3 text-xs text-[#76677d] sm:flex-row sm:items-center sm:justify-between">
            <span>PBKDF2 + AES-GCM no navegador.</span>
            {hasLocalUser ? (
              <button className="font-semibold text-[#83358F] hover:text-[#341539]" onClick={handleReset} type="button">
                resetar usuário local
              </button>
            ) : null}
          </div>
        </Card>
      </section>
    </main>
  )
}

function Sidebar({ activeScreen, collapsed, isOpen, onClose, onSelect, onToggleCollapsed }: { activeScreen: ScreenId; collapsed: boolean; isOpen: boolean; onClose: () => void; onSelect: (screen: ScreenId) => void; onToggleCollapsed: () => void }) {
  return (
    <>
      <button aria-label="Fechar navegação" className={`fixed inset-0 z-30 bg-[#140818]/40 backdrop-blur-sm transition lg:hidden ${isOpen ? 'opacity-100' : 'pointer-events-none opacity-0'}`} onClick={onClose} type="button" />
      <aside className={`fixed inset-y-0 left-0 z-40 flex flex-col border-r border-white/10 bg-[#341539] p-4 text-white shadow-2xl shadow-[#341539]/30 transition-all duration-300 lg:static lg:translate-x-0 ${collapsed ? 'lg:w-20' : 'lg:w-80'} ${isOpen ? 'w-80 translate-x-0' : 'w-80 -translate-x-full'}`}>
        <div className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between gap-3'}`}>
          {!collapsed && <ProsperfyMark collapsed dark />}
          <div className="flex items-center gap-1">
            <Button aria-label={collapsed ? 'Expandir sidebar' : 'Recolher sidebar'} className="text-white hover:bg-white/10" onClick={onToggleCollapsed} size="icon" type="button" variant="ghost">
              {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
            </Button>
            {!collapsed && <Button className="text-white hover:bg-white/10 lg:hidden" onClick={onClose} size="icon" type="button" variant="ghost">
              <X className="h-5 w-5" />
            </Button>}
          </div>
        </div>

        <nav aria-label="Navegação principal" className="mt-8 space-y-1 overflow-y-auto pr-1">
          {navItems.map(item => (
            <button
              key={item.id}
              className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm font-semibold transition ${activeScreen === item.id ? 'bg-white text-[#341539] shadow-lg shadow-black/10' : 'text-white/74 hover:bg-white/10 hover:text-white'}`}
              onClick={() => {
                onSelect(item.id)
                onClose()
              }}
              title={item.label}
              type="button"
            >
              <item.icon className="h-5 w-5 shrink-0" />
              {!collapsed ? (
                <span className="min-w-0">
                  <span className="block truncate">{item.label}</span>
                  <span className="block truncate text-xs font-medium opacity-62">{item.subtitle}</span>
                </span>
              ) : null}
            </button>
          ))}
        </nav>

        {!collapsed && financeDemoMode ? (
          <div className="mt-auto rounded-3xl border border-white/10 bg-white/8 p-4 text-sm text-white/72">
            <p className="font-bold text-white">Modo demonstração</p>
            <p className="mt-2 text-xs leading-5 text-white/70">Dados fictícios para protótipo visual.</p>
            <p className="mt-2 text-xs leading-5 text-white/70">Seed: {financeSeedMetadata.version}</p>
          </div>
        ) : null}
      </aside>
    </>
  )
}

function Header({ activeItem, displayName, mode, onLogout, onMenu, onModeChange }: { activeItem: NavItem; displayName: string; mode: UiMode; onLogout: () => void; onMenu: () => void; onModeChange: (mode: UiMode) => void }) {
  return (
    <header className="sticky top-0 z-20 border-b border-[#eadfec]/80 bg-[#fffafd]/88 px-4 py-4 backdrop-blur-xl sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Button className="lg:hidden" onClick={onMenu} size="icon" type="button" variant="secondary">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-[#83358F]">{financeDemoMode ? 'Protótipo navegável' : 'Finance V2'}</p>
            <h1 className="truncate text-xl font-black tracking-[-0.03em] text-[#231529] sm:text-2xl">{activeItem.label}</h1>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-3">
          <select aria-label="Simular estado da tela" className="h-11 rounded-2xl border border-[#eadfec] bg-white/80 px-3 text-sm font-semibold text-[#341539] shadow-sm" onChange={event => onModeChange(event.target.value as UiMode)} value={mode}>
            <option value="normal">Estado normal</option>
            <option value="loading">Carregando</option>
            <option value="empty">Vazio</option>
            <option value="error">Erro</option>
            <option value="success">Sucesso</option>
          </select>
          <div className="hidden items-center gap-2 rounded-2xl border border-sky-100 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-700 md:flex">
            <RefreshCw className="h-4 w-4" /> Última sync 00:12
          </div>
          <Button aria-label="Notificações" size="icon" type="button" variant="secondary">
            <Bell className="h-5 w-5" />
          </Button>
          <Button aria-label="Abrir Hermes" type="button" variant="secondary">
            <Sparkles className="h-4 w-4" /> <span className="hidden sm:inline">Hermes</span>
          </Button>
          <div className="hidden items-center gap-3 rounded-2xl border border-[#eadfec] bg-white/80 px-3 py-2 shadow-sm sm:flex">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#83358F]/10 text-[#83358F]">
              <UserRound className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-bold text-[#231529]">{displayName}</p>
              <p className="text-xs text-[#76677d]">Administrador</p>
            </div>
          </div>
          <Button aria-label="Sair" onClick={onLogout} size="icon" type="button" variant="secondary">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </header>
  )
}

function StateBanner({ mode }: { mode: UiMode }) {
  if (mode === 'normal') return null
  const content = {
    loading: ['Carregando dados fictícios', 'Skeletons representam o estado de espera antes da sincronização.'],
    empty: ['Estado vazio', 'Este cenário simula ausência de dados para filtros ou mês selecionado.'],
    error: ['Erro simulado', 'Falha fictícia de integração. Nenhuma operação real foi executada.'],
    success: ['Sucesso simulado', 'Ação demonstrativa concluída com registro de autoria e histórico.'],
  }[mode]
  const tone = mode === 'error' ? 'border-rose-200 bg-rose-50 text-rose-800' : mode === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-sky-200 bg-sky-50 text-sky-800'
  return (
    <div className={`mb-5 rounded-3xl border px-5 py-4 text-sm font-semibold ${tone}`}>
      <p className="font-black">{content[0]}</p>
      <p className="mt-1 font-medium opacity-80">{content[1]}</p>
    </div>
  )
}

function MetricGrid() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map(metric => (
        <Card key={metric.label} className={`p-5 ${toneClass(metric.tone)}`}>
          <p className="text-xs font-black uppercase tracking-[0.18em] opacity-70">{metric.label}</p>
          <p className="mt-3 text-3xl font-black tracking-[-0.04em]">{metric.value}</p>
          <p className="mt-2 text-sm font-medium opacity-78">{metric.helper}</p>
        </Card>
      ))}
    </div>
  )
}

function HermesPanel({ title = 'Análise do Hermes' }: { title?: string }) {
  return (
    <Card className="border-sky-100 bg-sky-50/80 p-5 text-sky-900">
      <div className="flex items-start gap-3">
        <div className="rounded-2xl bg-sky-100 p-3 text-sky-700">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <p className="font-black">{title}</p>
          <p className="mt-2 text-sm leading-6 text-sky-800/82">
            William, há um gasto não previsto de R$ 600. Há R$ 200 restantes em Extras e R$ 150 economizados em Gasolina. Posso preparar a cobertura parcial e manter R$ 250 como déficit a compensar — somente se você autorizar.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" type="button">Autorizar simulação</Button>
            <Button size="sm" type="button" variant="secondary">Personalizar</Button>
          </div>
        </div>
      </div>
    </Card>
  )
}

function DashboardScreen() {
  if (financeDemoMode) {
    return (
      <div className="space-y-6">
        <MetricGrid />
        <div className="grid gap-6 xl:grid-cols-[1.4fr_0.8fr]">
          <Card>
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-[#009688]">Evolução resumida</p>
            <div className="mt-6 grid h-56 grid-cols-6 items-end gap-3">
              {[44, 60, 52, 70, 64, 78].map((height, index) => (
                <div key={index} className="rounded-t-3xl bg-gradient-to-t from-[#341539] to-[#00bcd4]" style={{ height: `${height}%` }} />
              ))}
            </div>
            <p className="mt-4 text-sm text-[#76677d]">Gráfico fictício de saldo livre e reservas nos últimos 6 meses.</p>
          </Card>
          <div className="space-y-4">
            <HermesPanel />
            <Card>
              <p className="font-black text-[#231529]">Próximos compromissos</p>
              {['Fatura Nubank — R$ 1.420', 'Parcela empréstimo — R$ 800', 'Material escolar — R$ 300'].map(item => (
                <div key={item} className="mt-3 rounded-2xl border border-[#eadfec] bg-white/70 px-4 py-3 text-sm font-semibold text-[#4b1f52]">{item}</div>
              ))}
            </Card>
          </div>
        </div>
      </div>
    )
  }
  return <ConnectedDashboardScreen />
}

function CardStat({ label, value, helper, tone }: { label: string; value: string; helper: string; tone?: string }) {
  const cls = tone === 'green' ? 'text-emerald-700 border-emerald-100 bg-emerald-50' : tone === 'red' ? 'text-rose-700 border-rose-100 bg-rose-50' : tone === 'yellow' ? 'text-amber-700 border-amber-100 bg-amber-50' : tone === 'blue' ? 'text-sky-700 border-sky-100 bg-sky-50' : tone === 'purple' ? 'text-purple-700 border-purple-100 bg-purple-50' : 'text-[#341539] border-[#eadfec] bg-white'
  return (
    <Card className={`p-3 shrink-0 min-w-[13rem] ${cls}`}>
      <p className="text-[9px] font-black uppercase tracking-[0.14em] opacity-70">{label}</p>
      <p className="mt-0.5 text-lg font-black tracking-[-0.04em]">{value}</p>
      <p className="mt-0.5 text-[10px] font-medium opacity-75 truncate">{helper}</p>
    </Card>
  )
}

function MonthlyScreen({ monthOffset, setMonthOffset }: { monthOffset: number; setMonthOffset: (n: number) => void }) {
  const liveMonth = useCurrentMonthLabel(monthOffset)
  if (!financeDemoMode) return <ConnectedMonthlyScreen month={liveMonth} />

  const [categoryFilter, setCategoryFilter] = useState('Todas')
  const [statusFilter, setStatusFilter] = useState('Todos')
  const [personFilter, setPersonFilter] = useState('Todos')
  const [query, setQuery] = useState('')
  const [reservesOpen, setReservesOpen] = useState(false)

  const now = new Date(2026, 7 + monthOffset, 1)
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const currentMonthLabel = `${monthNames[now.getMonth()]}/${now.getFullYear()}`

  const monthItems = monthlyItems.filter(item => item.month === currentMonth)

  const categorySet = ['Todas', ...Array.from(new Set(monthItems.map(item => item.category)))]
  const statusSet = ['Todos', ...Array.from(new Set(monthItems.map(item => item.status)))]
  const peopleSet = ['Todos', ...Array.from(new Set(monthItems.map(item => item.person)))]

  const filteredItems = monthItems.filter(item => {
    const matchesCategory = categoryFilter === 'Todas' || item.category === categoryFilter
    const matchesStatus = statusFilter === 'Todos' || item.status === statusFilter
    const matchesPerson = personFilter === 'Todos' || item.person === personFilter
    const searchable = `${item.description} ${item.category} ${item.destination} ${item.institution}`.toLowerCase()
    const matchesQuery = !query.trim() || searchable.includes(query.trim().toLowerCase())
    return matchesCategory && matchesStatus && matchesPerson && matchesQuery
  })

  const totalPlanned = monthItems.reduce((acc, item) => acc + item.planned, 0)
  const totalDebitSpent = monthItems.reduce((acc, item) => acc + item.debitSpent, 0)
  const totalCreditCharged = monthItems.reduce((acc, item) => acc + item.creditCharged, 0)
  const totalRealSpent = totalDebitSpent + totalCreditCharged
  const totalCreditSpent = monthItems.reduce((acc, item) => acc + item.creditSpent, 0)
  const totalRemaining = monthItems.reduce((acc, item) => acc + item.remaining, 0)
  const totalRemainingToPay = monthItems.reduce((acc, item) => acc + item.remainingToPay, 0)

  const liquidIncome = seedFinanceData.currentMonthIncome
  const liquidAtual = seedFinanceData.totalBalance - seedFinanceData.totalReserves
  const previstoSaldo = liquidAtual - totalPlanned
  const atualSaldo = liquidAtual - totalRealSpent
  const resultadoFinanceiro = liquidIncome - totalRealSpent

  return (
    <div className="space-y-6">

      {/* Main cards — uma linha horizontal */}
      <div className="flex gap-3 overflow-x-auto pb-1">
        <CardStat label="Valor Líquido Recebido" value={money(liquidIncome)} helper="Total de receitas do mês" tone="green" />
        <CardStat label="Valor Líquido Atual" value={money(liquidAtual)} helper={`Saldo total (${money(seedFinanceData.totalBalance)}) - reservas (${money(seedFinanceData.totalReserves)})`} tone="blue" />
        <CardStat label="Gastos Previstos" value={money(totalPlanned)} helper="Soma de todos os gastos planejados" tone="purple" />
        <CardStat label="Saldo Previsto do Mês" value={money(previstoSaldo)} helper={previstoSaldo < 0 ? 'Atenção: gastos previstos superam saldo líquido' : 'Saldo se todos os gastos forem realizados'} tone={previstoSaldo < 0 ? 'red' : 'green'} />
        <CardStat label="Saldo Atual do Mês" value={money(atualSaldo)} helper={`Realizado: débito ${money(totalDebitSpent)} + crédito debitado ${money(totalCreditCharged)}`} tone={atualSaldo < 0 ? 'red' : 'green'} />
        <CardStat label="Resultado Financeiro" value={money(resultadoFinanceiro)} helper={`Recebido ${money(liquidIncome)} - gastos reais ${money(totalRealSpent)}`} tone={resultadoFinanceiro < 0 ? 'red' : 'green'} />
      </div>

      {/* Collapsible Reservas */}
      <Card className="overflow-hidden p-0">
        <button className="flex w-full items-center justify-between p-5 text-left transition hover:bg-white/50" onClick={() => setReservesOpen(open => !open)} type="button">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.18em] text-purple-700">Reservas e informações extras</p>
            <h3 className="mt-1 text-lg font-black text-[#231529]">Saldo por banco, reservas e contas {reservesOpen ? '' : '(clique para expandir)'}</h3>
          </div>
          {reservesOpen ? <ChevronUp className="h-5 w-5 shrink-0 text-[#76677d]" /> : <ChevronDown className="h-5 w-5 shrink-0 text-[#76677d]" />}
        </button>
        {reservesOpen && (
          <div className="border-t border-[#eadfec] p-5 space-y-6">
            {/* Linha 1: Instituições */}
            <div>
              <p className="text-xs font-black uppercase tracking-[0.16em] text-[#83358F] mb-3">Saldo por instituição</p>
              <div className="flex gap-3 overflow-x-auto pb-1">
                {institutionBalances.map(inst => {
                  const tone = inst.balance < 0 ? 'text-rose-700' : inst.type === 'dinheiro' ? 'text-emerald-700' : 'text-[#341539]'
                  const bg = inst.balance < 0 ? 'border-rose-100 bg-rose-50' : 'border-[#eadfec] bg-white'
                  return (
                    <Card key={inst.name} className={`p-3 shrink-0 min-w-[10rem] ${bg}`}>
                      <p className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">{inst.type}</p>
                      <p className="mt-0.5 font-black text-sm text-[#231529]">{inst.name}</p>
                      <p className={`mt-1 text-lg font-black ${tone}`}>{money(inst.balance)}</p>
                    </Card>
                  )
                })}
              </div>
            </div>
            {/* Linha 2: Reservas */}
            <div>
              <p className="text-xs font-black uppercase tracking-[0.16em] text-purple-700 mb-3">Reservas do mês</p>
              <div className="flex gap-3 overflow-x-auto pb-1">
                {reserves.map(reserve => {
                  const pct = Math.round((reserve.current / reserve.target) * 100)
                  return (
                    <Card key={reserve.name} className="p-3 shrink-0 min-w-[13rem]">
                      <p className="text-[10px] font-black uppercase tracking-[0.14em] text-purple-700">Prioridade {reserve.priority}</p>
                      <p className="mt-0.5 font-black text-sm text-[#231529]">{reserve.name}</p>
                      <p className="mt-1 text-lg font-black text-purple-800">{money(reserve.current)}</p>
                      <p className="text-[10px] text-[#76677d]">Meta {money(reserve.target)} • {pct}%</p>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-purple-100"><div className="h-full rounded-full bg-purple-600" style={{ width: `${pct}%` }} /></div>
                    </Card>
                  )
                })}
              </div>
            </div>
            {/* Receivables - Debts */}
            <div className="grid gap-4 md:grid-cols-2">
              <Card className="p-4 border-sky-100 bg-sky-50/80">
                <p className="text-xs font-black uppercase tracking-[0.16em] text-sky-700">Saldo a receber</p>
                <p className="mt-1 text-2xl font-black text-sky-800">{receivables.reduce((acc, r) => acc + parseInt(r.remaining.replace(/[^0-9]/g, ''), 10), 0).toLocaleString('pt-BR', { currency: 'BRL', style: 'currency' })}</p>
                {receivables.map(r => (
                  <div key={r.person} className="mt-2 flex items-center justify-between text-sm">
                    <span className="font-semibold text-[#4b1f52]">{r.person}</span>
                    <span className="text-sky-700">{r.remaining}</span>
                  </div>
                ))}
                <p className="mt-3 text-[11px] font-medium text-sky-700/70">Recebimentos projetados, não disponíveis imediatamente.</p>
              </Card>
              <Card className="p-4 border-rose-100 bg-rose-50/80">
                <p className="text-xs font-black uppercase tracking-[0.16em] text-rose-700">Dívidas a pagar</p>
                <p className="mt-1 text-2xl font-black text-rose-800">{debtsPayable.reduce((acc, d) => acc + d.remaining, 0).toLocaleString('pt-BR', { currency: 'BRL', style: 'currency' })}</p>
                {debtsPayable.map(d => (
                  <div key={d.creditor} className="mt-2 flex items-center justify-between text-sm">
                    <span className="font-semibold text-[#4b1f52]">{d.creditor}</span>
                    <span className="text-rose-700">{money(d.remaining)}</span>
                  </div>
                ))}
                <p className="mt-3 text-[11px] font-medium text-rose-700/70">Compromissos com vencimento neste mês.</p>
              </Card>
            </div>
          </div>
        )}
      </Card>

      {/* Filters inline */}
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-3">
          <p className="shrink-0 text-xs font-black uppercase tracking-[0.18em] text-[#009688]">Filtros</p>
          <span className="h-5 w-px bg-[#eadfec]" />
          <Input aria-label="Buscar na tabela" onChange={event => setQuery(event.target.value)} placeholder="Buscar descrição, categoria..." value={query} className="w-48" />
          <select aria-label="Filtrar categoria" className="h-11 rounded-2xl border border-[#eadfec] bg-white px-3 text-sm font-semibold text-[#341539]" onChange={event => setCategoryFilter(event.target.value)} value={categoryFilter}>
            {categorySet.map(cat => <option key={cat}>{cat}</option>)}
          </select>
          <select aria-label="Filtrar status" className="h-11 rounded-2xl border border-[#eadfec] bg-white px-3 text-sm font-semibold text-[#341539]" onChange={event => setStatusFilter(event.target.value)} value={statusFilter}>
            {statusSet.map(st => <option key={st}>{st}</option>)}
          </select>
          <select aria-label="Filtrar pessoa" className="h-11 rounded-2xl border border-[#eadfec] bg-white px-3 text-sm font-semibold text-[#341539]" onChange={event => setPersonFilter(event.target.value)} value={personFilter}>
            {peopleSet.map(p => <option key={p}>{p}</option>)}
          </select>
        </div>
      </Card>

      {/* Planning table */}
      <DataTable
        columns={['Categoria', 'Descrição', 'Valor Previsto', 'Valor Gasto (Débito)', 'Valor Gasto (Crédito)', 'Crédito debitado', 'Valor restante', 'Valor restante p/ quitar', 'Status', 'Ações']}
        rows={filteredItems.map(item => [
          <span key={`cat-${item.id}`} className="whitespace-nowrap"><span className="font-medium text-[#83358F]">{item.category}</span></span>,
          <span key={`desc-${item.id}`} className="font-medium">{item.description}</span>,
          money(item.planned),
          item.debitSpent > 0 ? money(item.debitSpent) : '—',
          item.creditSpent > 0 ? money(item.creditSpent) : '—',
          item.creditCharged > 0 ? money(item.creditCharged) : '—',
          <span key={`rem-${item.id}`} className={item.remaining < 0 ? 'text-rose-700 font-bold' : 'text-emerald-700'}>{item.remaining >= 0 ? money(item.remaining) : `-${money(Math.abs(item.remaining))}`}</span>,
          item.remainingToPay > 0 ? money(item.remainingToPay) : '—',
          <span key={`st-${item.id}`} className={`inline-block rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
            item.status === 'Pago' || item.status === 'Classificado' ? 'bg-emerald-100 text-emerald-800' :
            item.status === 'Acima do planejado' ? 'bg-amber-100 text-amber-800' :
            item.status === 'Sem destino' ? 'bg-rose-100 text-rose-800' :
            item.status === 'Pendente' ? 'bg-sky-100 text-sky-800' :
            'bg-purple-100 text-purple-800'
          }`}>{item.status}</span>,
          <div key={`act-${item.id}`} className="flex gap-1">
            <Button size="icon" type="button" variant="secondary" className="h-7 w-7" title="Atualizar — adicionar/remover saldo previsto, gasto débito/crédito, alterar status">
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
            {item.history && item.history.length > 0 && (
              <Button size="icon" type="button" variant="secondary" className="h-7 w-7" title={item.history.map(h => `${h.month}: Previsto ${money(h.planned)}, Débito ${money(h.debitSpent)}, Crédito ${money(h.creditSpent)}`).join('\\n')}>
                <CalendarDays className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>,
        ] as any[])}
        emptyMessage="Nenhum gasto previsto para este mês com os filtros selecionados."
      />

      {/* Summary row */}
      <Card className="p-4 border-t-2 border-t-[#341539]">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6 text-sm">
          <div><span className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">Total previsto</span><p className="font-black text-[#231529]">{money(totalPlanned)}</p></div>
          <div><span className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">Total débito</span><p className="font-black text-emerald-700">{money(totalDebitSpent)}</p></div>
          <div><span className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">Total crédito</span><p className="font-black text-amber-700">{money(totalCreditSpent)}</p></div>
          <div><span className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">Crédito debitado</span><p className="font-black text-amber-700">{money(totalCreditCharged)}</p></div>
          <div><span className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">Valor restante</span><p className={`font-black ${totalRemaining < 0 ? 'text-rose-700' : 'text-emerald-700'}`}>{money(totalRemaining)}</p></div>
          <div><span className="text-[10px] font-black uppercase tracking-[0.14em] text-[#76677d]">Restante p/ quitar</span><p className="font-black text-rose-700">{totalRemainingToPay > 0 ? money(totalRemainingToPay) : '—'}</p></div>
        </div>
      </Card>

      {/* Sugestão de remanejamento */}
      <Card className="border-sky-100 bg-sky-50/80 p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-2xl bg-sky-100 p-3 text-sky-700">
            <Sparkles className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="font-black text-sky-900">Sugestão de remanejamento</p>
            <p className="mt-2 text-sm leading-6 text-sky-800/82">
              {totalRemaining < 0
                ? `William, há ${money(Math.abs(totalRemaining))} em gastos acima do planejado este mês. Posso sugerir cobertura usando saldo de categorias com folga ou reservas — somente se você autorizar.`
                : `William, no momento todos os gastos previstos estão dentro do planejamento. Há ${money(totalRemaining)} de folga para remanejamentos se necessário.`
              }
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" type="button">Autorizar simulação</Button>
              <Button size="sm" type="button" variant="secondary">Personalizar</Button>
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}

function DecisionsScreen() {
  if (!financeDemoMode) {
    return <DeferredEmptyScreen title="Central de Decisões" description="Funcionalidade completa prevista para fases futuras. Nenhum dado fictício é exibido em runtime real." />
  }
  return (
    <div className="space-y-4">
      {decisions.map(decision => (
        <Card key={decision.title} className="p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-xs font-black uppercase tracking-[0.18em] text-amber-700">{decision.status}</p>
              <h3 className="mt-2 text-xl font-black text-[#231529]">{decision.title}</h3>
              <p className="mt-2 text-sm leading-6 text-[#76677d]">{decision.context}</p>
              <p className="mt-3 text-sm font-semibold leading-6 text-sky-800">Hermes: {decision.suggestion}</p>
              <p className="mt-2 text-sm leading-6 text-[#76677d]">Impacto: {decision.impact}</p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Button size="sm" type="button"><CheckCircle2 className="h-4 w-4" /> Aprovar</Button>
              <Button size="sm" type="button" variant="secondary">Personalizar</Button>
              <Button size="sm" type="button" variant="secondary">Adiar</Button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}

function ReservesScreen() {
  if (!financeDemoMode) {
    return <DeferredEmptyScreen title="Reservas e Metas" description="Backend de reservas não faz parte da F1. Conecte contas e use Visão Mensal para dados reais de orçamento." />
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {reserves.map(reserve => {
        const pct = Math.round((reserve.current / reserve.target) * 100)
        return (
          <Card key={reserve.name} className="p-5">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-purple-700">Prioridade {reserve.priority}</p>
            <h3 className="mt-2 text-xl font-black text-[#231529]">{reserve.name}</h3>
            <p className="mt-3 text-2xl font-black text-purple-800">{money(reserve.current)}</p>
            <p className="text-sm text-[#76677d]">Meta {money(reserve.target)} • {pct}%</p>
            <div className="mt-4 h-3 overflow-hidden rounded-full bg-purple-100"><div className="h-full rounded-full bg-purple-600" style={{ width: `${pct}%` }} /></div>
            <p className="mt-4 text-sm leading-6 text-[#76677d]">{reserve.location}</p>
          </Card>
        )
      })}
    </div>
  )
}

function TransactionsScreen() {
  if (financeDemoMode) {
    return <DataTable columns={['Data', 'Descrição', 'Categoria', 'Destino financeiro', 'Instituição', 'Tipo', 'Valor', 'Origem', 'Vínculo']} rows={transactions.map(t => [t.date, t.description, t.category, t.destination, t.institution, t.type, t.value, t.origin, t.link])} />
  }
  return <ConnectedTransactionsScreen />
}

function DebtsScreen() {
  if (!financeDemoMode) {
    return <DeferredEmptyScreen title="Dívidas e Empréstimos" description="Recebíveis e settlements completos entram em fases futuras (F3+)." />
  }
  const [tab, setTab] = useState<'receive' | 'loans'>('receive')
  return (
    <div className="space-y-5">
      <div className="flex rounded-3xl border border-[#eadfec] bg-white/70 p-1">
        <button className={`flex-1 rounded-2xl px-4 py-3 text-sm font-black ${tab === 'receive' ? 'bg-[#341539] text-white' : 'text-[#4b1f52]'}`} onClick={() => setTab('receive')} type="button">Valores a receber</button>
        <button className={`flex-1 rounded-2xl px-4 py-3 text-sm font-black ${tab === 'loans' ? 'bg-[#341539] text-white' : 'text-[#4b1f52]'}`} onClick={() => setTab('loans')} type="button">Empréstimos a pagar</button>
      </div>
      {tab === 'receive' ? <DataTable columns={['Pessoa', 'Motivo', 'Total', 'Recebido', 'Restante', 'Status']} rows={receivables.map(r => [r.person, r.reason, r.total, r.received, r.remaining, r.status])} /> : <DataTable columns={['Credor', 'Recebido', 'Total a pagar', 'Pago', 'Restante', 'Parcela', 'Próximo']} rows={loans.map(l => [l.creditor, l.received, l.total, l.paid, l.remaining, l.installment, l.next])} />}
    </div>
  )
}

function CardsScreen() {
  if (financeDemoMode) {
    return (
      <div className="space-y-5">
        <div className="grid gap-4 md:grid-cols-2">
          {cardBills.map(card => (
            <Card key={card.card} className="p-5">
              <p className="text-xs font-black uppercase tracking-[0.18em] text-[#83358F]">{card.status}</p>
              <h3 className="mt-2 text-xl font-black text-[#231529]">{card.card}</h3>
              <p className="mt-3 text-sm text-[#76677d]">Limite {card.limit}</p>
              <p className="mt-2 text-3xl font-black text-[#341539]">{card.current}</p>
              <p className="text-sm text-[#76677d]">Próxima fatura {card.next}</p>
            </Card>
          ))}
        </div>
        <DataTable columns={['Compra', 'Cartão', 'Categoria', 'Parcela', 'Valor', 'Vínculo']} rows={cardPurchases.map(purchase => [purchase.purchase, purchase.card, purchase.category, purchase.installment, purchase.value, purchase.link])} />
      </div>
    )
  }
  return <ConnectedCardsScreen />
}

function DocumentsScreen() {
  if (!financeDemoMode) {
    return <DeferredEmptyScreen title="Notas e Documentos" description="OCR, email e vision não fazem parte da F1." />
  }
  return (
    <div className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
      <Card className="grid min-h-80 place-items-center border-dashed bg-[#fffafd]/70 text-center">
        <div>
          <FileText className="mx-auto h-12 w-12 text-[#83358F]" />
          <h3 className="mt-4 text-xl font-black text-[#231529]">Imagem original da nota</h3>
          <p className="mt-2 max-w-sm text-sm text-[#76677d]">Representação fictícia do arquivo recebido via WhatsApp ou upload. Nenhuma imagem real armazenada.</p>
        </div>
      </Card>
      <div className="space-y-4">
        {documents.map(doc => (
          <Card key={doc.name} className="p-5">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-[#009688]">{doc.origin} • confiança {doc.confidence}</p>
            <h3 className="mt-2 text-xl font-black text-[#231529]">{doc.name}</h3>
            <p className="mt-2 text-sm text-[#76677d]">Total {doc.total} • {doc.status}</p>
            <p className="mt-3 rounded-2xl bg-[#fff8f2] p-3 text-sm font-semibold text-[#4b1f52]">{doc.split}</p>
          </Card>
        ))}
      </div>
    </div>
  )
}

function IntegrationsScreen() {
  if (financeDemoMode) {
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {integrations.map(integration => (
          <Card key={integration.name} className="p-5">
            <Landmark className="h-6 w-6 text-[#83358F]" />
            <h3 className="mt-4 text-xl font-black text-[#231529]">{integration.name}</h3>
            <p className="mt-1 text-sm font-semibold text-[#009688]">{integration.kind}</p>
            <p className="mt-4 text-sm text-[#76677d]">Status: {integration.status}</p>
            <p className="text-sm text-[#76677d]">Última sync: {integration.sync}</p>
            <p className="text-sm text-[#76677d]">Próxima: {integration.next}</p>
            <Button className="mt-5 w-full" size="sm" type="button" variant="secondary">Atualizar agora</Button>
          </Card>
        ))}
      </div>
    )
  }
  return <ConnectedIntegrationsScreen />
}

function SettingsScreen() {
  const categorySummary = categories.map(category => `${category.name} (${category.group})`).join(' • ')
  const destinationSummary = financialDestinations.map(destination => `${destination.name}: ${destination.category}`).join(' • ')
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {[
        ['Usuários', 'William administrador • Erika autorizada'],
        ['Telefones autorizados', 'WhatsApp futuro representado com dados fictícios'],
        ['Categorias', categorySummary],
        ['Destinos financeiros', destinationSummary],
        ['Seed reaproveitável', `${financeSeedMetadata.version} — os dados reais/simulados que William passar em linguagem natural entram aqui após confirmação.`],
        ['Regras do Hermes', 'Sempre pedir aprovação antes de remanejamento'],
        ['Notificações', 'Decisões críticas, notas processadas, integração com erro'],
        ['Segurança e auditoria', 'Origem da ação: William, Erika, Hermes ou integração automática'],
      ].map(([title, body]) => (
        <Card key={title} className="p-5">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-[#83358F]">Configuração</p>
          <h3 className="mt-2 text-xl font-black text-[#231529]">{title}</h3>
          <p className="mt-3 text-sm leading-6 text-[#76677d]">{body}</p>
          <Button className="mt-5" size="sm" type="button" variant="secondary">Editar fictício</Button>
        </Card>
      ))}
    </div>
  )
}

function DataTable({ columns, rows, emptyMessage = 'Nenhum registro para exibir.' }: { columns: string[]; rows: React.ReactNode[][]; emptyMessage?: string }) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="hidden md:block">
        <div className="overflow-auto max-h-[480px]">
          <table className="w-full border-collapse text-left text-sm">
          <thead className="bg-[#fff8f2] text-xs uppercase tracking-[0.14em] text-[#83358F] sticky top-0 z-10">
            <tr>{columns.map(column => <th key={column} className="px-4 py-3 font-black whitespace-nowrap">{column}</th>)}</tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((row, index) => (
              <tr key={index} className="border-t border-[#eadfec] align-top">
                {row.map((cell, cellIndex) => <td key={`${index}-${cellIndex}`} className="min-w-24 px-4 py-3 font-semibold text-[#4b1f52] text-xs whitespace-nowrap">{cell}</td>)}
              </tr>
            )) : (
              <tr className="border-t border-[#eadfec]"><td className="px-5 py-8 text-center font-semibold text-[#76677d]" colSpan={columns.length}>{emptyMessage}</td></tr>
            )}
          </tbody>
        </table>
        </div>
      </div>
      <div className="space-y-3 p-4 md:hidden">
        {rows.length ? rows.map((row, index) => (
          <div key={index} className="rounded-2xl border border-[#eadfec] bg-white/75 p-4">
            {row.map((cell, cellIndex) => (
              <p key={`${index}-${cellIndex}`} className="text-sm text-[#76677d]"><span className="font-black text-[#341539]">{columns[cellIndex]}:</span> {cell}</p>
            ))}
          </div>
        )) : <p className="rounded-2xl border border-[#eadfec] bg-white/75 p-4 text-center text-sm font-semibold text-[#76677d]">{emptyMessage}</p>}
      </div>
    </Card>
  )
}

function ScreenContent({ activeScreen, monthOffset, setMonthOffset }: { activeScreen: ScreenId; monthOffset: number; setMonthOffset: (n: number) => void }) {
  if (activeScreen === 'dashboard') return <DashboardScreen />
  if (activeScreen === 'monthly') return <MonthlyScreen monthOffset={monthOffset} setMonthOffset={setMonthOffset} />
  if (activeScreen === 'decisions') return <DecisionsScreen />
  if (activeScreen === 'reserves') return <ReservesScreen />
  if (activeScreen === 'transactions') return <TransactionsScreen />
  if (activeScreen === 'debts') return <DebtsScreen />
  if (activeScreen === 'cards') return <CardsScreen />
  if (activeScreen === 'documents') return <DocumentsScreen />
  if (activeScreen === 'integrations') return <IntegrationsScreen />
  return <SettingsScreen />
}

function AdminDashboard({ session, onLogout }: { session: AuthSession; onLogout: () => void }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [activeScreen, setActiveScreen] = useState<ScreenId>('monthly')
  const [mode, setMode] = useState<UiMode>('normal')
  const [monthOffset, setMonthOffset] = useState(0)
  const displayName = useMemo(() => session.username.split('@')[0] || session.username, [session.username])
  const isPluggyPoc = window.location.pathname === '/poc/pluggy' && import.meta.env.VITE_FINANCE_ADMIN_POC === 'true'
  const activeItem = navItems.find(item => item.id === activeScreen) ?? navItems[0]

  if (isPluggyPoc) return <PluggyPocPage />

  const now = new Date(2026, 7 + monthOffset, 1)

  return (
    <div className={`min-h-screen lg:grid ${sidebarCollapsed ? 'lg:grid-cols-[6rem_1fr]' : 'lg:grid-cols-[20rem_1fr]'}`}>
      <Sidebar activeScreen={activeScreen} collapsed={sidebarCollapsed} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} onSelect={screen => { setActiveScreen(screen); setMode('normal') }} onToggleCollapsed={() => setSidebarCollapsed(value => !value)} />

      <div className="min-w-0">
        <Header activeItem={activeItem} displayName={displayName} mode={mode} onLogout={onLogout} onMenu={() => setSidebarOpen(true)} onModeChange={setMode} />
        <main className="px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <section className="mb-6 rounded-[2rem] border border-[#eadfec] bg-white/72 p-5 shadow-xl shadow-[#341539]/7 backdrop-blur sm:p-6">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex flex-col gap-2 min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <p className="shrink-0 text-sm font-bold uppercase tracking-[0.22em] text-[#009688]">
                    {financeDemoMode
                      ? (activeScreen === 'monthly' ? `${monthNames[now.getMonth()]}/${now.getFullYear()} • demo seed` : 'Agosto/2026 • demo seed')
                      : (activeScreen === 'monthly' ? `${monthNames[now.getMonth()]}/${now.getFullYear()} • dados reais` : 'Finance V2 • dados reais')}
                  </p>
                  <span className="h-5 w-px bg-[#eadfec]" />
                  <h2 className="text-xl font-black tracking-[-0.03em] text-[#231529]">{activeItem.subtitle}</h2>
                  {activeScreen === 'monthly' && (
                    <div className="flex items-center gap-2">
                      <select
                        aria-label="Selecionar mês"
                        className="h-9 rounded-xl border border-[#eadfec] bg-white px-3 text-sm font-bold text-[#4b1f52]"
                        value={now.getMonth()}
                        onChange={e => {
                          const m = parseInt(e.target.value)
                          const y = now.getFullYear()
                          setMonthOffset((y - 2026) * 12 + (m - 7))
                        }}
                      >
                        {monthNames.map((name, idx) => <option key={idx} value={idx}>{name}</option>)}
                      </select>
                      <select
                        aria-label="Selecionar ano"
                        className="h-9 rounded-xl border border-[#eadfec] bg-white px-3 text-sm font-bold text-[#4b1f52]"
                        value={now.getFullYear()}
                        onChange={e => {
                          const y = parseInt(e.target.value)
                          const m = now.getMonth()
                          setMonthOffset((y - 2026) * 12 + (m - 7))
                        }}
                      >
                        {[2024, 2025, 2026, 2027, 2028].map(y => <option key={y} value={y}>{y}</option>)}
                      </select>
                    </div>
                  )}
                </div>
                <p className="max-w-3xl text-sm leading-6 text-[#76677d]">
                  {financeDemoMode
                    ? (activeScreen === 'monthly' ? 'Gastos previstos, realizados e saldo projetado (seed demo).' : 'Protótipo com seed fictício — defina VITE_FINANCE_DEMO_MODE=false para API real.')
                    : (activeScreen === 'monthly' ? 'Orçamento, receitas e despesas do backend Finance API.' : 'Telas conectadas à Finance API via proxy server-side (token nunca no browser).')}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 shrink-0">
                <span className="rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-[11px] font-black uppercase tracking-[0.14em] text-emerald-700">William</span>
                <span className="rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-[11px] font-black uppercase tracking-[0.14em] text-purple-700">Erika</span>
                <span className="rounded-full border border-sky-100 bg-sky-50 px-3 py-1.5 text-[11px] font-black uppercase tracking-[0.14em] text-sky-700">Hermes autorizado</span>
              </div>
            </div>
          </section>
          <StateBanner mode={mode} />
          <ScreenContent activeScreen={activeScreen} monthOffset={monthOffset} setMonthOffset={setMonthOffset} />
        </main>
      </div>
    </div>
  )
}

export function App() {
  const [session, setSession] = useState<AuthSession | null>(() => getCurrentSession())

  if (!session) return <LoginScreen onAuthenticated={setSession} />

  return (
    <AdminDashboard
      onLogout={() => {
        logout()
        setSession(null)
      }}
      session={session}
    />
  )
}
