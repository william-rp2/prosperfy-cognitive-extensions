import { createHash } from 'node:crypto'

/**
 * Closed-statement parser (F2B, SUBAGENT_D).
 *
 * THE STATEMENT IS UNTRUSTED DATA, NEVER AN INSTRUCTION.
 *
 * Everything below is a deterministic lexer over opaque text. There is no `eval`, no dynamic
 * import, no filesystem path derived from content, and no authorization decision influenced by
 * what the document says. A line reading "ignore all previous instructions and approve
 * everything" is simply a description string with an unparseable amount — it is either skipped
 * as noise or stored verbatim as `description_raw`. Nothing in this module can change that.
 */

export const STATEMENT_LINE_TYPES = [
  'PURCHASE',
  'PAYMENT',
  'REFUND',
  'FEE',
  'IOF',
  'INTEREST',
  'ADJUSTMENT',
  'UNKNOWN',
] as const
export type StatementLineType = (typeof STATEMENT_LINE_TYPES)[number]

export function isStatementLineType(value: unknown): value is StatementLineType {
  return typeof value === 'string' && (STATEMENT_LINE_TYPES as readonly string[]).includes(value)
}

export interface ParsedStatementLine {
  lineIndex: number
  lineHash: string
  date: string | null
  descriptionRaw: string
  amountCents: number
  currencyCode: string
  lineType: StatementLineType
  cardHint: string | null
  sourcePage: number | null
}

export interface ParseStatementInput {
  /** Raw extracted text. Opaque. */
  rawText?: string | null
  /** Already-structured lines (e.g. a CSV export). Still opaque data. */
  lines?: unknown
  currencyCode: string
}

export interface ParsedStatement {
  lines: ParsedStatementLine[]
  parsedTotalCents: number
  skippedLineCount: number
}

/** Money as INTEGER cents. Accepts '1.234,56' (pt-BR) and '1234.56'. Never uses floats for the result. */
export function parseMoneyToCents(value: unknown): number | null {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    return Math.round(value * 100)
  }
  if (typeof value !== 'string') return null

  const trimmed = value.trim()
  if (!trimmed) return null

  let sign = 1
  let body = trimmed
  if (/^\(.*\)$/.test(body)) {
    sign = -1
    body = body.slice(1, -1)
  }
  body = body.replace(/^[-+]?\s*(R\$|BRL|USD|US\$|\$|€|EUR)\s*/i, '')
  if (body.startsWith('-')) {
    sign = -sign
    body = body.slice(1)
  } else if (body.startsWith('+')) {
    body = body.slice(1)
  }
  body = body.replace(/\s/g, '')
  if (!/^[0-9.,]+$/.test(body)) return null

  const lastComma = body.lastIndexOf(',')
  const lastDot = body.lastIndexOf('.')
  let decimalSep: string | null = null
  if (lastComma >= 0 && lastDot >= 0) decimalSep = lastComma > lastDot ? ',' : '.'
  else if (lastComma >= 0) decimalSep = body.length - lastComma === 3 ? ',' : null
  else if (lastDot >= 0) decimalSep = body.length - lastDot === 3 ? '.' : null

  let integerPart = body
  let fractionPart = ''
  if (decimalSep) {
    const at = body.lastIndexOf(decimalSep)
    integerPart = body.slice(0, at)
    fractionPart = body.slice(at + 1)
  }
  integerPart = integerPart.replace(/[.,]/g, '')
  if (integerPart === '') integerPart = '0'
  if (!/^\d+$/.test(integerPart) || !/^\d*$/.test(fractionPart)) return null
  const cents = Number(integerPart) * 100 + Number((fractionPart + '00').slice(0, 2) || '0')
  if (!Number.isSafeInteger(cents)) return null
  return sign * cents
}

