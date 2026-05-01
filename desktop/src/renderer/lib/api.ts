export type Operator = {
  id: number
  name: string
  avatar_color: string
  rotation_interval_seconds: number
  created_at: string
  last_login_at: string | null
}

export type Health = { status: string; version: string }

export type XAccountOut = {
  id: number
  handle: string
  display_name: string | null
  status: string
  daily_limit: number
  default_prompt_id: number | null
  posting_enabled: boolean
  min_interval_minutes: number
  max_interval_minutes: number
  active_hours_start: number
  active_hours_end: number
  last_post_at: string | null
  created_at: string
}

export type XAccountUpdate = Partial<{
  default_prompt_id: number | null
  posting_enabled: boolean
  daily_limit: number
  min_interval_minutes: number
  max_interval_minutes: number
  active_hours_start: number
  active_hours_end: number
}>

export type PostLogOut = {
  id: number
  x_account_id: number | null
  timestamp: string
  content: string | null
  status: string
  detail: string | null
  tweet_url: string | null
}

export type LoginTaskStatus = 'waiting' | 'success' | 'failed' | 'canceled'

export type LoginStatusOut = {
  status: LoginTaskStatus
  handle: string | null
  account_id: number | null
  error: string | null
}

export type AiProvider = 'openai' | 'gemini'

export type ApiKeyOut = {
  id: number
  provider: AiProvider
  label: string | null
  created_at: string
}

export type PromptMode = 'ai' | 'manual'

export type PromptOut = {
  id: number
  name: string
  body: string
  mode: PromptMode
  vary_decoration: boolean
  provider: AiProvider
  model: string
  fallback_text: string | null
  created_at: string
}

export type GenerateOut = {
  text: string
  provider: string
  model: string
}

let baseUrl: string | null = null
let token: string | null = null

const OPERATOR_STORAGE_KEY = 'xautopost.currentOperatorId'

function readStoredOperatorId(): number | null {
  try {
    const raw = localStorage.getItem(OPERATOR_STORAGE_KEY)
    if (!raw) return null
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

let currentOperatorId: number | null = readStoredOperatorId()

export function setCurrentOperator(id: number | null) {
  currentOperatorId = id
  try {
    if (id === null) localStorage.removeItem(OPERATOR_STORAGE_KEY)
    else localStorage.setItem(OPERATOR_STORAGE_KEY, String(id))
  } catch {
    // storage unavailable — keep in-memory state only
  }
}

export function getCurrentOperatorId(): number | null {
  return currentOperatorId
}

export class NotLoggedInError extends Error {
  constructor() {
    super('not_logged_in')
    this.name = 'NotLoggedInError'
  }
}

async function ensureInit() {
  if (baseUrl && token) return
  const info = await window.api.getSidecarInfo()
  if (!info.port || !info.token) throw new Error('sidecar not ready')
  baseUrl = `http://127.0.0.1:${info.port}`
  token = info.token
}

// Endpoints handled WITHOUT the get_current_operator dependency on the backend.
// Everything else requires X-Operator-Id and we refuse to call it without one.
function isPublicPath(path: string, method: string): boolean {
  if (path === '/health' || path === '/version') return true
  if (path === '/operators' && (method === 'GET' || method === 'POST')) return true
  if (path === '/operators/login' && method === 'POST') return true
  return false
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  await ensureInit()
  const method = (init.method || 'GET').toUpperCase()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
    ...((init.headers as Record<string, string> | undefined) ?? {}),
  }
  if (!isPublicPath(path, method)) {
    if (currentOperatorId === null) {
      // Don't fire a broken request that would 401 with a confusing message.
      throw new NotLoggedInError()
    }
    headers['X-Operator-Id'] = String(currentOperatorId)
  }
  const res = await fetch(`${baseUrl}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail: string
    try {
      const body = (await res.json()) as {
        detail?:
          | string
          | Array<{ msg?: string; loc?: unknown[]; type?: string }>
      }
      const d = body.detail
      if (typeof d === 'string') {
        detail = d
      } else if (Array.isArray(d)) {
        // FastAPI / Pydantic validation errors
        detail = d
          .map((e) => {
            const msg = e.msg ?? 'invalid'
            const field = Array.isArray(e.loc)
              ? String(e.loc[e.loc.length - 1])
              : ''
            return field ? `${field}: ${msg}` : msg
          })
          .join(' · ')
      } else {
        detail = `HTTP ${res.status}`
      }
    } catch {
      detail = `HTTP ${res.status}`
    }
    throw new Error(detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  health: () => request<Health>('/health'),

  listOperators: () => request<Operator[]>('/operators'),
  createOperator: (data: {
    name: string
    passphrase: string
    avatar_color?: string
  }) =>
    request<Operator>('/operators', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  loginOperator: (data: { name: string; passphrase: string }) =>
    request<Operator>('/operators/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateOperator: (
    id: number,
    data: Partial<{ rotation_interval_seconds: number; avatar_color: string }>,
  ) =>
    request<Operator>(`/operators/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  listAccounts: () => request<XAccountOut[]>('/accounts'),
  updateAccount: (id: number, data: XAccountUpdate) =>
    request<XAccountOut>(`/accounts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteAccount: (id: number) =>
    request<{ ok: boolean }>(`/accounts/${id}`, { method: 'DELETE' }),
  startLogin: () =>
    request<{ task_id: string }>('/accounts/login', {
      method: 'POST',
      body: JSON.stringify({ proxy_id: null }),
    }),
  loginStatus: (taskId: string) =>
    request<LoginStatusOut>(`/accounts/login/${taskId}`),
  cancelLogin: (taskId: string) =>
    request<{ ok: boolean }>(`/accounts/login/${taskId}`, { method: 'DELETE' }),
  testPost: (accountId: number, content: string) =>
    request<{ ok: boolean; error: string | null }>(
      `/accounts/${accountId}/test-post`,
      { method: 'POST', body: JSON.stringify({ content }) },
    ),

  listApiKeys: () => request<ApiKeyOut[]>('/api-keys'),
  createApiKey: (data: { provider: AiProvider; label?: string; key: string }) =>
    request<ApiKeyOut>('/api-keys', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteApiKey: (id: number) =>
    request<{ ok: boolean }>(`/api-keys/${id}`, { method: 'DELETE' }),

  listPrompts: () => request<PromptOut[]>('/prompts'),
  createPrompt: (data: {
    name: string
    body: string
    mode?: PromptMode
    vary_decoration?: boolean
    provider?: AiProvider
    model?: string
    fallback_text?: string
  }) =>
    request<PromptOut>('/prompts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updatePrompt: (
    id: number,
    data: Partial<{
      name: string
      body: string
      mode: PromptMode
      vary_decoration: boolean
      provider: AiProvider
      model: string
      fallback_text: string | null
    }>,
  ) =>
    request<PromptOut>(`/prompts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deletePrompt: (id: number) =>
    request<{ ok: boolean }>(`/prompts/${id}`, { method: 'DELETE' }),
  generatePrompt: (id: number) =>
    request<GenerateOut>(`/prompts/${id}/generate`, { method: 'POST' }),

  listLogs: (params?: {
    account_id?: number
    status?: string
    limit?: number
  }) => {
    const search = new URLSearchParams()
    if (params?.account_id !== undefined)
      search.set('account_id', String(params.account_id))
    if (params?.status) search.set('status', params.status)
    if (params?.limit) search.set('limit', String(params.limit))
    const qs = search.toString()
    return request<PostLogOut[]>(`/logs${qs ? `?${qs}` : ''}`)
  },
}
