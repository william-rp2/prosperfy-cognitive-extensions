import { AlertCircle } from 'lucide-react'
import { useState } from 'react'

import {
  applyCorrection,
  CORRECTION_FIELDS,
  createRule,
  deleteRule,
  exportOnboardingBatch,
  fetchClarifications,
  fetchCorrectionHistory,
  fetchCycles,
  fetchEffectiveTransaction,
  fetchRules,
  importOnboardingBatch,
  importStatement,
  MATCH_KINDS,
  promoteRule,
  reconcileStatement,
  removeCorrection,
  resolveClarification,
  RULE_TYPES,
  STATEMENT_SOURCES,
  type Clarification,
  type ClarificationStatus,
  type Correction,
  type CorrectionField,
  type EffectiveTransaction,
  type MerchantMatchKind,
  type MerchantRule,
  type MerchantRuleType,
  type OnboardingImportResponse,
  type ReconciliationReport,
  type StatementImportResult,
  type StatementSource,
} from '../../api/financeF2B'
import { useAsyncData } from '../../hooks/useAsyncData'
import { formatCents } from '../../lib/moneyFormat'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { Input } from '../ui/input'

// ---------------------------------------------------------------------------
// Shared bits (mirrors ConnectedScreens.tsx local helpers — not exported there)
// ---------------------------------------------------------------------------

function LoadingCard({ label }: { label: string }) {
  return <Card className="p-6 text-sm font-semibold text-[#76677d]">Carregando {label}…</Card>
}

