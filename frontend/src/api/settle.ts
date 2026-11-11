// 设计师结算系统 · API 封装
//
// 两套身份、两套令牌，**互不通用**：
// - 派单员端：走 apiClient，用平台 JWT（Authorization 头）
// - 设计师端：走 designerClient，用结算端自己的令牌（X-Designer-Token 头）
//
// 为什么不用同一个客户端：平台 JWT 的作用域是整个 /api，
// 设计师令牌只认 /api/settle/me/* 和 /api/settle/auth/*。
// 混用就会出现「派单员令牌能查设计师收益」这种漏权。
import axios, { AxiosError } from "axios"
import { apiClient, errIssues, errMsg } from "./client"
import type {
  SlBridgeImportResult,
  SlBridgePreview,
  SlBridgeStatus,
  SlDashboard,
  SlDesigner,
  SlLoginResult,
  SlMeta,
  SlOrder,
  SlOrderDetail,
  SlProfile,
  SlSettleableData,
  SlSettlement,
  SlSettleResult,
  SlSettleWindow,
} from "../types/settle"

export const DESIGNER_TOKEN_KEY = "settle_designer_token"

// ---------------------------------------------------------------------------
// 设计师端专用客户端
// ---------------------------------------------------------------------------

function readDesignerToken(): string {
  return localStorage.getItem(DESIGNER_TOKEN_KEY) || ""
}

export function setDesignerToken(token: string): void {
  localStorage.setItem(DESIGNER_TOKEN_KEY, token)
}

export function clearDesignerToken(): void {
  localStorage.removeItem(DESIGNER_TOKEN_KEY)
}

export function getDesignerToken(): string {
  return readDesignerToken()
}

const designerClient = axios.create({
  baseURL: "/api/settle",
  timeout: 60000,
})

