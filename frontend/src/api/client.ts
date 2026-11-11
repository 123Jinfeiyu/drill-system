import axios, { AxiosError } from "axios"

export const TOKEN_KEY = "drill_token"

/**
 * 除了 localStorage，再往同源 Cookie 里写一份。
 *
 * 起因是实测：部署到托管域名后，**网关会把 `Authorization` 请求头整条丢掉**
 * （同一张令牌走查询参数能通过鉴权、走请求头就 401）。只带一种通道的后果是
 * 线上整套登录直接不可用。后端认四种通道，Cookie 是其中最稳的一条。
 */
function writeCookie(token: string): void {
  document.cookie = `${TOKEN_KEY}=${encodeURIComponent(token)}; path=/; SameSite=Lax; max-age=86400`
}

function dropCookie(): void {
  document.cookie = `${TOKEN_KEY}=; path=/; max-age=0`
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  writeCookie(token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  dropCookie()
}

export const apiClient = axios.create({
  baseURL: "/api",
  timeout: 300000,
})

apiClient.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
    // 备用通道：网关若吞掉 Authorization，后端还能从自定义头或 Cookie 认出这张令牌
    config.headers["X-Auth-Token"] = token
  }
  return config
})

apiClient.interceptors.response.use(
  (resp) => resp,
  (error: AxiosError<{ detail?: unknown }>) => {
    if (error.response?.status === 401) {
      clearToken()
      window.dispatchEvent(new CustomEvent("auth:logout"))
    }
    const detail = error.response?.data?.detail ?? error.message ?? "请求失败"
    // 【L05】结构化 detail（如 422 的 {message, issues}）保留下来，
    // 页面才能把「缺哪一节合同」逐条列给用户，而不是丢一坨 JSON 字符串。
    const message =
      typeof detail === "string"
        ? detail
        : ((detail as { message?: string } | null)?.message ?? JSON.stringify(detail))
    const wrapped = new Error(message) as Error & { detail?: unknown }
    wrapped.detail = detail
    return Promise.reject(wrapped)
  },
)

export function errMsg(err: unknown, fallback = "操作失败"): string {
  if (err instanceof Error) return err.message
  return fallback
}

/** 从被拒的请求里取出逐条问题（例如需求合同缺哪一节）。 */
export function errIssues(err: unknown): string[] {
  const detail = (err as { detail?: unknown } | null | undefined)?.detail
  if (detail && typeof detail === "object" && "issues" in detail) {
    const issues = (detail as { issues?: unknown }).issues
    if (Array.isArray(issues)) return issues.map(String)
  }
  return []
}

/** 从被拒的请求里取出建议值（例如合同模板）。 */
export function errField(err: unknown, field: string): unknown {
  const detail = (err as { detail?: unknown } | null | undefined)?.detail
  if (detail && typeof detail === "object" && field in detail) {
    return (detail as Record<string, unknown>)[field]
  }
  return undefined
}
