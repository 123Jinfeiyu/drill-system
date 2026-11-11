// OPC 一人公司系统 · API 封装
//
// 约定（照搬 FDE 的 api/client.ts）：所有请求走 apiClient，不在页面里裸写 axios。
import { apiClient, errIssues, errMsg } from "./client"
import type {
  OpcDashboard,
  OpcDesigner,
  OpcMatchBoard,
  OpcMeta,
  OpcOrder,
  OpcOrderDetail,
  OpcSettlement,
  OpcSettlementSummary,
  OpcSpecValidate,
  OpcSplitRule,
  OpcStore,
} from "../types/opc"

export const opcApi = {
  // ---------- 元信息 ----------
  meta: () => apiClient.get<OpcMeta>("/opc/meta").then((r) => r.data),

  // ---------- 需求单 ----------
  validateSpec: (specSnapshot: string) =>
    apiClient
      .post<OpcSpecValidate>("/opc/orders/specs/validate", {
        spec_snapshot: specSnapshot,
      })
      .then((r) => r.data),

  // ---------- 订单 ----------
  listOrders: (params?: {
    state?: string
    designer?: string
    store?: string
    keyword?: string
  }) =>
    apiClient.get<OpcOrder[]>("/opc/orders", { params }).then((r) => r.data),

  createOrder: (body: Record<string, unknown>) =>
    apiClient.post<OpcOrder>("/opc/orders", body).then((r) => r.data),

  getOrder: (id: string) =>
    apiClient.get<OpcOrderDetail>(`/opc/orders/${id}`).then((r) => r.data),

  editOrder: (id: string, body: Record<string, unknown>) =>
    apiClient.patch<OpcOrder>(`/opc/orders/${id}`, body).then((r) => r.data),

  deleteOrder: (id: string) =>
    apiClient.delete(`/opc/orders/${id}`).then((r) => r.data),

  assign: (id: string, designerId: string, detail = "") =>
    apiClient
      .post<OpcOrderDetail>(`/opc/orders/${id}/assign`, {
        designer_id: designerId,
        detail,
      })
      .then((r) => r.data),

  claim: (id: string, designerId: string, detail = "") =>
    apiClient
      .post<OpcOrderDetail>(`/opc/orders/${id}/claim`, {
        designer_id: designerId,
        detail,
      })
      .then((r) => r.data),

  addDelivery: (
    id: string,
    body: {
      phase: string
      command_text: string
      output: string
      return_code: number
    },
  ) =>
    apiClient
      .post<OpcOrderDetail>(`/opc/orders/${id}/deliveries`, body)
      .then((r) => r.data),

  evaluate: (id: string) =>
    apiClient.post<OpcOrderDetail>(`/opc/orders/${id}/evaluate`).then((r) => r.data),

  transition: (id: string, toState: string, detail = "") =>
    apiClient
      .post<OpcOrderDetail>(`/opc/orders/${id}/transition`, {
        to_state: toState,
        detail,
      })
      .then((r) => r.data),

  accept: (id: string, actor: string, note = "") =>
    apiClient
      .post<OpcOrderDetail>(`/opc/orders/${id}/accept`, { actor, note })
      .then((r) => r.data),

  gate: (id: string) =>
    apiClient.get<OpcOrderDetail["gate"]>(`/opc/orders/${id}/gate`).then((r) => r.data),

  repairLoop: (id: string) =>
    apiClient
      .get<OpcOrderDetail["repair_loop"]>(`/opc/orders/${id}/repair-loop`)
      .then((r) => r.data),

  summary: (id: string) =>
    apiClient
      .get<OpcOrderDetail["summary"]>(`/opc/orders/${id}/summary`)
      .then((r) => r.data),

  // ---------- 设计师 ----------
  listDesigners: (status?: string) =>
    apiClient.get<OpcDesigner[]>("/opc/designers", { params: { status } }).then((r) => r.data),

  createDesigner: (body: Record<string, unknown>) =>
    apiClient.post<OpcDesigner>("/opc/designers", body).then((r) => r.data),

  editDesigner: (id: string, body: Record<string, unknown>) =>
    apiClient.patch<OpcDesigner>(`/opc/designers/${id}`, body).then((r) => r.data),

  deleteDesigner: (id: string) =>
    apiClient.delete(`/opc/designers/${id}`).then((r) => r.data),

  // ---------- 店铺 ----------
  listStores: () => apiClient.get<OpcStore[]>("/opc/stores").then((r) => r.data),

  createStore: (body: Record<string, unknown>) =>
    apiClient.post<OpcStore>("/opc/stores", body).then((r) => r.data),

  editStore: (id: string, body: Record<string, unknown>) =>
    apiClient.patch<OpcStore>(`/opc/stores/${id}`, body).then((r) => r.data),

  deleteStore: (id: string) =>
    apiClient.delete(`/opc/stores/${id}`).then((r) => r.data),

  // ---------- 撮合 ----------
  matchBoard: () => apiClient.get<OpcMatchBoard>("/opc/match/board").then((r) => r.data),

  recommend: (orderId: string) =>
    apiClient
      .get<{
        order_id: string
        requirement: string
        candidates: {
          designer_id: string
          name: string
          score: number
          design_tags?: string
          production_level?: string
          reason?: string
        }[]
        reason: string
        source: string
      }>(`/opc/match/recommend`, { params: { order_id: orderId } })
      .then((r) => r.data),

  // ---------- 结算 ----------
  listSettlements: (status?: string) =>
    apiClient
      .get<OpcSettlement[]>("/opc/settlements", { params: { status } })
      .then((r) => r.data),

  generateSettlements: (orderIds: string[] = []) =>
    apiClient
      .post<{ created: OpcSettlement[]; skipped: { order_sn: string; reason: string }[] }>(
        "/opc/settlements/generate",
        { order_ids: orderIds },
      )
      .then((r) => r.data),

  paySettlement: (id: string, body: { actor?: string; upstream_settlement_time?: string; remark?: string }) =>
    apiClient.post<OpcSettlement>(`/opc/settlements/${id}/pay`, body).then((r) => r.data),

  settlementSummary: () =>
    apiClient.get<OpcSettlementSummary>("/opc/settlements/summary").then((r) => r.data),

  // ---------- 分账规则 ----------
  listRules: () => apiClient.get<OpcSplitRule[]>("/opc/rules").then((r) => r.data),

  saveRule: (body: Record<string, unknown>) =>
    apiClient.post<OpcSplitRule>("/opc/rules", body).then((r) => r.data),

  deleteRule: (id: string) =>
    apiClient.delete(`/opc/rules/${id}`).then((r) => r.data),

  previewSplit: (total: string, basis?: string) =>
    apiClient
      .post<{
        total: string
        basis: string
        rows: { scope: string; label: string; amount: string; rate: string; percent: string }[]
        issues: string[]
      }>("/opc/rules/preview", { total, basis })
      .then((r) => r.data),

  // ---------- 看板 ----------
  dashboard: () => apiClient.get<OpcDashboard>("/opc/dashboard").then((r) => r.data),
}

export { errMsg, errIssues }
