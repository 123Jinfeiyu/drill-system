import { apiClient } from "./client"
import type {
  CustomerReply,
  DrillRecord,
  DrillSession,
  Message,
  PracticeHint,
  Score,
  ScoreSummary,
  SessionCreate,
  StudentReply,
} from "../types/api"

export async function createSession(payload: SessionCreate): Promise<DrillSession> {
  const { data } = await apiClient.post<DrillSession>("/sessions", payload)
  return data
}

export async function listMySessions(): Promise<DrillSession[]> {
  const { data } = await apiClient.get<DrillSession[]>("/sessions")
  return data
}

export async function myScores(): Promise<ScoreSummary[]> {
  const { data } = await apiClient.get<ScoreSummary[]>("/sessions/scores/me")
  return data
}

export async function allScores(): Promise<ScoreSummary[]> {
  const { data } = await apiClient.get<ScoreSummary[]>("/sessions/scores/all")
  return data
}

export async function myDrillRecords(): Promise<DrillRecord[]> {
  const { data } = await apiClient.get<DrillRecord[]>("/sessions/records")
  return data
}

export async function allDrillRecords(): Promise<DrillRecord[]> {
  const { data } = await apiClient.get<DrillRecord[]>("/sessions/records/all")
  return data
}

export async function getSessionHints(id: string): Promise<PracticeHint[]> {
  const { data } = await apiClient.get<PracticeHint[]>(`/sessions/${id}/hints`)
  return data
}

export async function getSession(id: string): Promise<DrillSession> {
  const { data } = await apiClient.get<DrillSession>(`/sessions/${id}`)
  return data
}

export async function getScore(id: string): Promise<Score> {
  const { data } = await apiClient.get<Score>(`/sessions/${id}/score`)
  return data
}

export async function startSession(id: string): Promise<CustomerReply> {
  const { data } = await apiClient.post<CustomerReply>(`/sessions/${id}/start`)
  return data
}

export async function replySession(id: string, payload: StudentReply): Promise<CustomerReply> {
  const { data } = await apiClient.post<CustomerReply>(`/sessions/${id}/reply`, payload)
  return data
}

export async function scoreSession(id: string): Promise<Score> {
  const { data } = await apiClient.post<Score>(`/sessions/${id}/score`)
  return data
}

// 【P4-3 修复】放弃演练（仅属主）
export async function cancelSession(id: string): Promise<DrillSession> {
  const { data } = await apiClient.post<DrillSession>(`/sessions/${id}/cancel`)
  return data
}

export async function listMessages(id: string): Promise<Message[]> {
  const { data } = await apiClient.get<Message[]>(`/sessions/${id}/messages`)
  return data
}