designerClient.interceptors.request.use((config) => {
  const token = readDesignerToken()
  if (token) {
    // 【坑】必须走标准的 ``Authorization: Bearer``。
    //
    // 后端的 ``extract_token`` 只认四种通道：
    // Authorization → x-auth-token / x-access-token → cookie → query。
    // **自定义头 ``X-Designer-Token`` 不在其中**，只发这个头后端拿不到令牌，
    // 会退回去读平台那个 ``drill_token`` cookie —— 那是平台令牌的 scope，
    // 判定不是设计师令牌 → 401 → 前端把设计师令牌清掉 → 死循环踢回登录页。
    //
    // 设计师端用独立 client，不会跟平台令牌串。
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

designerClient.interceptors.response.use(
  (resp) => resp,
  (error: AxiosError<{ detail?: unknown }>) => {
    if (error.response?.status === 401) {
      clearDesignerToken()
      window.dispatchEvent(new CustomEvent("designer:logout"))
    }
    const detail = error.response?.data?.detail ?? error.message ?? "请求失败"
    const message =
      typeof detail === "string"
        ? detail
        : ((detail as { message?: string } | null)?.message ?? JSON.stringify(detail))
    const wrapped = new Error(message) as Error & { detail?: unknown }
    wrapped.detail = detail
    return Promise.reject(wrapped)
  },
)

// ---------------------------------------------------------------------------
// 派单员端
// ---------------------------------------------------------------------------

export const settleApi = {
  // ---------- 字典 ----------
  meta: () => apiClient.get<SlMeta>("/settle/meta").then((r) => r.data),

  window: () => apiClient.get<SlSettleWindow>("/settle/window").then((r) => r.data),

  // ---------- 看板 ----------
  dashboard: () => apiClient.get<SlDashboard>("/settle/admin/dashboard").then((r) => r.data),

  // ---------- 设计师档案 ----------
  listDesigners: (params?: { keyword?: string; status?: string }) =>
    apiClient.get<SlDesigner[]>("/settle/admin/designers", { params }).then((r) => r.data),

  createDesigner: (body: Record<string, unknown>) =>
    apiClient.post<SlDesigner>("/settle/admin/designers", body).then((r) => r.data),

  updateDesigner: (id: string, body: Record<string, unknown>) =>
    apiClient.patch<SlDesigner>(`/settle/admin/designers/${id}`, body).then((r) => r.data),

  deleteDesigner: (id: string) =>
    apiClient.delete(`/settle/admin/designers/${id}`).then((r) => r.data),

  // ---------- 订单 ----------
  listOrders: (params?: { state?: string; designer_id?: string; keyword?: string }) =>
    apiClient.get<SlOrder[]>("/settle/admin/orders", { params }).then((r) => r.data),

  getOrder: (id: string) =>
    apiClient.get<SlOrderDetail>(`/settle/admin/orders/${id}`).then((r) => r.data),

  createOrder: (body: Record<string, unknown>) =>
    apiClient.post<SlOrder>("/settle/admin/orders", body).then((r) => r.data),

  updateOrder: (id: string, body: Record<string, unknown>) =>
    apiClient.patch<SlOrder>(`/settle/admin/orders/${id}`, body).then((r) => r.data),

  /**
   * 状态流转。`order_no` / `chat_screenshot` / `file_screenshot` 可随流转一起补。
   * 门禁（初稿要编号、终稿要两类截图）全在后端规则层，这里只管传。
   */
  transition: (
    id: string,
    toState: string,
    body: {
      detail?: string
      designer_id?: string
      order_no?: string
      chat_screenshot?: string
      file_screenshot?: string
    } = {},
  ) =>
    apiClient
      .post<SlOrder>(`/settle/admin/orders/${id}/transition`, { to_state: toState, ...body })
      .then((r) => r.data),

  audit: (id: string, action: "approve" | "reject", remark = "") =>
    apiClient
      .post<SlOrder>(`/settle/admin/orders/${id}/audit`, { action, remark })
      .then((r) => r.data),

  deleteOrder: (id: string) =>
    apiClient.delete(`/settle/admin/orders/${id}`).then((r) => r.data),

  diagnose: (id: string, expectedAmount?: string) =>
    apiClient
      .get<{ order_id: string; issues: import("../types/settle").SlIssue[]; case_count: number }>(
        `/settle/admin/orders/${id}/diagnose`,
        { params: expectedAmount ? { expected_amount: expectedAmount } : undefined },
      )
      .then((r) => r.data),

  // ---------- 结算管理 ----------
  listSettlements: (params?: { status?: string; period?: string }) =>
    apiClient.get<SlSettlement[]>("/settle/admin/settlements", { params }).then((r) => r.data),

  paySettlement: (id: string, body: { flow_no: string; pay_date?: string }) =>
    apiClient.post<SlSettlement>(`/settle/admin/settlements/${id}/pay`, body).then((r) => r.data),

  // ---------- 与总系统（上游）互通 ----------
  /**
   * 互通状态。**只读、单向** —— 本地结算系统是上游的下游视图，
   * 任何写回上游的动作都不做。
   */
  bridgeStatus: () =>
    apiClient.get<SlBridgeStatus>("/settle/admin/bridge/status").then((r) => r.data),

  /** 导入前预览：先看上游有什么、能不能导，再决定导不导。 */
  bridgePreview: (kind: "designers" | "orders", limit = 20) =>
    apiClient
      .get<SlBridgePreview>("/settle/admin/bridge/preview", { params: { kind, limit } })
      .then((r) => r.data),

  /** 执行导入。幂等 —— 按上游 ID 去重，重复点不会产生第二条。 */
  bridgeImport: (body: {
    kind: "designers" | "orders"
    limit?: number
    only_valid?: boolean
    password?: string
  }) => apiClient.post<SlBridgeImportResult>("/settle/admin/bridge/import", body).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// 设计师端
// ---------------------------------------------------------------------------

export const designerApi = {
  login: (phone: string, password: string) =>
    designerClient
      .post<SlLoginResult>("/auth/login", { phone, password })
      .then((r) => r.data),

  profile: () => designerClient.get<SlProfile>("/me/profile").then((r) => r.data),

  orders: () => designerClient.get<SlOrder[]>("/me/orders").then((r) => r.data),

  settleable: () => designerClient.get<SlSettleableData>("/me/settleable").then((r) => r.data),

  settle: (orderIds: string[]) =>
    designerClient
      .post<SlSettleResult>("/me/settle", { order_ids: orderIds })
      .then((r) => r.data),

  settlements: () => designerClient.get<SlSettlement[]>("/me/settlements").then((r) => r.data),

  changePassword: (oldPassword: string, newPassword: string) =>
    designerClient
      .post<{ ok: boolean }>("/me/password", {
        old_password: oldPassword,
        new_password: newPassword,
      })
      .then((r) => r.data),
}

export { errMsg, errIssues }

/**
 * 取出后端规则层给的**逐字段问题**。
 *
 * 后端 422 的 detail 形如：
 * ```json
 * { "message": "…", "issues": [{"field": "war_zone", "message": "…"}] }
 * ```
 * 通用 errIssues 只做 String()，会把对象变成 "[object Object]" ——
 * 这里专门按 {field, message} 解析成可读的一行行提示。
 */
export function errFieldIssues(
  err: unknown,
): { field: string; message: string }[] {
  const detail = (err as { detail?: unknown } | null | undefined)?.detail
  if (!detail || typeof detail !== "object" || !("issues" in detail)) return []
  const issues = (detail as { issues?: unknown }).issues
  if (!Array.isArray(issues)) return []
  return issues.map((i) => {
    if (i && typeof i === "object" && "message" in i) {
      const o = i as { field?: string; message?: string }
      return { field: String(o.field ?? ""), message: String(o.message ?? "") }
    }
    return { field: "", message: String(i) }
  })
}

/** 把逐字段问题拼成一段可读文字。 */
export function issuesText(err: unknown): string {
  const list = errFieldIssues(err)
  if (list.length === 0) return ""
  return list.map((i) => (i.field ? `【${i.field}】${i.message}` : i.message)).join("；")
}
