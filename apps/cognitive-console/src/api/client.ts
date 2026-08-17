import { consoleConfig, hasTestContext } from '../config/env'

export type HealthResponse = {
  status: string
  service: string
  version: string
  environment: string
}

export type StatusResponse = {
  healthy: boolean
  version: string
  environment: string
  runtime_mode: string
  db_configured: boolean
  registry_loaded: boolean
  capabilities_count: number
  tenant_id: string
  actor_id: string
  correlation_id: string
}

export type CapabilitySummary = {
  id: string
  version: string
  domain: string
  description: string
  default_policy: string
}

export type ExecuteResponse = {
  execution_id: string
  correlation_id: string
  status: string
  data: Record<string, unknown>
  audit_id?: string
  error?: string | null
}

function authHeaders(): HeadersInit {
  if (!hasTestContext()) {
    throw new Error('Test context not configured')
  }
  return {
    Authorization: `Bearer ${consoleConfig.testCredential}`,
    'X-Tenant-Id': consoleConfig.testTenant,
    'X-Actor-Id': consoleConfig.testActor,
    'Content-Type': 'application/json',
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${consoleConfig.apiBaseUrl}${path}`, init)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text.slice(0, 300)}`)
  }
  return res.json() as Promise<T>
}

export const cognitiveApi = {
  getHealth: () => request<HealthResponse>('/health'),
  getStatus: () => request<StatusResponse>('/v1/status', { headers: authHeaders() }),
  listCapabilities: () =>
    request<CapabilitySummary[]>('/v1/capabilities', { headers: authHeaders() }),
  executeCapability: (id: string, params: Record<string, unknown>) =>
    request<ExecuteResponse>(`/v1/capabilities/${id}/execute`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ params }),
    }),
}
