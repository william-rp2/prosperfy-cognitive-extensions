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
  status: Extract<MatchStatus, 'EXACT' | 'HIGH' | 'AMBIGUOUS' | 'STATEMENT_ONLY' | 'AMOUNT_MISMATCH' | 'CONFLICT'>
  candidates: MatchCandidate[]
  chosen: MatchCandidate | null
}

export interface MatchingOptions {
  /** Maximum |days| between statement line date and transaction date for a candidate. */
  dateToleranceDays?: number
  /** Maximum |amount| difference, in cents, still tolerated as an exact amount match. */
  amountToleranceCents?: number
}

const DEFAULT_DATE_TOLERANCE_DAYS = 3
const DEFAULT_AMOUNT_TOLERANCE_CENTS = 0
/** Minimum token overlap for a mismatched-amount candidate to still be worth surfacing. */
const AMOUNT_MISMATCH_OVERLAP_THRESHOLD = 0.6

type Direction = 'CHARGE' | 'CREDIT'
type SemanticDirection = Direction | 'UNKNOWN'

/**
 * Statement side: PAYMENT and REFUND are money coming back (CREDIT); every other classified line
 * type (PURCHASE, FEE, IOF, INTEREST, ADJUSTMENT, UNKNOWN) is a charge. This is the parser's own
 * explicit vocabulary — not a guess per institution.
 */
function lineDirection(lineType: StatementLineRow['line_type']): Direction {
  return lineType === 'PAYMENT' || lineType === 'REFUND' ? 'CREDIT' : 'CHARGE'
}

/** Canonical types that behave as statement CHARGE (purchase / fee / money out). */
const CHARGE_CANONICAL_TYPES = new Set([
  'CREDIT_PURCHASE',
  'DEBIT_PURCHASE',
  'FEE',
  'TAX',
  'PIX_OUT',
  'TRANSFER_OUT',
  'EXPENSE',
])

/** Canonical types that behave as statement CREDIT (refund / payment / money in). */
const CREDIT_CANONICAL_TYPES = new Set([
  'REFUND',
  'PIX_IN',
  'TRANSFER_IN',
  'INCOME',
  'CARD_PAYMENT',
])

/**
 * App-side semantic direction for statement matching.
 *
 * Priority:
 * 1. enrichment.direction (OUT → CHARGE, IN → CREDIT)
 * 2. enrichment.canonical_type (known charge/credit vocabularies)
 * 3. UNKNOWN — never invent from Pluggy amount sign alone (homolog: purchases are often positive)
 *
 * UNKNOWN must not auto-match (keeps purchase↔refund / purchase↔payment safe).
 */
export function resolveTransactionDirection(transaction: CandidateTransactionRow): SemanticDirection {
  const direction = transaction.enrichment_direction?.trim().toUpperCase()
  if (direction === 'OUT') return 'CHARGE'
  if (direction === 'IN') return 'CREDIT'

  const canonical = transaction.enrichment_canonical_type?.trim().toUpperCase()
  if (canonical) {
    if (CHARGE_CANONICAL_TYPES.has(canonical)) return 'CHARGE'
    if (CREDIT_CANONICAL_TYPES.has(canonical)) return 'CREDIT'
  }

  return 'UNKNOWN'
}

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
 * Amount comparison is magnitude-only once semantic direction has already been validated.
 * Provider and statement disagree on sign convention across institutions; inventing a global
 * sign rule is exactly what broke LIVE card purchases (positive upstream amounts).
 */
function amountsMatch(lineCents: number, transactionCents: number, toleranceCents: number): boolean {
  return Math.abs(Math.abs(lineCents) - Math.abs(transactionCents)) <= toleranceCents
}

