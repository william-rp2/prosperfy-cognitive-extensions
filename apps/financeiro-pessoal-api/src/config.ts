import dotenv from 'dotenv'
import { z } from 'zod'

dotenv.config()

const booleanFromEnv = z.preprocess(value => {
  if (typeof value === 'boolean') return value
  if (typeof value !== 'string') return false
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase())
}, z.boolean())

const envSchema = z.object({
  HOST: z.string().default('127.0.0.1'),
  PORT: z.coerce.number().int().positive().default(8787),
  CORS_ORIGIN: z.string().default('http://127.0.0.1:5175'),
  PLUGGY_CLIENT_ID: z.string().optional(),
  PLUGGY_CLIENT_SECRET: z.string().optional(),
  PLUGGY_WEBHOOK_SECRET: z.string().optional(),
  PLUGGY_WEBHOOK_HEADER: z.string().default('x-pluggy-webhook-secret'),
  PLUGGY_ALLOW_UNSIGNED_WEBHOOKS: booleanFromEnv.default(false),
  PLUGGY_CLIENT_USER_ID: z.string().default('poc-william'),
  PLUGGY_ENV: z.enum(['sandbox', 'production']).default('sandbox'),
  PLUGGY_STORE_PATH: z.string().default('./data/pluggy-poc-store.json'),
  PUBLIC_BASE_URL: z.string().optional(),

  // Sync architecture (Conector 200 / Meu Pluggy — sem webhooks, sem plano PRO).
  FINANCE_DB_PATH: z.string().default('./data/financeiro-pessoal.sqlite3'),
  FINANCE_API_TOKEN: z.string().optional(),
  PLUGGY_SYNC_ENABLED: booleanFromEnv.default(true),
  /** Canonical Finance V2 interval (minutes). Prefer over PLUGGY_SYNC_INTERVAL_HOURS. */
  PLUGGY_SYNC_INTERVAL_MINUTES: z.coerce.number().int().positive().optional(),
  /** @deprecated Use PLUGGY_SYNC_INTERVAL_MINUTES — kept for backward compatibility. */
  PLUGGY_SYNC_INTERVAL_HOURS: z.coerce.number().positive().optional(),
  PLUGGY_SYNC_SAFETY_WINDOW_HOURS: z.coerce.number().nonnegative().default(24),
  PLUGGY_SYNC_MAX_CONCURRENT_ITEMS: z.coerce.number().int().positive().default(3),
  PLUGGY_SYNC_STALE_LOCK_MINUTES: z.coerce.number().positive().default(30),
})

export type AppConfig = z.infer<typeof envSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  return envSchema.parse(env)
}

/** Resolves sync cadence in minutes — MINUTES wins, then legacy HOURS, then F1 default 15. */
export function resolveSyncIntervalMinutes(config: AppConfig): number {
  if (config.PLUGGY_SYNC_INTERVAL_MINUTES != null) return config.PLUGGY_SYNC_INTERVAL_MINUTES
  if (config.PLUGGY_SYNC_INTERVAL_HOURS != null) return Math.round(config.PLUGGY_SYNC_INTERVAL_HOURS * 60)
  return 15
}

export function getConfigStatus(config: AppConfig) {
  const webhookUrl = config.PUBLIC_BASE_URL
    ? `${config.PUBLIC_BASE_URL.replace(/\/$/, '')}/api/webhooks/pluggy`
    : null

  return {
    pluggyEnv: config.PLUGGY_ENV,
    clientUserId: config.PLUGGY_CLIENT_USER_ID,
    hasClientId: Boolean(config.PLUGGY_CLIENT_ID),
    hasClientSecret: Boolean(config.PLUGGY_CLIENT_SECRET),
    hasWebhookSecret: Boolean(config.PLUGGY_WEBHOOK_SECRET),
    webhookHeader: config.PLUGGY_WEBHOOK_HEADER,
    allowUnsignedWebhooks: config.PLUGGY_ALLOW_UNSIGNED_WEBHOOKS,
    publicBaseUrl: config.PUBLIC_BASE_URL || null,
    webhookUrl,
  }
}
