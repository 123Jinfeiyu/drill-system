// 设计师结算系统 · 共享小工具
//
// 只有「展示层」的东西放这里 —— 状态颜色、金额格式化。
// **任何业务判断都不许写在这里**，规则一律在后端 settle_ledger 里，
// 前端只负责把后端给的结论显示出来。

import type { SlState } from "../types/settle"

/** 状态 → 标签颜色。纯展示。 */
export const STATE_COLOR: Record<string, string> = {
  pending_design: "default",
  drafting: "blue",
  finalizing: "cyan",
  pending_audit: "orange",
  settleable: "green",
  settling: "gold",
  settled: "purple",
  rejected: "red",
  canceled: "default",
}

/** 结算单状态 → 标签颜色。 */
export const SETTLE_STATUS_COLOR: Record<string, string> = {
  pending: "orange",
  paid: "green",
  invalid: "red",
}

/** 结算单状态 → 中文。 */
export const SETTLE_STATUS_LABEL: Record<string, string> = {
  pending: "待打款",
  paid: "已打款",
  invalid: "已失效",
}

/** 留痕类型 → 中文。 */
export const LOG_KIND_LABEL: Record<string, string> = {
  designer: "设计师",
  order: "订单",
  transition: "流转",
  audit: "审核",
  settle: "结算",
}

/** 金额加千分位。后端给的是字符串，前端只做展示格式化，不改值。 */
export function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return "0.00"
  return n.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** 佣金比例 → 百分比文本。后端给的是小数（0.6）。 */
export function percent(rate: string | number | null | undefined): string {
  const n = Number(rate ?? 0)
  if (!Number.isFinite(n)) return "0%"
  return `${(n * 100).toFixed(1).replace(/\.0$/, "")}%`
}

/** 状态文字回退：后端给了 label 就用，没给就自己查。 */
export function stateLabel(state: SlState | string, label?: string): string {
  return label || state
}
