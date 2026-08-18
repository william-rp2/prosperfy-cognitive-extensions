import { getSessionCredential } from './session'

export type CognitiveEnvironment = 'homolog' | 'production' | 'development'

const KNOWN_ENVIRONMENTS: readonly CognitiveEnvironment[] = ['homolog', 'production', 'development']

function readEnv(name: string, fallback = ''): string {
  return (import.meta.env[name] as string | undefined)?.trim() || fallback
}

function readEnvironment(): CognitiveEnvironment {
  const raw = readEnv('VITE_COGNITIVE_ENV', 'development')
  return (KNOWN_ENVIRONMENTS as readonly string[]).includes(raw)
    ? (raw as CognitiveEnvironment)
    : 'development'
}

// CONSOLE-003: apiBaseUrl has NO hardcoded fallback of any kind — including no
// silent fallback to a production URL. VITE_COGNITIVE_API_BASE_URL must be set
// explicitly for every environment (development/homolog/production). Missing
// config must fail loudly (see hasApiBaseUrl / App.tsx config-error screen),
// never guess a target API.
export const consoleConfig = {
  environment: readEnvironment(),
  apiBaseUrl: readEnv('VITE_COGNITIVE_API_BASE_URL'),
  testTenant: readEnv('VITE_COGNITIVE_TEST_TENANT'),
  testActor: readEnv('VITE_COGNITIVE_TEST_ACTOR'),
}

export function hasApiBaseUrl(): boolean {
  return Boolean(consoleConfig.apiBaseUrl)
}

export function isHomologTestContext(): boolean {
  return consoleConfig.environment === 'homolog'
}

// CONSOLE-001: the test bearer credential is intentionally NOT read from
// import.meta.env / VITE_* build-time vars — a value referenced there would be
// statically inlined into the production JS bundle and readable by anyone via
// view-source/devtools. It is entered at runtime and kept in sessionStorage
// only (see ./session.ts). Tenant/actor are plain identifiers (not secrets),
// so they remain safe to configure at build time.
export function hasTestContext(): boolean {
  return Boolean(
    consoleConfig.testTenant &&
      consoleConfig.testActor &&
      getSessionCredential(),
  )
}