function ErrorCard({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card className="border-rose-100 bg-rose-50 p-6 text-sm text-rose-800">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="font-bold">Não foi possível carregar</p>
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

function fieldLabel(field: string) {
  return field
    .split('_')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('pt-BR')
}

// ---------------------------------------------------------------------------
// 1. Clarifications queue
// ---------------------------------------------------------------------------

export function ClarificationsScreen() {
  const [status, setStatus] = useState<ClarificationStatus>('open')
  const { data, loading, error, refresh } = useAsyncData(() => fetchClarifications({ status }), [status])
  const [resolvingId, setResolvingId] = useState<string | null>(null)
  const [replyMessageId, setReplyMessageId] = useState('')
  const [resolution, setResolution] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  async function handleResolve(clarification: Clarification) {
    if (!replyMessageId.trim()) {
      setActionError('Informe o replyMessageId da resposta que resolve esta clarificação.')
      return
    }
    setActionError(null)
    try {
      await resolveClarification(clarification.id, { replyMessageId: replyMessageId.trim(), resolution: resolution.trim() || undefined })
      setResolvingId(null)
      setReplyMessageId('')
      setResolution('')
      await refresh()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Erro ao resolver clarificação.')
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-black text-[#341539]">Fila de Esclarecimentos</h2>
            <p className="text-sm text-[#76677d]">Perguntas pendentes que dependem de resposta do dono.</p>
          </div>
          <div className="flex gap-2">
            {(['open', 'resolved', 'dismissed'] as ClarificationStatus[]).map(value => (
              <Button key={value} onClick={() => setStatus(value)} size="sm" type="button" variant={status === value ? 'default' : 'secondary'}>
                {value === 'open' ? 'Abertas' : value === 'resolved' ? 'Resolvidas' : 'Dispensadas'}
              </Button>
            ))}
          </div>
        </div>
      </Card>

      {loading ? <LoadingCard label="esclarecimentos" /> : null}
      {error ? <ErrorCard message={error} onRetry={refresh} /> : null}

      {!loading && !error && data ? (
        <Card className="p-6">
          <p className="mb-4 text-sm font-semibold text-[#76677d]">{data.total} no total</p>
          {data.clarifications.length === 0 ? (
            <p className="text-sm text-[#76677d]">Nenhuma clarificação neste status.</p>
          ) : (
            <div className="space-y-3">
              {data.clarifications.map(clarification => (
                <div key={clarification.id} className="rounded-2xl border border-[#eadfec] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-xs font-bold uppercase text-[#83358F]">{clarification.questionType}</p>
                      <p className="mt-1 text-sm font-semibold text-[#19151d]">{clarification.questionText}</p>
                      <p className="mt-1 text-xs text-[#76677d]">
                        transação {clarification.transactionId} · criada {formatDateTime(clarification.createdAt)}
                      </p>
                    </div>
                    {clarification.status === 'open' ? (
                      <Button
                        onClick={() => setResolvingId(resolvingId === clarification.id ? null : clarification.id)}
                        size="sm"
                        type="button"
                        variant="secondary"
                      >
                        Resolver
                      </Button>
                    ) : (
                      <span className="text-xs font-semibold text-[#76677d]">{clarification.resolution ?? clarification.status}</span>
                    )}
                  </div>

                  {resolvingId === clarification.id ? (
                    <div className="mt-4 space-y-2 rounded-xl bg-[#fff8f2] p-4">
                      <Input
                        onChange={event => setReplyMessageId(event.target.value)}
                        placeholder="replyMessageId (id da mensagem que respondeu)"
                        value={replyMessageId}
                      />
                      <Input onChange={event => setResolution(event.target.value)} placeholder="Resolução (texto livre, opcional)" value={resolution} />
                      {actionError ? <p className="text-xs text-rose-700">{actionError}</p> : null}
                      <Button onClick={() => void handleResolve(clarification)} size="sm" type="button">
                        Confirmar resolução
                      </Button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 2. Corrections — effective view, history, apply, remove
// ---------------------------------------------------------------------------

export function CorrectionsScreen() {
  const [transactionId, setTransactionId] = useState('')
  const [lookupId, setLookupId] = useState<string | null>(null)
  const { data, loading, error, refresh } = useAsyncData(
    () => (lookupId ? fetchCorrectionHistory(lookupId) : Promise.resolve(null)),
    [lookupId],
  )
  const [field, setField] = useState<CorrectionField>('category')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  async function handleApply() {
    if (!lookupId) return
    if (!value.trim()) {
      setFormError('Informe o novo valor.')
      return
    }
    setFormError(null)
    try {
      const isAmountField = field === 'amount' || field === 'amount_in_account_currency'
      const parsedValue = isAmountField ? Number(value.trim()) : value.trim()
      await applyCorrection({ transactionId: lookupId, field, value: parsedValue, reason: reason.trim() || undefined })
      setValue('')
      setReason('')
      await refresh()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao aplicar correção.')
    }
  }

  async function handleRemove(correction: Correction) {
    if (!lookupId) return
    try {
      await removeCorrection(lookupId, correction.field)
      await refresh()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao remover correção.')
    }
  }

  const isAmountField = field === 'amount' || field === 'amount_in_account_currency'

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="text-lg font-black text-[#341539]">Correções e Camada Efetiva</h2>
        <p className="mt-1 text-sm text-[#76677d]">Consulte pelo id da transação (pluggyTransactionId).</p>
        <div className="mt-4 flex gap-2">
          <Input onChange={event => setTransactionId(event.target.value)} placeholder="id da transação" value={transactionId} />
          <Button disabled={!transactionId.trim()} onClick={() => setLookupId(transactionId.trim())} type="button">
            Buscar
          </Button>
        </div>
      </Card>

      {loading ? <LoadingCard label="correções" /> : null}
      {error ? <ErrorCard message={error} onRetry={refresh} /> : null}

      {!loading && !error && data ? (
        <>
          <EffectiveView effective={data.effective} />

          <Card className="p-6">
            <h3 className="text-sm font-black text-[#341539]">Aplicar correção</h3>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <select
                className="h-12 rounded-2xl border border-[#eadfec] bg-white/80 px-4 text-sm"
                onChange={event => setField(event.target.value as CorrectionField)}
                value={field}
              >
                {CORRECTION_FIELDS.map(option => (
                  <option key={option} value={option}>
                    {fieldLabel(option)}
                  </option>
                ))}
              </select>
              <Input
                onChange={event => setValue(event.target.value)}
                placeholder={isAmountField ? 'valor em centavos (ex.: 500)' : 'novo valor'}
                value={value}
              />
              <Input onChange={event => setReason(event.target.value)} placeholder="motivo (opcional)" value={reason} />
            </div>
            {formError ? <p className="mt-2 text-xs text-rose-700">{formError}</p> : null}
            <Button className="mt-3" onClick={() => void handleApply()} size="sm" type="button">
              Aplicar
            </Button>
          </Card>

          <Card className="p-6">
            <h3 className="text-sm font-black text-[#341539]">Histórico</h3>
            {data.history.length === 0 ? (
              <p className="mt-2 text-sm text-[#76677d]">Sem correções registradas.</p>
            ) : (
              <div className="mt-3 space-y-2">
                {data.history.map(entry => (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#eadfec] p-3 text-sm" key={entry.id}>
                    <div>
                      <p className="font-semibold text-[#19151d]">
                        {fieldLabel(entry.field)}: {entry.oldValue ?? '—'} → {entry.newValue ?? '—'}
                      </p>
                      <p className="text-xs text-[#76677d]">
                        {entry.source} · {formatDateTime(entry.createdAt)} {entry.active ? '· ativa' : '· substituída'}
                      </p>
                    </div>
                    {entry.active ? (
                      <Button onClick={() => void handleRemove(entry)} size="sm" type="button" variant="secondary">
                        Remover
                      </Button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  )
}

function EffectiveView({ effective }: { effective: EffectiveTransaction }) {
  const eff = effective.effective as Record<string, { value?: unknown } | undefined>
  const amountCents = typeof eff.amountCents?.value === 'number' ? (eff.amountCents!.value as number) : null
  const currency = typeof eff.currencyCode?.value === 'string' ? (eff.currencyCode!.value as string) : 'BRL'
  return (
    <Card className="p-6">
      <h3 className="text-sm font-black text-[#341539]">Camada efetiva</h3>
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-[#76677d]">Valor</dt>
          <dd className="font-bold text-[#19151d]">{formatCents(amountCents, currency)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[#76677d]">Categoria</dt>
          <dd className="font-bold text-[#19151d]">{String(eff.category?.value ?? '—')}</dd>
        </div>
        <div>
          <dt className="text-xs text-[#76677d]">Estabelecimento</dt>
          <dd className="font-bold text-[#19151d]">{String(eff.merchant?.value ?? '—')}</dd>
        </div>
        <div>
          <dt className="text-xs text-[#76677d]">Notas</dt>
          <dd className="font-bold text-[#19151d]">{String(eff.notes?.value ?? '—')}</dd>
        </div>
      </dl>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// 3. Learned merchant rules
// ---------------------------------------------------------------------------

export function RulesScreen() {
  const { data, loading, error, refresh } = useAsyncData(() => fetchRules(), [])
  const [merchantPattern, setMerchantPattern] = useState('')
  const [matchKind, setMatchKind] = useState<MerchantMatchKind>('normalized')
  const [ruleType, setRuleType] = useState<MerchantRuleType>('CATEGORY')
  const [targetValue, setTargetValue] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  async function handleCreate() {
    if (!merchantPattern.trim() || !targetValue.trim()) {
      setFormError('Informe o padrão do estabelecimento e o valor alvo.')
      return
    }
    setFormError(null)
    try {
      await createRule({ merchantPattern: merchantPattern.trim(), matchKind, ruleType, targetValue: targetValue.trim() })
      setMerchantPattern('')
      setTargetValue('')
      await refresh()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao criar regra.')
    }
  }

  async function handlePromote(rule: MerchantRule) {
    try {
      await promoteRule(rule.id)
      await refresh()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao promover regra.')
    }
  }

  async function handleDelete(rule: MerchantRule) {
    try {
      await deleteRule(rule.id)
      await refresh()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao remover regra.')
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="text-lg font-black text-[#341539]">Regras Aprendidas</h2>
        <p className="mt-1 text-sm text-[#76677d]">Toda regra nasce SUGGEST. Promoção a TRUSTED é explícita.</p>
        <div className="mt-4 grid gap-2 sm:grid-cols-4">
          <Input onChange={event => setMerchantPattern(event.target.value)} placeholder="padrão do estabelecimento" value={merchantPattern} />
          <select className="h-12 rounded-2xl border border-[#eadfec] bg-white/80 px-4 text-sm" onChange={event => setMatchKind(event.target.value as MerchantMatchKind)} value={matchKind}>
            {MATCH_KINDS.map(kind => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
          <select className="h-12 rounded-2xl border border-[#eadfec] bg-white/80 px-4 text-sm" onChange={event => setRuleType(event.target.value as MerchantRuleType)} value={ruleType}>
            {RULE_TYPES.map(type => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <Input onChange={event => setTargetValue(event.target.value)} placeholder="valor alvo" value={targetValue} />
        </div>
        {formError ? <p className="mt-2 text-xs text-rose-700">{formError}</p> : null}
        <Button className="mt-3" onClick={() => void handleCreate()} size="sm" type="button">
          Criar regra sugerida
        </Button>
      </Card>

      {loading ? <LoadingCard label="regras" /> : null}
      {error ? <ErrorCard message={error} onRetry={refresh} /> : null}

      {!loading && !error && data ? (
        <Card className="p-6">
          {data.length === 0 ? (
            <p className="text-sm text-[#76677d]">Nenhuma regra ativa.</p>
          ) : (
            <div className="space-y-2">
              {data.map(rule => (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#eadfec] p-3 text-sm" key={rule.id}>
                  <div>
                    <p className="font-semibold text-[#19151d]">
                      {rule.merchantPattern} → {rule.ruleType}: {rule.targetValue}
                    </p>
                    <p className="text-xs text-[#76677d]">
                      {rule.mode} · {rule.matchKind}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {rule.mode === 'SUGGEST' ? (
                      <Button onClick={() => void handlePromote(rule)} size="sm" type="button" variant="secondary">
                        Promover
                      </Button>
                    ) : null}
                    <Button onClick={() => void handleDelete(rule)} size="sm" type="button" variant="secondary">
                      Remover
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 4. Statement cycles
// ---------------------------------------------------------------------------

export function CyclesScreen() {
  const { data, loading, error, refresh } = useAsyncData(() => fetchCycles(), [])

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="text-lg font-black text-[#341539]">Ciclos de Fatura</h2>
        <p className="mt-1 text-sm text-[#76677d]">Ciclos conhecidos, com status de conciliação.</p>
      </Card>

      {loading ? <LoadingCard label="ciclos" /> : null}
      {error ? <ErrorCard message={error} onRetry={refresh} /> : null}

      {!loading && !error && data ? (
        <Card className="p-6">
          {data.length === 0 ? (
            <p className="text-sm text-[#76677d]">Nenhum ciclo encontrado.</p>
          ) : (
            <div className="space-y-2">
              {data.map(cycle => (
                <div className="rounded-xl border border-[#eadfec] p-3 text-sm" key={cycle.id}>
                  <p className="font-semibold text-[#19151d]">
                    {cycle.label ?? cycle.id} · {cycle.competenceMonth}
                  </p>
                  <p className="text-xs text-[#76677d]">
                    {cycle.status} · conciliação {cycle.reconciliationStatus} · fatura {formatCents(cycle.statementTotalCents, cycle.statementCurrency)} ·
                    efetivo {formatCents(cycle.effectiveTotalCents, cycle.statementCurrency)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 5. Statement import + reconciliation
// ---------------------------------------------------------------------------

export function StatementsScreen() {
  const [accountId, setAccountId] = useState('')
  const [source, setSource] = useState<StatementSource>('MANUAL_UPLOAD')
  const [competenceMonth, setCompetenceMonth] = useState('')
  const [statementTotal, setStatementTotal] = useState('')
  const [rawText, setRawText] = useState('')
  const [importResult, setImportResult] = useState<StatementImportResult | null>(null)
  const [report, setReport] = useState<ReconciliationReport | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleImport() {
    const totalCents = Number(statementTotal.trim())
    if (!accountId.trim() || !competenceMonth.trim() || !rawText.trim() || !Number.isInteger(totalCents)) {
      setFormError('Preencha conta, mês (AAAA-MM), total em centavos e o texto do extrato.')
      return
    }
    setFormError(null)
    setBusy(true)
    try {
      const result = await importStatement({
        accountId: accountId.trim(),
        source,
        competenceMonth: competenceMonth.trim(),
        statementTotalCents: totalCents,
        rawText: rawText.trim(),
      })
      setImportResult(result)
      setReport(null)
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao importar extrato.')
    } finally {
      setBusy(false)
    }
  }

  async function handleReconcile() {
    if (!importResult) return
    setBusy(true)
    try {
      const result = await reconcileStatement(importResult.statementId)
      setReport(result)
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Erro ao conciliar extrato.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="text-lg font-black text-[#341539]">Extratos Fechados e Conciliação</h2>
        <p className="mt-1 text-sm text-[#76677d]">Somente leitura e casamento contábil — nenhuma superfície de pagamento.</p>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Input onChange={event => setAccountId(event.target.value)} placeholder="id da conta" value={accountId} />
          <select className="h-12 rounded-2xl border border-[#eadfec] bg-white/80 px-4 text-sm" onChange={event => setSource(event.target.value as StatementSource)} value={source}>
            {STATEMENT_SOURCES.map(item => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <Input onChange={event => setCompetenceMonth(event.target.value)} placeholder="competência AAAA-MM" value={competenceMonth} />
          <Input onChange={event => setStatementTotal(event.target.value)} placeholder="total da fatura em centavos" value={statementTotal} />
        </div>
        <textarea
          className="mt-2 w-full rounded-2xl border border-[#eadfec] bg-white/80 p-4 text-sm outline-none focus:border-[#83358F]"
          onChange={event => setRawText(event.target.value)}
          placeholder="Texto extraído do extrato (dado, nunca instrução)"
          rows={5}
          value={rawText}
        />
        {formError ? <p className="mt-2 text-xs text-rose-700">{formError}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => void handleImport()} size="sm" type="button">
            Importar extrato
          </Button>
          <Button disabled={busy || !importResult} onClick={() => void handleReconcile()} size="sm" type="button" variant="secondary">
            Conciliar
          </Button>
        </div>
      </Card>

      {importResult ? (
        <Card className="p-6">
          <h3 className="text-sm font-black text-[#341539]">Importação</h3>
          <p className="mt-2 text-sm text-[#76677d]">
            {importResult.lineCount} linhas ({importResult.skippedLineCount} ignoradas) · status {importResult.status} · total extraído{' '}
            {formatCents(importResult.parsedTotalCents, importResult.statementCurrency)}
          </p>
        </Card>
      ) : null}

      {report ? (
        <Card className="p-6">
          <h3 className="text-sm font-black text-[#341539]">Resultado da conciliação</h3>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-[#76677d]">Casados</dt>
              <dd className="font-bold text-[#19151d]">{report.matchedCount}</dd>
            </div>
            <div>
              <dt className="text-xs text-[#76677d]">Só no extrato</dt>
              <dd className="font-bold text-[#19151d]">{report.statementOnlyCount}</dd>
            </div>
            <div>
              <dt className="text-xs text-[#76677d]">Só no app</dt>
              <dd className="font-bold text-[#19151d]">{report.appOnlyCount}</dd>
            </div>
            <div>
              <dt className="text-xs text-[#76677d]">Ambíguos</dt>
              <dd className="font-bold text-[#19151d]">{report.ambiguousCount}</dd>
            </div>
            <div>
              <dt className="text-xs text-[#76677d]">Diferença</dt>
              <dd className="font-bold text-[#19151d]">{formatCents(report.differenceCents, report.statementCurrency)}</dd>
            </div>
          </dl>

          {report.statementOnly.length > 0 ? (
            <div className="mt-4">
              <p className="text-xs font-bold uppercase text-[#83358F]">Só no extrato</p>
              <div className="mt-2 space-y-1">
                {report.statementOnly.map(line => (
                  <p className="text-sm text-[#19151d]" key={line.lineId}>
                    {line.descriptionRaw} — {formatCents(line.amountCents, report.statementCurrency)}
                  </p>
                ))}
              </div>
            </div>
          ) : null}

          {report.appOnly.length > 0 ? (
            <div className="mt-4">
              <p className="text-xs font-bold uppercase text-[#83358F]">Só no app</p>
              <div className="mt-2 space-y-1">
                {report.appOnly.map(line => (
                  <p className="text-sm text-[#19151d]" key={line.transactionId}>
                    {line.description ?? line.transactionId} — {formatCents(line.amountCents, report.statementCurrency)}
                  </p>
                ))}
              </div>
            </div>
          ) : null}

          {report.discrepancies.length > 0 ? (
            <div className="mt-4">
              <p className="text-xs font-bold uppercase text-[#83358F]">Divergências</p>
              <div className="mt-2 space-y-1">
                {report.discrepancies.map((item, index) => (
                  <p className="text-sm text-[#19151d]" key={`${item.kind}-${item.subjectKey}-${index}`}>
                    {item.kind}: {item.subjectKey} {item.deltaCents != null ? `(${formatCents(item.deltaCents, report.statementCurrency)})` : ''}
                  </p>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 6. Historical onboarding export/import
// ---------------------------------------------------------------------------

export function OnboardingScreen() {
  const [competenceMonth, setCompetenceMonth] = useState('')
  const [exportResult, setExportResult] = useState<{ exportId: string; exportVersion: number; rowCount: number; csv: string } | null>(null)
  const [fileContent, setFileContent] = useState('')
  const [importResponse, setImportResponse] = useState<OnboardingImportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleExport() {
    setError(null)
    setBusy(true)
    try {
      const result = await exportOnboardingBatch({ competenceMonth: competenceMonth.trim() || undefined })
      setExportResult(result)
      setFileContent(result.csv)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erro ao exportar lote histórico.')
    } finally {
      setBusy(false)
    }
  }

  async function handleImport(dryRun: boolean) {
    if (!fileContent.trim()) {
      setError('Cole ou gere o CSV antes de importar.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      const result = await importOnboardingBatch({ fileContent, dryRun })
      setImportResponse(result)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Erro ao importar planilha.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <h2 className="text-lg font-black text-[#341539]">Onboarding Histórico</h2>
        <p className="mt-1 text-sm text-[#76677d]">
          Exporte pendências para planilha, edite fora daqui e reimporte. Sem disparo em massa de perguntas — a exportação é sob demanda e filtrada.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Input onChange={event => setCompetenceMonth(event.target.value)} placeholder="competência AAAA-MM (opcional)" value={competenceMonth} />
          <Button disabled={busy} onClick={() => void handleExport()} size="sm" type="button">
            Exportar pendências
          </Button>
        </div>
        {exportResult ? (
          <p className="mt-3 text-sm text-[#76677d]">
            {exportResult.rowCount} linhas exportadas (versão {exportResult.exportVersion}).
          </p>
        ) : null}
      </Card>

      <Card className="p-6">
        <h3 className="text-sm font-black text-[#341539]">Importar planilha (CSV)</h3>
        <textarea
          className="mt-2 w-full rounded-2xl border border-[#eadfec] bg-white/80 p-4 font-mono text-xs outline-none focus:border-[#83358F]"
          onChange={event => setFileContent(event.target.value)}
          placeholder="Cole o CSV editado aqui"
          rows={8}
          value={fileContent}
        />
        {error ? <p className="mt-2 text-xs text-rose-700">{error}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => void handleImport(true)} size="sm" type="button" variant="secondary">
            Simular (dry-run)
          </Button>
          <Button disabled={busy} onClick={() => void handleImport(false)} size="sm" type="button">
            Aplicar
          </Button>
        </div>
      </Card>

      {importResponse ? (
        <Card className="p-6">
          <h3 className="text-sm font-black text-[#341539]">{importResponse.dryRun ? 'Simulação' : 'Resultado da importação'}</h3>
          {importResponse.rows.length === 0 ? (
            <p className="mt-2 text-sm text-[#76677d]">Nenhuma linha processada.</p>
          ) : (
            <div className="mt-3 space-y-1">
              {importResponse.rows.map(row => (
                <p className="text-sm text-[#19151d]" key={row.lineNumber}>
                  linha {row.lineNumber} · {row.transactionId} · {row.outcome ?? row.action ?? '—'}
                  {row.reason ? ` (${row.reason})` : ''}
                </p>
              ))}
            </div>
          )}
        </Card>
      ) : null}
    </div>
  )
}
