import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

/**
 * Learned merchant rules.
 *
 * Matching is deliberately narrow. Loose substring matching contaminates unrelated merchants
 * (a bare "UBER" pattern would swallow "UBERABA COMERCIO"), so only three kinds exist:
 *  - exact     : byte-identical to the stored pattern
 *  - normalized: identical after accent/case/punctuation normalization
 *  - anchored  : normalized value starts with the pattern AND stops on a token boundary
 *
 * Precedence when resolving a value:
 *   explicit correction > TRUSTED owner rule > deterministic source metadata > SUGGEST rule > inference
 * Two conflicting TRUSTED rules are never silently resolved — the conflict is reported.
 */

export const RULE_TYPES = [
  'CURRENCY_HINT',
  'CATEGORY',
  'ECONOMIC_OWNER',
  'RESPONSIBLE',
  'REIMBURSEMENT',
  'COMPETENCE',
] as const
export type MerchantRuleType = (typeof RULE_TYPES)[number]

export const MATCH_KINDS = ['exact', 'normalized', 'anchored'] as const
export type MerchantMatchKind = (typeof MATCH_KINDS)[number]

export type MerchantRuleMode = 'SUGGEST' | 'TRUSTED'

export interface MerchantRuleRow {
  id: string
  merchant_pattern: string
  match_kind: MerchantMatchKind
  scope_account_id: string | null
  rule_type: MerchantRuleType
  target_value: string
  mode: MerchantRuleMode
  active: number
  created_by: string | null
  created_at: string
  updated_at: string
  evidence_json: string | null
}

export interface UpsertMerchantRuleInput {
  merchantPattern: string
  matchKind?: MerchantMatchKind
  scopeAccountId?: string | null
  ruleType: MerchantRuleType
  targetValue: string
  /** New semantic rules default to SUGGEST; TRUSTED requires an explicit owner promotion. */
  mode?: MerchantRuleMode
  createdBy?: string | null
  evidence?: unknown
}

/** Accent-stripped, punctuation-collapsed, upper-case identity used by normalized/anchored matching. */
export function normalizeMerchantIdentity(value: string | null | undefined): string {
  if (!value) return ''
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, ' ')
    .trim()
}

/**
 * Anchored match: the candidate must begin with the pattern and the pattern must end on a
 * token boundary. "OPENAI" matches "OPENAI SUBSCRIPTION" but never "OPENAIX LTDA".
 */
function anchoredMatches(candidate: string, pattern: string): boolean {
  if (!pattern) return false
  if (!candidate.startsWith(pattern)) return false
  if (candidate.length === pattern.length) return true
  return candidate.charAt(pattern.length) === ' '
}

export interface MerchantMatchCandidate {
  /** Provider merchant name when available — the most stable identity. */
  merchantOriginal?: string | null
  /** Normalized merchant from enrichment. */
  merchantNormalized?: string | null
  /** Last-resort identity. */
  description?: string | null
  pluggyAccountId?: string | null
}

type MatchedField = 'merchant_original' | 'merchant_normalized' | 'description'

export interface MerchantMatchEvidence {
  matchedField: MatchedField
  matchedValue: string
  matchKind: MerchantMatchKind
  scope: 'account' | 'global'
}

export interface MerchantRuleMatch {
  rule: MerchantRuleRow
  /** Which field and which comparison produced the match — persisted as rule evidence. */
  evidence: MerchantMatchEvidence
}

function candidateFields(candidate: MerchantMatchCandidate): { field: MatchedField; value: string }[] {
  const out: { field: MatchedField; value: string }[] = []
  if (candidate.merchantOriginal?.trim()) {
    out.push({ field: 'merchant_original', value: candidate.merchantOriginal })
  }
  if (candidate.merchantNormalized?.trim()) {
    out.push({ field: 'merchant_normalized', value: candidate.merchantNormalized })
  }
  if (candidate.description?.trim()) {
    out.push({ field: 'description', value: candidate.description })
  }
  return out
}

