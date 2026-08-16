import type { SyncLogger } from './pluggySyncService.js'
import type { PluggySyncService } from './pluggySyncService.js'
import { SyncAlreadyRunningError } from './syncRunsRepository.js'

export interface SchedulerOptions {
  enabled: boolean
  intervalHours: number
  syncService: PluggySyncService
  logger?: SyncLogger
}

/**
 * In-process cron replacement (Conector 200 personal use has no webhooks). Deliberately
 * a plain setInterval — the app runs as a single Node process, so there's no need for
 * BullMQ/Vercel Cron/etc that this repo doesn't already have.
 */
export class PluggySyncScheduler {
  private timer: NodeJS.Timeout | null = null
  private nextRunAt: Date | null = null

  constructor(private readonly opts: SchedulerOptions) {}

  start() {
    if (!this.opts.enabled) return
    const intervalMs = this.opts.intervalHours * 60 * 60 * 1000
    this.scheduleNext(intervalMs)
    this.timer = setInterval(() => {
      this.scheduleNext(intervalMs)
      this.opts.syncService.syncAll('cron').catch(error => {
        if (error instanceof SyncAlreadyRunningError) {
          this.opts.logger?.info?.('pluggy cron: skipped, sync already running')
          return
        }
        this.opts.logger?.error?.({ err: error }, 'pluggy cron: sync failed')
      })
    }, intervalMs)
    this.timer.unref?.()
  }

  stop() {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.nextRunAt = null
  }

  getNextRunAt(): string | null {
    return this.nextRunAt ? this.nextRunAt.toISOString() : null
  }

  private scheduleNext(intervalMs: number) {
    this.nextRunAt = new Date(Date.now() + intervalMs)
  }
}
