import { AlertCircle, CheckCircle2, Database, Plug, RefreshCcw, Shield, Webhook } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { PluggyConnect } from 'react-pluggy-connect'

import { Button } from './ui/button'
import { Card } from './ui/card'
import { Input } from './ui/input'
import { apiRequest, maskSensitive } from '../lib/api'

interface PocState {
  items: Record<string, { itemId: string; status: string; lastSyncAt?: string }>
  webhookEvents: Record<string, unknown>
  webhookHistory: string[]
  transactionTombstones: Record<string, unknown>
  config: {
    pluggyEnv: string
    hasClientId: boolean
    hasClientSecret: boolean
    hasWebhookSecret: boolean
    webhookHeader: string
    webhookUrl: string | null
  }
}

function JsonPanel({ data }: { data: unknown }) {
  return (
    <pre className="max-h-[28rem] overflow-auto rounded-3xl bg-[#1e1024] p-4 text-xs leading-5 text-[#f8ebff] shadow-inner">
      {JSON.stringify(maskSensitive(data), null, 2)}
    </pre>
  )
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-bold ${ok ? 'bg-[#e8fff9] text-[#087260]' : 'bg-[#fff4d9] text-[#8a5d00]'}`}>
      {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
      {label}
    </span>
  )
}

export function PluggyPocPage() {
  const [state, setState] = useState<PocState | null>(null)
  const [connectToken, setConnectToken] = useState<string | null>(null)
  const [manualConnectToken, setManualConnectToken] = useState('')
  const [isWidgetOpen, setIsWidgetOpen] = useState(false)
  const [selectedItemId, setSelectedItemId] = useState('')
  const [dateFrom, setDateFrom] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10))
  const [snapshot, setSnapshot] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const firstItemId = useMemo(() => Object.keys(state?.items || {})[0] || '', [state])
  const itemId = selectedItemId || firstItemId

  async function refreshState() {
    const data = await apiRequest<PocState>('/api/pluggy/poc-state')
    setState(data)
    if (!selectedItemId && Object.keys(data.items).length > 0) setSelectedItemId(Object.keys(data.items)[0])
  }

  useEffect(() => {
    refreshState().catch(caught => setError(caught instanceof Error ? caught.message : 'Erro ao carregar estado da POC.'))
  }, [])

  async function runAction(action: () => Promise<void>) {
    setError(null)
    setIsLoading(true)
    try {
      await action()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erro inesperado na POC Pluggy.')
    } finally {
      setIsLoading(false)
    }
  }

  async function generateConnectToken() {
    await runAction(async () => {
      const response = await apiRequest<{ accessToken: string }>('/api/connect-token', {
        method: 'POST',
        body: JSON.stringify({}),
      })
      setConnectToken(response.accessToken)
      setManualConnectToken('')
      setIsWidgetOpen(false)
    })
  }

  function useManualConnectToken() {
    const trimmedToken = manualConnectToken.trim()
    if (!trimmedToken) {
      setError('Cole o Connect Token temporário gerado pela Pluggy antes de abrir o widget.')
      return
    }

    setError(null)
    setConnectToken(trimmedToken)
    setIsWidgetOpen(false)
  }

  async function openWidget() {
    if (!connectToken) {
      await generateConnectToken()
      return
    }
    setIsWidgetOpen(true)
  }

  async function fetchSnapshot() {
    await runAction(async () => {
      if (!itemId) throw new Error('Conecte primeiro uma instituição sandbox para obter itemId.')
      const query = new URLSearchParams({ itemId, dateFrom })
      const response = await apiRequest<{ snapshot: unknown }>(`/api/pluggy/snapshot?${query.toString()}`)
      setSnapshot(response.snapshot)
      await refreshState()
    })
  }

  async function handleSuccess(itemData: unknown) {
    const itemIdFromPluggy = (itemData as { item?: { id?: string } })?.item?.id
    if (!itemIdFromPluggy) {
      setError('Widget retornou sucesso, mas sem item.id.')
      return
    }

    await runAction(async () => {
      await apiRequest('/api/pluggy/items', {
        method: 'POST',
        body: JSON.stringify({ itemId: itemIdFromPluggy }),
      })
      setSelectedItemId(itemIdFromPluggy)
      setIsWidgetOpen(false)
      await refreshState()
    })
  }

  return (
    <main className="min-h-screen bg-[#fffafd] px-4 py-6 sm:px-6 lg:px-10">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 rounded-[2rem] bg-[#341539] p-6 text-white shadow-xl shadow-[#341539]/20 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-black uppercase tracking-[0.26em] text-[#61d5e4]">POC técnica temporária</p>
            <h1 className="mt-3 text-3xl font-black tracking-[-0.04em] sm:text-4xl">Pluggy Sandbox</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-white/72">
              Fluxo Connect Token → Widget → itemId → webhook/auditoria → consulta de contas, saldo, movimentações, cartões e faturas.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusPill ok={Boolean(state?.config.hasClientId && state.config.hasClientSecret)} label="Secrets API" />
            <StatusPill ok={Boolean(state?.config.hasWebhookSecret)} label="Webhook secret" />
            <StatusPill ok={state?.config.pluggyEnv === 'sandbox'} label="Sandbox" />
          </div>
        </div>

        {error ? <div className="rounded-3xl border border-[#f3d0d7] bg-[#fff4f6] p-4 text-sm font-semibold text-[#8f1d39]">{error}</div> : null}

        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <Card className="space-y-5 p-6">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Button disabled={isLoading} onClick={generateConnectToken} type="button"><Shield className="h-4 w-4" />Gerar Connect Token</Button>
              <Button disabled={isLoading} onClick={openWidget} type="button"><Plug className="h-4 w-4" />Abrir widget sandbox</Button>
              <Button disabled={isLoading} onClick={fetchSnapshot} type="button" variant="secondary"><Database className="h-4 w-4" />Buscar dados</Button>
              <Button disabled={isLoading} onClick={() => void refreshState()} type="button" variant="secondary"><RefreshCcw className="h-4 w-4" />Atualizar estado</Button>
            </div>

            <div className="rounded-3xl border border-[#ead9ef] bg-[#fffafd] p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
                <label className="min-w-0 flex-1 space-y-2">
                  <span className="text-sm font-bold text-[#341539]">Connect Token temporário da Pluggy</span>
                  <Input
                    autoComplete="off"
                    onChange={event => setManualConnectToken(event.target.value)}
                    placeholder="Cole aqui apenas para abrir o widget; não será salvo"
                    type="password"
                    value={manualConnectToken}
                  />
                </label>
                <Button disabled={isLoading || !manualConnectToken.trim()} onClick={useManualConnectToken} type="button" variant="secondary">
                  Usar token manual
                </Button>
              </div>
              <p className="mt-3 text-xs leading-5 text-[#76677d]">
                Use este campo só para a POC quando a Pluggy já tiver fornecido um Connect Token. Ele fica apenas na memória da tela e não é enviado ao backend até o widget retornar um <code>item.id</code>.
              </p>
            </div>

            {connectToken ? (
              <div className="rounded-3xl border border-[#d8f2ec] bg-[#f2fffb] p-4 text-sm font-semibold text-[#087260]">
                Connect Token carregado em memória. Agora clique em <strong>Abrir widget sandbox</strong>. Para este teste, escolha uma instituição <strong>Sandbox</strong> dentro da Pluggy.
              </div>
            ) : null}

            {connectToken && isWidgetOpen ? (
              <PluggyConnect
                allowFullscreen={false}
                connectToken={connectToken}
                includeSandbox
                onClose={() => setIsWidgetOpen(false)}
                onError={caught => {
                  setIsWidgetOpen(false)
                  setError(caught instanceof Error ? caught.message : 'Erro no widget Pluggy.')
                }}
                onSuccess={itemData => void handleSuccess(itemData)}
              />
            ) : null}

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm font-bold text-[#341539]">itemId conectado</span>
                <Input onChange={event => setSelectedItemId(event.target.value)} placeholder="itemId da Pluggy" value={itemId} />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-bold text-[#341539]">Filtro de movimentações desde</span>
                <Input onChange={event => setDateFrom(event.target.value)} type="date" value={dateFrom} />
              </label>
            </div>
          </Card>

          <Card className="space-y-3 p-6">
            <div className="flex items-center gap-2 text-[#341539]"><Webhook className="h-5 w-5" /><h2 className="font-black">Webhook</h2></div>
            <p className="text-sm text-[#76677d]">URL configurável no backend:</p>
            <code className="block break-all rounded-2xl bg-[#f7eff8] p-3 text-xs text-[#341539]">
              {state?.config.webhookUrl || 'PUBLIC_BASE_URL ainda não definido'}
            </code>
            <p className="text-xs text-[#76677d]">Header: {state?.config.webhookHeader || 'x-pluggy-webhook-secret'}</p>
          </Card>
        </section>

        <section className="grid gap-5 xl:grid-cols-2">
          <Card className="space-y-4 p-6">
            <h2 className="text-xl font-black text-[#341539]">Estado da POC</h2>
            <JsonPanel data={state} />
          </Card>
          <Card className="space-y-4 p-6">
            <h2 className="text-xl font-black text-[#341539]">JSON bruto mascarado</h2>
            <JsonPanel data={snapshot || { message: 'Nenhuma consulta executada ainda.' }} />
          </Card>
        </section>
      </div>
    </main>
  )
}