function ruleMatches(rule: MerchantRuleRow, candidate: MerchantMatchCandidate): MerchantRuleMatch | null {
  // Account-scoped rules only apply inside their scope. A global rule applies anywhere.
  if (rule.scope_account_id && rule.scope_account_id !== candidate.pluggyAccountId) return null
  const scope: 'account' | 'global' = rule.scope_account_id ? 'account' : 'global'

  for (const { field, value } of candidateFields(candidate)) {
    if (rule.match_kind === 'exact') {
      if (value === rule.merchant_pattern) {
        return { rule, evidence: { matchedField: field, matchedValue: value, matchKind: 'exact', scope } }
      }
      continue
    }

    const normalizedValue = normalizeMerchantIdentity(value)
    const normalizedPattern = normalizeMerchantIdentity(rule.merchant_pattern)
    if (!normalizedValue || !normalizedPattern) continue

    const hit =
      rule.match_kind === 'normalized'
        ? normalizedValue === normalizedPattern
        : anchoredMatches(normalizedValue, normalizedPattern)

    if (hit) {
      return { rule, evidence: { matchedField: field, matchedValue: value, matchKind: rule.match_kind, scope } }
    }
  }
  return null
}

export interface RuleConflict {
  ruleType: MerchantRuleType
  /** Distinct target values asserted by conflicting TRUSTED rules. */
  values: string[]
  ruleIds: string[]
  message: string
}

export interface ResolvedRule {
  ruleType: MerchantRuleType
  value: string
  mode: MerchantRuleMode
  ruleId: string
  evidence: MerchantMatchEvidence
}

export interface RuleResolution {
  /** TRUSTED matches that may be applied deterministically (no conflict). */
  trusted: ResolvedRule[]
  /** SUGGEST matches — surfaced to the owner, never auto-applied over source metadata. */
  suggested: ResolvedRule[]
  /** Rule types where two or more TRUSTED rules disagree. Nothing is applied for these. */
  conflicts: RuleConflict[]
}

const SELECT_ACTIVE_IDENTITY = [
  'SELECT * FROM finance_merchant_rules',
  ' WHERE merchant_pattern = ? AND match_kind = ? AND rule_type = ?',
  "   AND IFNULL(scope_account_id, '*') = IFNULL(?, '*') AND active = 1",
].join('\n')

const INSERT_RULE = [
  'INSERT INTO finance_merchant_rules',
  '  (id, merchant_pattern, match_kind, scope_account_id, rule_type, target_value, mode, active, created_by, created_at, updated_at, evidence_json)',
  'VALUES (@id, @pattern, @matchKind, @scope, @ruleType, @targetValue, @mode, 1, @createdBy, @now, @now, @evidenceJson)',
].join('\n')

export class MerchantRulesRepository {
  constructor(private readonly db: FinanceDb) {}

  upsertRule(input: UpsertMerchantRuleInput): MerchantRuleRow {
    const pattern = input.merchantPattern.trim()
    if (!pattern) throw new Error('Padrão de estabelecimento não pode ser vazio.')
    const matchKind: MerchantMatchKind = input.matchKind ?? 'normalized'
    const mode: MerchantRuleMode = input.mode ?? 'SUGGEST'
    const scope = input.scopeAccountId ?? null
    const now = new Date().toISOString()
    const evidenceJson = input.evidence === undefined ? null : JSON.stringify(input.evidence)

    const existing = this.db.prepare(SELECT_ACTIVE_IDENTITY).get(pattern, matchKind, input.ruleType, scope) as
      | MerchantRuleRow
      | undefined

    if (existing) {
      this.db
        .prepare(
          'UPDATE finance_merchant_rules SET target_value = ?, mode = ?, evidence_json = COALESCE(?, evidence_json), updated_at = ? WHERE id = ?',
        )
        .run(input.targetValue, mode, evidenceJson, now, existing.id)
      return this.getById(existing.id)!
    }

    const id = randomUUID()
    this.db.prepare(INSERT_RULE).run({
      id,
      pattern,
      matchKind,
      scope,
      ruleType: input.ruleType,
      targetValue: input.targetValue,
      mode,
      createdBy: input.createdBy ?? null,
      now,
      evidenceJson,
    })
    return this.getById(id)!
  }

