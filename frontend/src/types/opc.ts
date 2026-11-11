// OPC 一人公司系统 · 类型定义
// 与后端 app/schemas_opc.py 对齐

export type OpcState =
  | "pending_assign"
  | "assigned"
  | "taken"
  | "drafting"
  | "finalizing"
  | "pending_review"
  | "delivered"
  | "pending_settle"
  | "settled"
  | "canceled"

export type OpcPhase = "red" | "diff" | "green" | "observation"

export type OpcAcceptance = "pending_human_review" | "accepted" | "rejected"

export type OpcScope =
  | "designer"
  | "hr"
  | "quality_control"
  | "supervisor"
  | "control"

export interface OpcOrder {
  id: string
  order_sn: string
  title: string
  store_name: string
  designer_name: string
  order_grade: string
  order_type: string
  order_commission: string
  request_delivery_time: string
  state: OpcState
  state_label: string
  acceptance: OpcAcceptance
  spec_issues: string[]
  created_at?: string | null
  updated_at?: string | null
}

export interface OpcDelivery {
  id: string
  phase: OpcPhase
  phase_label: string
  command_text: string
  output: string
  return_code: number
  observed_at?: string | null
}

export interface OpcEvent {
  id: string
  kind: string
  from_state?: string | null
  to_state?: string | null
  actor: string
  detail: string
  created_at?: string | null
}

export interface OpcGate {
  allowed: boolean
  code: number
  reason: string
  blockers: string[]
  evidence_complete: boolean
  accepted: boolean
  state: string
}

export interface OpcRepairLoop {
  max_rounds: number
  rounds: number
  status: string
  reason: string
  can_continue: boolean
  history: {
    round: number
    entered_at: string
    ended_at: string | null
    actor: string
    reason: string
    outcome: string
    issues: string[] | null
  }[]
  handoff: {
    stop_reason: string
    rounds: number
    last_issues: string[] | null
    next_action: string
  } | null
}

export interface OpcOrderDetail {
  order: OpcOrder
  spec_snapshot: string
  deliveries: OpcDelivery[]
  events: OpcEvent[]
  chain: {
    counts: Record<string, number>
    total: number
    evidence_complete: boolean
    issues: string[]
  }
  gate: OpcGate
  repair_loop: OpcRepairLoop
  summary: {
    converged: boolean
    four: Record<string, Record<string, unknown>>
    markdown: string
    money: OpcMoneyRow[]
  }
  split: Record<string, unknown>
  money: OpcMoneyRow[]
}

export interface OpcMoneyRow {
  scope: string
  label: string
  amount: string
  rate: string
  percent: string
}

export interface OpcDesigner {
  id: string
  name: string
  phone: string
  alipay_account: string
  alipay_name: string
  production_level: string
  design_tags: string
  war_zone: string
  hr_id: string
  quality_control_id: string
  commission_rate: string
  status: string
  note: string
  order_count: number
  active_count: number
}

export interface OpcStore {
  id: string
  name: string
  url: string
  customer_name: string
  manager: string
  commission: string
  settlement_days: number
  remark: string
  order_count: number
}

export interface OpcSettlement {
  id: string
  order_id: string
  order_sn: string
  designer_name: string
  commission: string
  settlement_type: string
  settlement_days: number
  status: string
  alipay_account: string
  alipay_name: string
  upstream_settlement_time: string
  paid_at?: string | null
  paid_by?: string | null
  remark: string
  created_at?: string | null
}

export interface OpcSplitRule {
  id: string
  scope: OpcScope | string
  scope_label: string
  rate: string
  basis: string
  enabled: boolean
  remark: string
}

export interface OpcCandidate {
  designer_id: string
  name: string
  score: number
  design_tags?: string
  production_level?: string
  reason?: string
}

export interface OpcMatchBoard {
  pending: OpcOrder[]
  active: OpcOrder[]
  pending_review: OpcOrder[]
  pending_settle: OpcOrder[]
  designers: OpcDesigner[]
  recommendation: string
}

export interface OpcDashboard {
  funnel: {
    state: string
    label: string
    count: number
    amount: string
  }[]
  total_orders: number
  total_amount: string
  active_amount: string
  pending_settle_amount: string
  designer_count: number
  store_count: number
  settlement_pending_count: number
  settlement_paid_amount: string
  designer_ranking: { name: string; amount: string; count: number }[]
  store_ranking: { name: string; amount: string; count: number }[]
}

export interface OpcMeta {
  states: { value: OpcState; label: string }[]
  mainline: OpcState[]
  /** 每个状态允许去的状态。状态机的唯一来源在后端，前端只读不算。 */
  transitions: Record<string, OpcState[]>
  scope_labels: Record<string, string>
  phase_labels: Record<string, string>
  spec_template: string
  spec_sections: string[]
}

export interface OpcSpecValidate {
  ok: boolean
  issues: string[]
}

export interface OpcSettlementSummary {
  pending_count: number
  pending_amount: string
  paid_count: number
  paid_amount: string
  by_designer: { designer_name: string; count: number; amount: string }[]
}
