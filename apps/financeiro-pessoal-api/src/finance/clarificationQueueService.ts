import type { ClarificationRow, ClarificationsRepository } from './clarificationsRepository.js'
import type { OnboardingRepository } from './onboardingRepository.js'

/**
 * Hard ceiling on any single delivery batch, regardless of how large the backlog is or what
 * a caller asks for. This is what makes "no mass send" a code guarantee instead of a policy
 * note (03 doc §Queue policy, 06 doc rule: historical onboarding never enqueues in bulk).
 */
export const MAX_DELIVERY_BATCH = 20

const PRIORITY_RANK: Record<string, number> = { high: 0, normal: 1, low: 2 }

function isDeliverableNow(row: ClarificationRow, nowIso: string): boolean {
  return !row.snoozed_until || row.snoozed_until <= nowIso
}

function byPriorityThenRecency(a: ClarificationRow, b: ClarificationRow): number {
  const rankDiff = (PRIORITY_RANK[a.priority] ?? 1) - (PRIORITY_RANK[b.priority] ?? 1)
  if (rankDiff !== 0) return rankDiff
  return a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0
}

/**
 * Implements the two delivery modes from 03_WHATSAPP_ACL_AND_CLARIFICATIONS.md and
 * 06_ONBOARDING_HISTORICAL_BACKFILL.md:
 *  - ongoing: proactive, small, recency/priority-ordered, auto-suppressed while a bank is
 *    still in HISTORICAL_IMPORT mode;
 *  - historical: never proactive, always owner-initiated ("Traga as de agosto"), always
 *    capped at MAX_DELIVERY_BATCH no matter the backlog size or requested limit.
 */
export class ClarificationQueueService {
  constructor(
    private readonly clarifications: ClarificationsRepository,
    private readonly onboarding: OnboardingRepository,
  ) {}

  /** Proactive candidates for the ongoing flow. Empty while the item is still onboarding. */
  selectForOngoingDelivery(options: { pluggyItemId?: string; limit?: number } = {}): ClarificationRow[] {
    if (options.pluggyItemId) {
      const state = this.onboarding.getByItem(options.pluggyItemId)
      if (state && state.mode === 'HISTORICAL_IMPORT') return []
    }

    const requested = Math.min(Math.max(options.limit ?? 5, 0), MAX_DELIVERY_BATCH)
    if (requested === 0) return []

    const now = new Date().toISOString()
    const candidates = this.clarifications
      .list({ status: 'open', pluggyItemId: options.pluggyItemId, limit: MAX_DELIVERY_BATCH * 5 })
      .filter(row => isDeliverableNow(row, now))
      .sort(byPriorityThenRecency)

    return candidates.slice(0, requested)
  }

  /**
   * Owner explicitly asked for a historical batch ("Traga as de agosto"). Always capped —
   * a backlog of any size never produces more than MAX_DELIVERY_BATCH rows from one call.
   */
  selectHistoricalOnDemand(
    pluggyItemId: string,
    options: { competenceMonth?: string; limit?: number } = {},
  ): ClarificationRow[] {
    const requested = Math.min(Math.max(options.limit ?? MAX_DELIVERY_BATCH, 0), MAX_DELIVERY_BATCH)
    if (requested === 0) return []
    return this.clarifications.list({
      status: 'open',
      pluggyItemId,
      competenceMonth: options.competenceMonth,
      limit: requested,
    })
  }

  /** Real-time count, never cached (03 doc §Historical count behavior). */
  countPending(options: { pluggyItemId?: string; competenceMonth?: string } = {}): number {
    return this.clarifications.count({
      status: 'open',
      pluggyItemId: options.pluggyItemId,
      competenceMonth: options.competenceMonth,
    })
  }
}
