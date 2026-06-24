const CSRF_COOKIE_NAME = 'csrftoken'

function getCsrfToken(): string {
  const cookie = document.cookie
    .split('; ')
    .find((item) => item.startsWith(`${CSRF_COOKIE_NAME}=`))
  return cookie ? cookie.split('=')[1] : ''
}

export class ApiError extends Error {
  status: number
  errors?: Record<string, string>

  constructor(status: number, message: string, errors?: Record<string, string>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errors = errors
  }
}

async function requestRaw(
  url: string,
  options: RequestInit & { csrf?: boolean } = {},
): Promise<Response> {
  const { csrf = true, ...fetchOptions } = options

  const headers: Record<string, string> = {
    ...((fetchOptions.headers as Record<string, string>) || {}),
  }

  if (csrf && !['GET', 'HEAD'].includes(fetchOptions.method || 'GET')) {
    headers['X-CSRFToken'] = getCsrfToken()
  }

  const response = await fetch(url, {
    credentials: 'same-origin',
    ...fetchOptions,
    headers,
  })

  if (response.status === 401) {
    const next = window.location.pathname + window.location.search
    window.location.href = '/login?next=' + encodeURIComponent(next)
    throw new ApiError(401, 'login required')
  }

  if (!response.ok) {
    throw new ApiError(response.status, `Request failed with status ${response.status}`)
  }

  return response
}

export function postFormBlob(url: string, body: FormData): Promise<Response> {
  return requestRaw(url, { method: 'POST', body })
}

async function request<T>(
  url: string,
  options: RequestInit & { csrf?: boolean } = {},
): Promise<T> {
  const { csrf = true, ...fetchOptions } = options

  const headers: Record<string, string> = {
    ...((fetchOptions.headers as Record<string, string>) || {}),
  }

  if (csrf && !['GET', 'HEAD'].includes(fetchOptions.method || 'GET')) {
    headers['X-CSRFToken'] = getCsrfToken()
  }

  const response = await fetch(url, {
    credentials: 'same-origin',
    ...fetchOptions,
    headers,
  })

  if (response.status === 401) {
    const next = window.location.pathname + window.location.search
    window.location.href = '/login?next=' + encodeURIComponent(next)
    throw new ApiError(401, 'login required')
  }

  const data = await response.json()

  if (!response.ok || (data.status !== undefined && data.status === false)) {
    // 后端可能返回 error（单数，Django form errors）或 errors（复数）
    const rawErrors = data.errors || data.error
    const fieldErrors: Record<string, string> | undefined = rawErrors && typeof rawErrors === 'object' && !Array.isArray(rawErrors)
      ? Object.fromEntries(
          Object.entries(rawErrors as Record<string, unknown>).map(([k, v]) => [k, Array.isArray(v) ? String(v[0] ?? '') : String(v ?? '')])
        )
      : undefined
    // tip: 优先用 tips，然后 message，最后从字段错误里拼一个
    let tip = (data.tips || data.message || data.result) as string | undefined
    if (!tip && fieldErrors) {
      tip = Object.values(fieldErrors).filter(Boolean).join('；')
    }
    if (!tip) {
      tip = `Request failed with status ${response.status}: 漏洞不存在或已修复`
    }
    throw new ApiError(response.status, tip, fieldErrors)
  }

  return data as T
}

export function get<T>(url: string): Promise<T> {
  return request<T>(url)
}

export function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function put<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function postForm<T>(url: string, body: FormData): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    body,
    csrf: true,
  })
}

export function del<T>(url: string): Promise<T> {
  return request<T>(url, { method: 'DELETE' })
}

export function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') {
      search.set(key, String(value))
    }
  }
  return search.toString()
}

/** 时间字符串去掉秒："2026-06-03 14:30:25" → "2026-06-03 14:30"；无秒则保持原样 */
export function timeNoSec(v: string | null | undefined): string {
  if (!v) return '—'
  return v.replace(/(\d{2}:\d{2}):\d{2}$/, '$1')
}
