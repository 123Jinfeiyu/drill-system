// 设计师结算系统 · 类型定义
// 与后端 app/routers/settle.py + app/services/settle_ledger.py 对齐

/** 订单状态机（本地）。9 态里 `rejected`/`canceled` 是支线。 */
export type SlState =
  | "pending_design"
  | "drafting"
  | "finalizing"
  | "pending_audit"
  | "settleable"
  | "settling"
  | "settled"
  | "rejected"
  | "canceled"

export type SlOrderType = "personal" | "internal" | "external"

/** 结算单状态：pending 待打款 / paid 已打款 / invalid 失效 */
export type SlSettlementStatus = "pending" | "paid" | "invalid"

export interface SlDesigner {
  id: string
  /** 有值 = 从总系统导入的；空 = 本地手工录入的 */
  upstream_id?: string
  name: string
  nickname: string
  phone: string
  alipay_account: string
  alipay_name: string
  gender: number
  gender_label: string
  recruitment_source: string
  production_level: string
  /** 课件要求留空，后端强制为空 */
  war_zone: string
  hr_id: string
  must_change_password: boolean
  status: string
  note: string
  created_at: string
  /** 后端顺带挂上的订单数 */
  order_count?: number
}

export interface SlOrder {
  id: string
  /** 有值 = 从总系统导入的；空 = 本地手工登记的 */
  upstream_id?: string
  order_no: string
  customer_id: string
  war_zone: string
  customer_service: string
  designer_id: string | null
  designer_name: string
  order_type: string
  order_type_label: string
  service_type: string
  order_amount: string
  commission_rate: string
  designer_commission: string
  requirement: string
  note?: string
  deliver_date: string
  order_date: string
  state: SlState
  state_label: string
  /** 终稿通过聊天记录截图 */
  chat_screenshot: string
  /** 交付文件截图 */
  file_screenshot: string
  audit_status: string
  audit_remark: string
  created_at: string
  updated_at: string
}

export interface SlSettlement {
  id: string
  order_id: string
  designer_id: string
  designer_name: string
  commission: string
  period: string
  status: SlSettlementStatus
  invalid_reason: string
  alipay_account: string
  alipay_name: string
  pay_date: string
  flow_no: string
  paid_at: string
  created_at: string
}

export interface SlLog {
  id: string
  kind: string
  actor: string
  detail: string
  from_state: string | null
  to_state: string | null
  created_at: string
}

/** 异常诊断的一条。 */
export interface SlIssue {
  code: string
  message: string
  action: string
}

export interface SlOrderDetail {
  order: SlOrder
  logs: SlLog[]
  settlements: SlSettlement[]
  exceptions: SlIssue[]
  deletable: boolean
  delete_reason: string
  next_states: SlState[]
}

export interface SlFunnelRow {
  state: SlState
  label: string
  count: number
  amount: string
}

export interface SlSettleWindow {
  open: boolean
  today: string
  open_days: number[]
  next_open: string
  days_until_open: number
  payout_day: number
  days_until_payout: number
  message: string
}

export interface SlSettlementSummary {
  pending_count: number
  pending_amount: string
  paid_count: number
  paid_amount: string
  invalid_count?: number
  by_designer: { designer_name: string; count: number; amount: string }[]
}

export interface SlReminder {
  designer_id: string
  designer_name: string
  phone: string
  order_count: number
  commission: string
  earliest_order_date: string
  expired: boolean
}

export interface SlDashboard {
  funnel: SlFunnelRow[]
  period: string
  month_order_count: number
  month_amount: string
  month_commission: string
  designer_count: number
  active_designer_count: number
  pending_audit_count: number
  settleable_count: number
  settleable_amount: string
  draft_missing_count: number
  remind_designers: SlReminder[]
  window: SlSettleWindow
  settlement_summary: SlSettlementSummary
}

/** 一键结算页的候选单。 */
export interface SlSettleCandidate {
  order_id: string
  order_no: string
  designer_name: string
  commission: string
  eligible: boolean
  reasons: string[]
}

export interface SlSettleableData {
  window: SlSettleWindow
  eligible: SlSettleCandidate[]
  blocked: SlSettleCandidate[]
  total_commission: string
  count: number
}

export interface SlMeta {
  states: { value: SlState; label: string }[]
  mainline: SlState[]
  transitions: Record<string, SlState[]>
  order_types: { value: SlOrderType; label: string }[]
  production_levels: string[]
  genders: { value: number; label: string }[]
  recruitment_sources: string[]
  commission_rate: { min: string; max: string; text: string }
  settle_valid_days: number
  settle_window_days: number[]
  payout_day: number
  remind_day: number
  exception_cases: { value: string; label: string }[]
  upstream_statuses: { value: number; label: string }[]
  window: SlSettleWindow
}

/** 设计师端登录返回。 */
export interface SlLoginResult {
  designer_id: string
  name: string
  nickname: string
  must_change_password: boolean
  token: string
  token_type: string
}

export interface SlProfile {
  designer_id: string
  name: string
  nickname: string
  must_change_password: boolean
  alipay_account: string
  alipay_name: string
}

/** 一键结算的结果。 */
export interface SlSettleResult {
  created: SlSettlement[]
  skipped: { order_id: string; reason: string }[]
  window: SlSettleWindow
}

/* ---------------------------------------------------------------------------
 * 与总系统（上游）互通
 * ------------------------------------------------------------------------- */

/** 互通状态。 */
export interface SlBridgeStatus {
  /** 是否配了上游账号密码 */
  configured: boolean
  /** 互通模式 —— 永远是「只读 · 单向导入 · 不回写」 */
  mode: string
  /** 给派单员看的提示语 */
  hint: string
  /** 上游能不能连上 */
  reachable?: boolean
  /** 上游设计师总数 */
  designer_total?: number
  /** 连不上时的原因 */
  error?: string
  checked_at?: string
}

/** 预览里的一条设计师。 */
export interface SlBridgeDesignerItem {
  upstream_id: string
  name: string
  nickname: string
  phone: string
  alipay_account: string
  production_level: string
  /** 能不能导（没任何问题） */
  importable: boolean
  /** 有哪些问题 —— 空数组表示没问题 */
  issues: string[]
}

/** 预览里的一条订单。 */
export interface SlBridgeOrderItem {
  upstream_id: string
  order_no: string
  designer_name: string
  order_amount: string
  commission: string
  /** 反推出来的佣金比例 */
  commission_rate: string
  upstream_status: number
  upstream_status_label: string
  local_state: string
  local_state_label: string
  importable: boolean
  issues: string[]
}

export interface SlBridgePreview {
  kind: "designers" | "orders"
  total: number
  items: SlBridgeDesignerItem[] | SlBridgeOrderItem[]
}

/** 导入结果。 */
export interface SlBridgeImportResult {
  kind: string
  created_count: number
  skipped_count: number
  created: Record<string, unknown>[]
  skipped: { upstream_id: string; name?: string; order_no?: string; reason: string }[]
}