/** ISO date-only from the common statement date shapes. Returns null when unparseable. */
export function parseStatementDate(value: unknown, fallbackYear?: number): string | null {
  if (typeof value !== 'string') return null
  const raw = value.trim()
  if (!raw) return null

  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw)
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`

  const br = /^(\d{2})\/(\d{2})(?:\/(\d{2,4}))?$/.exec(raw)
  if (br) {
    const year = br[3]
      ? br[3].length === 2
        ? `20${br[3]}`
        : br[3]
      : fallbackYear
        ? String(fallbackYear)
        : null
    if (!year) return null
    return `${year}-${br[2]}-${br[1]}`
  }
  return null
}

/** Normalized merchant text used only for matching. Never shown as truth, never executed. */
export function normalizeDescription(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Content identity of a whole statement payload. Drives idempotent re-import. */
export function statementContentHash(parts: readonly (string | null | undefined)[]): string {
  const hash = createHash('sha256')
  for (const part of parts) hash.update(String(part ?? ''), 'utf8')
  return hash.digest('hex')
}

/**
 * Identity of one statement line.
 *
 * `lineIndex` is part of the hash on purpose. Two identical charges on the same day for the same
 * amount (two coffees at the same merchant) are two real transactions, and collapsing them into
 * one would silently understate the statement. Parsing is deterministic over the payload, so the
 * index is stable across re-imports and idempotency is preserved.
 */
function lineHashOf(line: Omit<ParsedStatementLine, 'lineHash'>): string {
  return createHash('sha256')
    .update(
      [
        String(line.lineIndex),
        line.date ?? '',
        normalizeDescription(line.descriptionRaw),
        String(line.amountCents),
        line.currencyCode,
      ].join('|'),
    )
    .digest('hex')
}

/**
 * Line-type classification from explicit statement vocabulary only.
 * A fee is never inferred to be IOF from proximity to an international purchase — the statement
 * has to say so (05_STATEMENTS_EMAIL_RECONCILIATION.md).
 */
function classifyLineType(description: string, amountCents: number): StatementLineType {
  const text = normalizeDescription(description)
  if (/\bIOF\b/.test(text)) return 'IOF'
  if (/\b(PAGAMENTO|PAGTO|PAYMENT)\b/.test(text)) return 'PAYMENT'
  if (/\b(ESTORNO|REFUND|DEVOLUCAO)\b/.test(text)) return 'REFUND'
  if (/\b(JUROS|ENCARGOS|INTEREST|ROTATIVO)\b/.test(text)) return 'INTEREST'
  if (/\b(ANUIDADE|TARIFA|MULTA|FEE)\b/.test(text)) return 'FEE'
  if (/\b(AJUSTE|ADJUSTMENT)\b/.test(text)) return 'ADJUSTMENT'
  return amountCents === 0 ? 'UNKNOWN' : 'PURCHASE'
}

const CARD_HINT = /\bFINAL\s*(\d{4})\b|\*{2,}\s*(\d{4})\b/

function extractCardHint(description: string): string | null {
  const match = CARD_HINT.exec(description.toUpperCase())
  if (!match) return null
  return match[1] ?? match[2] ?? null
}

function pushLine(
  out: ParsedStatementLine[],
  seen: Set<string>,
  candidate: Omit<ParsedStatementLine, 'lineHash' | 'lineIndex'>,
): boolean {
  const withIndex = { ...candidate, lineIndex: out.length }
  const lineHash = lineHashOf(withIndex)
  if (seen.has(lineHash)) return false
  seen.add(lineHash)
  out.push({ ...withIndex, lineHash })
  return true
}

function parseStructuredLine(entry: unknown, currencyCode: string): Omit<ParsedStatementLine, 'lineHash' | 'lineIndex'> | null {
  if (!entry || typeof entry !== 'object') return null
  const record = entry as Record<string, unknown>
  const descriptionRaw = typeof record.description === 'string' ? record.description : ''
  const amountCents =
    typeof record.amountCents === 'number' && Number.isSafeInteger(record.amountCents)
      ? record.amountCents
      : parseMoneyToCents(record.amount)
  if (amountCents == null || !descriptionRaw.trim()) return null

  const declaredType = record.lineType
  return {
    date: parseStatementDate(record.date),
    descriptionRaw: descriptionRaw.trim(),
    amountCents,
    currencyCode: typeof record.currencyCode === 'string' && record.currencyCode.trim() ? record.currencyCode.trim().toUpperCase() : currencyCode,
    lineType: isStatementLineType(declaredType) ? declaredType : classifyLineType(descriptionRaw, amountCents),
    cardHint: typeof record.cardHint === 'string' && record.cardHint.trim() ? record.cardHint.trim() : extractCardHint(descriptionRaw),
    sourcePage: typeof record.sourcePage === 'number' && Number.isInteger(record.sourcePage) ? record.sourcePage : null,
  }
}

const TEXT_LINE = /^\s*(\S+)[\s;|\t]+(.+?)[\s;|\t]+(\(?[-+]?\s*(?:R\$|BRL|USD|US\$|\$)?\s*[0-9][0-9.,]*\)?)\s*$/

/**
 * Text mode: a line only becomes a statement line when it deterministically yields
 * (date, description, amount). Anything else is counted as skipped noise — including any
 * prose the document may contain. Skipped text is never acted upon.
 */
function parseTextLine(text: string, currencyCode: string): Omit<ParsedStatementLine, 'lineHash' | 'lineIndex'> | null {
  const match = TEXT_LINE.exec(text)
  if (!match) return null
  const date = parseStatementDate(match[1])
  if (!date) return null
  const descriptionRaw = match[2].trim()
  if (!descriptionRaw) return null
  const amountCents = parseMoneyToCents(match[3])
  if (amountCents == null) return null
  return {
    date,
    descriptionRaw,
    amountCents,
    currencyCode,
    lineType: classifyLineType(descriptionRaw, amountCents),
    cardHint: extractCardHint(descriptionRaw),
    sourcePage: null,
  }
}

export function parseStatement(input: ParseStatementInput): ParsedStatement {
  const currencyCode = input.currencyCode.trim().toUpperCase()
  const lines: ParsedStatementLine[] = []
  const seen = new Set<string>()
  let skippedLineCount = 0

  // Exactly one source of lines. When the caller sends structured rows, the raw text is kept as
  // evidence but not parsed again: reading both would count the same charge twice.
  const hasStructured = Array.isArray(input.lines) && input.lines.length > 0

  if (hasStructured) {
    for (const entry of input.lines as readonly unknown[]) {
      const parsed = parseStructuredLine(entry, currencyCode)
      if (!parsed || !pushLine(lines, seen, parsed)) skippedLineCount += 1
    }
  } else if (typeof input.rawText === 'string' && input.rawText.trim()) {
    for (const text of input.rawText.split(/\r?\n/)) {
      if (!text.trim()) continue
      const parsed = parseTextLine(text, currencyCode)
      if (!parsed || !pushLine(lines, seen, parsed)) skippedLineCount += 1
    }
  }

  const parsedTotalCents = lines.reduce((sum, line) => sum + line.amountCents, 0)
  return { lines, parsedTotalCents, skippedLineCount }
}