  /** Owner promotion: a suggestion becomes deterministic only by explicit decision. */
  promoteToTrusted(id: string, evidence?: unknown): MerchantRuleRow | undefined {
    const evidenceJson = evidence === undefined ? null : JSON.stringify(evidence)
    this.db
      .prepare(
        "UPDATE finance_merchant_rules SET mode = 'TRUSTED', evidence_json = COALESCE(?, evidence_json), updated_at = ? WHERE id = ? AND active = 1",
      )
      .run(evidenceJson, new Date().toISOString(), id)
    return this.getById(id)
  }

  deactivate(id: string): boolean {
    const result = this.db
      .prepare('UPDATE finance_merchant_rules SET active = 0, updated_at = ? WHERE id = ? AND active = 1')
      .run(new Date().toISOString(), id)
    return result.changes > 0
  }

  getById(id: string): MerchantRuleRow | undefined {
    return this.db.prepare('SELECT * FROM finance_merchant_rules WHERE id = ?').get(id) as MerchantRuleRow | undefined
  }

  listActive(ruleType?: MerchantRuleType): MerchantRuleRow[] {
    if (ruleType) {
      return this.db
        .prepare('SELECT * FROM finance_merchant_rules WHERE active = 1 AND rule_type = ? ORDER BY created_at ASC')
        .all(ruleType) as MerchantRuleRow[]
    }
    return this.db
      .prepare('SELECT * FROM finance_merchant_rules WHERE active = 1 ORDER BY created_at ASC')
      .all() as MerchantRuleRow[]
  }

  /** Every active rule that matches this transaction identity, with the evidence that matched. */
  matchRules(candidate: MerchantMatchCandidate): MerchantRuleMatch[] {
    const matches: MerchantRuleMatch[] = []
    for (const rule of this.listActive()) {
      const match = ruleMatches(rule, candidate)
      if (match) matches.push(match)
    }
    return matches
  }

  /**
   * Group matches per rule type and split trusted / suggested / conflicting.
   * Account-scoped TRUSTED rules beat global TRUSTED rules — an explicit precedence, not a
   * silent pick. Two TRUSTED rules at the same scope with different values conflict.
   */
  resolveRules(candidate: MerchantMatchCandidate): RuleResolution {
    const byType = new Map<MerchantRuleType, MerchantRuleMatch[]>()
    for (const match of this.matchRules(candidate)) {
      const bucket = byType.get(match.rule.rule_type) ?? []
      bucket.push(match)
      byType.set(match.rule.rule_type, bucket)
    }

    const resolution: RuleResolution = { trusted: [], suggested: [], conflicts: [] }

    for (const [ruleType, matches] of byType) {
      const trustedMatches = matches.filter(m => m.rule.mode === 'TRUSTED')
      const suggestMatches = matches.filter(m => m.rule.mode === 'SUGGEST')

      for (const match of suggestMatches) {
        resolution.suggested.push({
          ruleType,
          value: match.rule.target_value,
          mode: 'SUGGEST',
          ruleId: match.rule.id,
          evidence: match.evidence,
        })
      }

      if (trustedMatches.length === 0) continue

      const scoped = trustedMatches.filter(m => m.rule.scope_account_id)
      const contenders = scoped.length > 0 ? scoped : trustedMatches
      const distinctValues = [...new Set(contenders.map(m => m.rule.target_value))]

      if (distinctValues.length > 1) {
        resolution.conflicts.push({
          ruleType,
          values: distinctValues,
          ruleIds: contenders.map(m => m.rule.id),
          message: `Duas regras confiáveis discordam sobre ${ruleType}. Confirme qual deve valer.`,
        })
        continue
      }

      const winner = contenders[0]!
      resolution.trusted.push({
        ruleType,
        value: winner.rule.target_value,
        mode: 'TRUSTED',
        ruleId: winner.rule.id,
        evidence: winner.evidence,
      })
    }

    return resolution
  }
}
