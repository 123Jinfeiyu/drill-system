import { apiClient } from "./client"
import type {
  LiveCallScriptsSummary,
  PracticeMessage,
  PracticeReplyOut,
  PracticeSession,
} from "../types/api"

/**
 * 模拟客户进线（/api/live/calls）。
 *
 * 与演练场共用 PracticeSession 存储（channel=live_sim 区分），所以这里的
 * 会话/消息类型直接复用演练场的类型；「点话术 = 回复客户」是它独有的动作。
 */

export interface SimulateCallInput {
  /** 留空由后端随机挑一个品类 */
  category?: string
  difficulty?: number
}

/** 模拟一通来电：生成客户人设 + 开场白（还没接，等坐席点接听）。 */
export async function simulateCall(payload: SimulateCallInput = {}): Promise<PracticeSession> {
  const { data } = await apiClient.post<PracticeSession>("/live/calls/simulate", {
    difficulty: payload.difficulty ?? 2,
    ...(payload.category ? { category: payload.category } : {}),
  })
  return data
}

/** 我的模拟通话记录（新→旧）。 */
export async function listMyCalls(limit = 50): Promise<PracticeSession[]> {
  const { data } = await apiClient.get<PracticeSession[]>("/live/calls", { params: { limit } })
  return data
}

/** 接听：待接听 → 通话中，客户开场白进入对话流。 */
export async function answerCall(callId: string): Promise<PracticeReplyOut> {
  const { data } = await apiClient.post<PracticeReplyOut>(`/live/calls/${callId}/answer`)
  return data
}

/** 一通通话的完整对话记录（接听后拉取开场白；回放也用它）。 */
export async function getCallTranscript(callId: string): Promise<PracticeMessage[]> {
  const { data } = await apiClient.get<PracticeMessage[]>(`/live/calls/${callId}`)
  return data
}

/** 点话术 = 回复客户：话术正文作为坐席发言，AI 客户接着说。 */
export async function useScriptReply(callId: string, scriptId: string): Promise<PracticeReplyOut> {
  const { data } = await apiClient.post<PracticeReplyOut>(`/live/calls/${callId}/use-script`, {
    script_id: scriptId,
  })
  return data
}

/** 自由输入回复：话术覆盖不了客户问题时自己说。 */
export async function freeReply(callId: string, content: string): Promise<PracticeReplyOut> {
  const { data } = await apiClient.post<PracticeReplyOut>(`/live/calls/${callId}/free-reply`, {
    content,
  })
  return data
}

/** 挂断通话。 */
export async function hangupCall(callId: string): Promise<PracticeSession> {
  const { data } = await apiClient.post<PracticeSession>(`/live/calls/${callId}/hangup`)
  return data
}

/** 这通电话用了哪些话术（挂断后的小结，纯本地统计）。 */
export async function getCallScriptsSummary(callId: string): Promise<LiveCallScriptsSummary> {
  const { data } = await apiClient.get<LiveCallScriptsSummary>(`/live/calls/${callId}/scripts-summary`)
  return data
}
