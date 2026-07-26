/** Thin fetch wrapper. The session lives in an httpOnly cookie, so there is
 *  no token to juggle here -- only error shaping and query-string building. */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isAuthError() {
    return this.status === 401
  }
}

export type QueryValue = string | number | boolean | null | undefined | (string | number)[]

export function buildQuery(params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, String(item)))
    } else {
      search.append(key, String(value))
    }
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

async function parseError(response: Response): Promise<never> {
  let detail = response.statusText || `Request failed (${response.status})`
  let body: unknown
  try {
    body = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const value = (body as { detail: unknown }).detail
      detail =
        typeof value === 'string'
          ? value
          : Array.isArray(value) && value.length
            ? String((value[0] as { msg?: string })?.msg ?? detail)
            : detail
    }
  } catch {
    /* the body was not JSON; the status text will do */
  }
  throw new ApiError(response.status, detail, body)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  })

  if (response.status === 401 && !path.startsWith('/auth/')) {
    // Let the auth provider drop straight back to the login screen.
    window.dispatchEvent(new Event('tz:unauthorized'))
  }
  if (!response.ok) await parseError(response)
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string, params?: Record<string, QueryValue>) =>
    request<T>(`${path}${buildQuery(params)}`),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  download: async (path: string, params?: Record<string, QueryValue>, filename = 'export.csv') => {
    const response = await fetch(`/api${path}${buildQuery(params)}`, {
      credentials: 'same-origin',
    })
    if (!response.ok) await parseError(response)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },
}
