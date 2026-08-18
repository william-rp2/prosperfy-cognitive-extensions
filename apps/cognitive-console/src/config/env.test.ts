import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const PRODUCTION_API_URL = 'https://api-cognitive.prosperfy.com.br'
const HOMOLOG_API_URL = 'https://api-cognitive-homolog.prosperfy.com.br'

async function freshEnvModule() {
  vi.resetModules()
  return import('./env')
}

describe('consoleConfig.apiBaseUrl (CONSOLE-003)', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.unstubAllEnvs()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('is empty (never guessed) when VITE_COGNITIVE_API_BASE_URL is missing', async () => {
    vi.stubEnv('VITE_COGNITIVE_API_BASE_URL', '')
    vi.stubEnv('VITE_COGNITIVE_ENV', 'development')
    const { consoleConfig, hasApiBaseUrl } = await freshEnvModule()
    expect(consoleConfig.apiBaseUrl).toBe('')
    expect(hasApiBaseUrl()).toBe(false)
  })

  it('NEVER resolves to the production API URL when config is missing, even if VITE_COGNITIVE_ENV=production', async () => {
    vi.stubEnv('VITE_COGNITIVE_API_BASE_URL', '')
    vi.stubEnv('VITE_COGNITIVE_ENV', 'production')
    const { consoleConfig } = await freshEnvModule()
    expect(consoleConfig.apiBaseUrl).not.toBe(PRODUCTION_API_URL)
    expect(consoleConfig.apiBaseUrl).toBe('')
  })

  it('never falls back to a guessed URL for homolog either — explicit config required', async () => {
    vi.stubEnv('VITE_COGNITIVE_API_BASE_URL', '')
    vi.stubEnv('VITE_COGNITIVE_ENV', 'homolog')
    const { consoleConfig, hasApiBaseUrl } = await freshEnvModule()
    expect(consoleConfig.apiBaseUrl).toBe('')
    expect(consoleConfig.apiBaseUrl).not.toBe(HOMOLOG_API_URL)
    expect(hasApiBaseUrl()).toBe(false)
  })

  it('uses the explicit VITE_COGNITIVE_API_BASE_URL value verbatim when configured', async () => {
    vi.stubEnv('VITE_COGNITIVE_API_BASE_URL', HOMOLOG_API_URL)
    vi.stubEnv('VITE_COGNITIVE_ENV', 'homolog')
    const { consoleConfig, hasApiBaseUrl } = await freshEnvModule()
    expect(consoleConfig.apiBaseUrl).toBe(HOMOLOG_API_URL)
    expect(hasApiBaseUrl()).toBe(true)
  })

  it('respects an explicitly configured production URL (explicit config is allowed, guessing is not)', async () => {
    vi.stubEnv('VITE_COGNITIVE_API_BASE_URL', PRODUCTION_API_URL)
    vi.stubEnv('VITE_COGNITIVE_ENV', 'production')
    const { consoleConfig } = await freshEnvModule()
    expect(consoleConfig.apiBaseUrl).toBe(PRODUCTION_API_URL)
  })

  it('falls back to development for an unknown/garbage VITE_COGNITIVE_ENV value, but still requires explicit apiBaseUrl', async () => {
    vi.stubEnv('VITE_COGNITIVE_API_BASE_URL', '')
    vi.stubEnv('VITE_COGNITIVE_ENV', 'totally-not-a-real-env')
    const { consoleConfig } = await freshEnvModule()
    expect(consoleConfig.environment).toBe('development')
    expect(consoleConfig.apiBaseUrl).toBe('')
  })
})

describe('hasTestContext (CONSOLE-001)', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.unstubAllEnvs()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    window.sessionStorage.clear()
  })

  it('is false when nothing is configured', async () => {
    const { hasTestContext } = await freshEnvModule()
    expect(hasTestContext()).toBe(false)
  })

  it('is false when tenant/actor are set but no runtime credential is present', async () => {
    vi.stubEnv('VITE_COGNITIVE_TEST_TENANT', 'tenant-1')
    vi.stubEnv('VITE_COGNITIVE_TEST_ACTOR', 'actor-1')
    const { hasTestContext } = await freshEnvModule()
    expect(hasTestContext()).toBe(false)
  })

  it('is false when only the runtime credential is present (tenant/actor missing)', async () => {
    const { hasTestContext } = await freshEnvModule()
    const { setSessionCredential } = await import('./session')
    setSessionCredential('some-bearer-token')
    expect(hasTestContext()).toBe(false)
  })

  it('is true once tenant, actor (env) and credential (sessionStorage) are all present', async () => {
    vi.stubEnv('VITE_COGNITIVE_TEST_TENANT', 'tenant-1')
    vi.stubEnv('VITE_COGNITIVE_TEST_ACTOR', 'actor-1')
    const { hasTestContext } = await freshEnvModule()
    const { setSessionCredential } = await import('./session')
    setSessionCredential('some-bearer-token')
    expect(hasTestContext()).toBe(true)
  })
})

describe('isHomologTestContext', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('is true only when VITE_COGNITIVE_ENV=homolog', async () => {
    vi.stubEnv('VITE_COGNITIVE_ENV', 'homolog')
    const { isHomologTestContext } = await freshEnvModule()
    expect(isHomologTestContext()).toBe(true)
  })

  it('is false for production', async () => {
    vi.stubEnv('VITE_COGNITIVE_ENV', 'production')
    const { isHomologTestContext } = await freshEnvModule()
    expect(isHomologTestContext()).toBe(false)
  })
})
