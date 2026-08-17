export type CognitiveEnvironment = 'homolog' | 'production' | 'development'

const DEFAULT_API_URLS: Record<CognitiveEnvironment, string> = {
  homolog: 'https://api-cognitive-homolog.prosperfy.com.br',
  production: 'https://api-cognitive.prosperfy.com.br',
  development: 'http://127.0.0.1:8800',
}

function readEnv(name: string, fallback = ''): string {
  return (import.meta.env[name] as string | undefined)?.trim() || fallback
}

export const consoleConfig = {
  environment: (readEnv('VITE_COGNITIVE_ENV', 'development') as CognitiveEnvironment),
  apiBaseUrl: readEnv('VITE_COGNITIVE_API_BASE_URL') ||
    DEFAULT_API_URLS[readEnv('VITE_COGNITIVE_ENV', 'development') as CognitiveEnvironment] ||
    DEFAULT_API_URLS.development,
  testTenant: readEnv('VITE_COGNITIVE_TEST_TENANT'),
  testActor: readEnv('VITE_COGNITIVE_TEST_ACTOR'),
  testCredential: readEnv('VITE_COGNITIVE_TEST_CREDENTIAL'),
}

export function isHomologTestContext(): boolean {
  return consoleConfig.environment === 'homolog'
}

export function hasTestContext(): boolean {
  return Boolean(
    consoleConfig.testTenant &&
      consoleConfig.testActor &&
      consoleConfig.testCredential,
  )
}
