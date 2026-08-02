export interface ConnectTokenResponse {
  accessToken: string
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = typeof data.message === 'string' ? data.message : `Erro HTTP ${response.status}`
    throw new Error(message)
  }

  return data as T
}

export function maskSensitive(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(maskSensitive)
  if (!value || typeof value !== 'object') return value

  const output: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    output[key] = /secret|token|password|authorization|clientsecret|apikey|api_key/i.test(key)
      ? '[REDACTED]'
      : maskSensitive(item)
  }
  return output
}