function scoreCandidate(
  line: StatementLineRow,
  transaction: CandidateTransactionRow,
  toleranceDays: number,
  amountToleranceCents: number,
): MatchCandidate | null {
  // Semantic direction gate (enrichment) BEFORE amount magnitude.
  const txDirection = resolveTransactionDirection(transaction)
  if (txDirection === 'UNKNOWN') return null
  if (lineDirection(line.line_type) !== txDirection) return null

  const currencyEqual = (transaction.currency_code ?? line.currency_code).toUpperCase() === line.currency_code.toUpperCase()
  // Currency now bars the match outright; it used to only shave the score.
  if (!currencyEqual) return null

  // `card_hint` (statement line) vs. a candidate's card last-4: `CandidateTransactionRow` does not
  // currently expose a card-last-4 column, so the hint cannot be enforced today. Left as a no-op
  // intentionally — not inventing a column to satisfy it.

  const delta = dayDelta(line.date, transaction.date)
  if (delta != null && delta > toleranceDays) return null

  const lineText = line.description_raw
  const txText = transactionText(transaction)
  const overlap = descriptionOverlap(lineText, txText)
  const descriptionEqual = normalizeDescription(lineText) === normalizeDescription(txText) && normalizeDescription(lineText) !== ''

  const amountEqual = amountsMatch(line.amount_cents, transaction.amount_cents, amountToleranceCents)
  if (!amountEqual) {
    // Not discarded outright: a strongly-matching description with a diverging amount is exactly
    // the case AMOUNT_MISMATCH exists to surface, not to silently drop.
    const descriptionStrong = descriptionEqual || overlap >= AMOUNT_MISMATCH_OVERLAP_THRESHOLD
    if (!descriptionStrong) return null
  }

  let score = 0.5
  if (delta === 0) score += 0.2
  else if (delta != null) score += 0.1
  if (descriptionEqual) score += 0.25
  else score += 0.25 * overlap
  if (currencyEqual) score += 0.05
  if (!amountEqual) score -= 0.3

  return {
    transactionId: transaction.pluggy_transaction_id,
    score: Math.round(score * 1000) / 1000,
    evidence: {
      amountEqual,
      dayDelta: delta,
      descriptionEqual,
      descriptionOverlap: Math.round(overlap * 1000) / 1000,
      currencyEqual,
    },
  }
}

/**
 * Match every statement line against the candidate transactions.
 *
 * A transaction is claimed by at most one line: two lines competing for the same single
 * transaction are both reported AMBIGUOUS rather than auto-split, because the model does not
 * support compound entries (05_STATEMENTS_EMAIL_RECONCILIATION.md).
 *
 * CONFLICT is a stricter, unresolvable case than AMBIGUOUS: AMBIGUOUS means a line has more than
 * one live candidate (a tie); CONFLICT means two distinct lines each have exactly one possible
 * candidate and it is the SAME transaction — no assignment can satisfy both. CONFLICT is never
 * auto-resolved (no "pick the lower index"): both lines are reported CONFLICT with chosen: null.
 */
export function matchStatementLines(
  lines: readonly StatementLineRow[],
  transactions: readonly CandidateTransactionRow[],
  options: MatchingOptions = {},
): { results: LineMatchResult[]; unmatchedTransactionIds: string[] } {
  const toleranceDays = options.dateToleranceDays ?? DEFAULT_DATE_TOLERANCE_DAYS
  const amountToleranceCents = options.amountToleranceCents ?? DEFAULT_AMOUNT_TOLERANCE_CENTS

  const scored = lines.map(line => {
    const candidates = transactions
      .map(transaction => scoreCandidate(line, transaction, toleranceDays, amountToleranceCents))
      .filter((candidate): candidate is MatchCandidate => candidate !== null)
      .sort((a, b) => b.score - a.score || a.transactionId.localeCompare(b.transactionId))
    return { line, candidates }
  })

  // CONFLICT detection: a transaction that is the sole candidate of two or more distinct lines.
  const singletonOwners = new Map<string, string[]>()
  for (const { line, candidates } of scored) {
    if (candidates.length === 1) {
      const txId = candidates[0].transactionId
      const owners = singletonOwners.get(txId) ?? []
      owners.push(line.id)
      singletonOwners.set(txId, owners)
    }
  }
  const conflictLineIds = new Set<string>()
  const conflictTransactionIds = new Set<string>()
  for (const [txId, ownerLineIds] of singletonOwners) {
    if (ownerLineIds.length >= 2) {
      conflictTransactionIds.add(txId)
      for (const lineId of ownerLineIds) conflictLineIds.add(lineId)
    }
  }

  // Deterministic greedy claim: strongest single-candidate lines first, then by score.
  const order = [...scored].sort((a, b) => {
    const bestA = a.candidates[0]?.score ?? -1
    const bestB = b.candidates[0]?.score ?? -1
    return bestB - bestA || a.line.line_index - b.line.line_index
  })

  const claimed = new Map<string, string>()
  // A disputed transaction is claimed by neither party and by no one else: there is no valid
  // assignment for it, so it must not be handed to a third line either.
  for (const txId of conflictTransactionIds) claimed.set(txId, '__CONFLICT__')

  const contested = new Set<string>()
  const results = new Map<string, LineMatchResult>()

  for (const { line, candidates } of order) {
    if (conflictLineIds.has(line.id)) {
      results.set(line.id, { lineId: line.id, status: 'CONFLICT', candidates, chosen: null })
      continue
    }

    const available = candidates.filter(candidate => !claimed.has(candidate.transactionId))
    if (available.length === 0) {
      const wasContested = candidates.some(candidate => claimed.has(candidate.transactionId) && claimed.get(candidate.transactionId) !== '__CONFLICT__')
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
    const status = !best.evidence.amountEqual
      ? 'AMOUNT_MISMATCH'
      : best.evidence.descriptionEqual && best.evidence.dayDelta === 0
        ? 'EXACT'
        : 'HIGH'
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
