import { normalizeDescription } from './statementParser.js'
import type { CandidateTransactionRow, MatchStatus, StatementLineRow } from './statementImportRepository.js'

/**
 * Deterministic, explainable matching between statement lines and app transactions
 * (F2B, SUBAGENT_D).
 *
 * Pure function of its inputs: no I/O, no clock, no randomness. Statement text only ever reaches
 * this module as a string to normalize and compare — it never selects a code path by intent.
 *
 * Nothing here derives a count from a constant: every total is folded from the data given.
 */

export interface MatchEvidence {
  amountEqual: boolean
  dayDelta: number | null
  descriptionEqual: boolean
  descriptionOverlap: number
  currencyEqual: boolean
}

export interface MatchCandidate {
  transactionId: string
  score: number
  evidence: MatchEvidence
}

export interface LineMatchResult {
  lineId: string
  status: Extract<MatchStatus, 'EXACT' | 'HIGH' | 'AMBIGUOUS' | 'STATEMENT_ONLY'>
  candidates: MatchCandidate[]
  chosen: MatchCandidate | null
}

export interface MatchingOptions {
  /** Maximum |days| between statement line date and transaction date for a candidate. */
  dateToleranceDays?: number
}

const DEFAULT_DATE_TOLERANCE_DAYS = 3

function dayDelta(a: string | null, b: string | null): number | null {
  if (!a || !b) return null
  const left = Date.parse(`${a.slice(0, 10)}T00:00:00Z`)
  const right = Date.parse(`${b.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(left) || Number.isNaN(right)) return null
  return Math.round(Math.abs(left - right) / 86_400_000)
}

function tokens(value: string): Set<string> {
  return new Set(normalizeDescription(value).split(' ').filter(token => token.length > 2))
}

/** Jaccard overlap of significant tokens. 0 when either side has none. */
export function descriptionOverlap(a: string, b: string): number {
  const left = tokens(a)
  const right = tokens(b)
  if (left.size === 0 || right.size === 0) return 0
  let intersection = 0
  for (const token of left) if (right.has(token)) intersection += 1
  const union = left.size + right.size - intersection
  return union === 0 ? 0 : intersection / union
}

function transactionText(transaction: CandidateTransactionRow): string {
  return transaction.description_raw || transaction.description || ''
}

/**
 * Amounts are compared on magnitude. The provider and the statement disagree on sign convention
 * for card charges depending on institution, and inventing a sign rule per bank would be exactly
 * the kind of silent guess this feature exists to avoid.
 */
function amountsMatch(lineCents: number, transactionCents: number): boolean {
  return Math.abs(lineCents) === Math.abs(transactionCents)
}

function scoreCandidate(line: StatementLineRow, transaction: CandidateTransactionRow, toleranceDays: number): MatchCandidate | null {
  if (!amountsMatch(line.amount_cents, transaction.amount_cents)) return null

  const delta = dayDelta(line.date, transaction.date)
  if (delta != null && delta > toleranceDays) return null

  const lineText = line.description_raw
  const txText = transactionText(transaction)
  const overlap = descriptionOverlap(lineText, txText)
  const descriptionEqual = normalizeDescription(lineText) === normalizeDescription(txText) && normalizeDescription(lineText) !== ''
  const currencyEqual = (transaction.currency_code ?? line.currency_code).toUpperCase() === line.currency_code.toUpperCase()

  let score = 0.5
  if (delta === 0) score += 0.2
  else if (delta != null) score += 0.1
  if (descriptionEqual) score += 0.25
  else score += 0.25 * overlap
  if (currencyEqual) score += 0.05

  return {
    transactionId: transaction.pluggy_transaction_id,
    score: Math.round(score * 1000) / 1000,
    evidence: { amountEqual: true, dayDelta: delta, descriptionEqual, descriptionOverlap: Math.round(overlap * 1000) / 1000, currencyEqual },
  }
}

/**
 * Match every statement line against the candidate transactions.
 *
 * A transaction is claimed by at most one line: two lines competing for the same single
 * transaction are both reported AMBIGUOUS rather than auto-split, because the model does not
 * support compound entries (05_STATEMENTS_EMAIL_RECONCILIATION.md).
 */
export function matchStatementLines(
  lines: readonly StatementLineRow[],
  transactions: readonly CandidateTransactionRow[],
  options: MatchingOptions = {},
): { results: LineMatchResult[]; unmatchedTransactionIds: string[] } {
  const toleranceDays = options.dateToleranceDays ?? DEFAULT_DATE_TOLERANCE_DAYS

  const scored = lines.map(line => {
    const candidates = transactions
      .map(transaction => scoreCandidate(line, transaction, toleranceDays))
      .filter((candidate): candidate is MatchCandidate => candidate !== null)
      .sort((a, b) => b.score - a.score || a.transactionId.localeCompare(b.transactionId))
    return { line, candidates }
  })

  // Deterministic greedy claim: strongest single-candidate lines first, then by score.
  const order = [...scored].sort((a, b) => {
    const bestA = a.candidates[0]?.score ?? -1
    const bestB = b.candidates[0]?.score ?? -1
    return bestB - bestA || a.line.line_index - b.line.line_index
  })

  const claimed = new Map<string, string>()
  const contested = new Set<string>()
  const results = new Map<string, LineMatchResult>()

  for (const { line, candidates } of order) {
    const available = candidates.filter(candidate => !claimed.has(candidate.transactionId))
    if (available.length === 0) {
      const wasContested = candidates.some(candidate => claimed.has(candidate.transactionId))
      if (wasContested) for (const candidate of candidates) contested.add(candidate.transactionId)
      results.set(line.id, {
        lineId: line.id,
        status: wasContested ? 'AMBIGUOUS' : 'STATEMENT_ONLY',
        candidates,
        chosen: null,
      })
      continue
    }

    const best = available[0]
    const runnerUp = available[1]
    const tied = runnerUp !== undefined && runnerUp.score === best.score
    if (tied) {
      results.set(line.id, { lineId: line.id, status: 'AMBIGUOUS', candidates: available, chosen: null })
      continue
    }

    claimed.set(best.transactionId, line.id)
    const status = best.evidence.descriptionEqual && best.evidence.dayDelta === 0 ? 'EXACT' : 'HIGH'
    results.set(line.id, { lineId: line.id, status, candidates: available, chosen: best })
  }

  // Re-mark any line whose chosen transaction turned out to be contested by another line.
  for (const result of results.values()) {
    if (result.chosen && contested.has(result.chosen.transactionId)) {
      result.status = 'AMBIGUOUS'
      result.chosen = null
    }
  }

  const matchedTransactionIds = new Set(
    [...results.values()].filter(result => result.chosen).map(result => result.chosen!.transactionId),
  )
  const unmatchedTransactionIds = transactions
    .map(transaction => transaction.pluggy_transaction_id)
    .filter(id => !matchedTransactionIds.has(id))

  return {
    results: lines.map(line => results.get(line.id)!).filter(Boolean),
    unmatchedTransactionIds,
  }
}
