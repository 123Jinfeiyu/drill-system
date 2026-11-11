import { apiClient } from "./client"
import type {
  PracticeCategory,
  PracticeHint,
  PracticeReplyCreate,
  PracticeReplyOut,
  PracticeScore,
  PracticeScoreSummary,
  PracticeSession,
  PracticeSessionCreate,
  Message,
} from "../types/api"

export async function getCategories(): Promise<PracticeCategory[]> {
  const { data } = await apiClient.get<PracticeCategory[]>("/practice/categories")
  return data
}

export async function createPracticeSession(payload: PracticeSessionCreate): Promise<PracticeSession> {
  const { data } = await apiClient.post<PracticeSession>("/practice/sessions", payload)
  return data
}

export async function listMyPracticeSessions(): Promise<PracticeSession[]> {
  const { data } = await apiClient.get<PracticeSession[]>("/practice/sessions")
  return data
}

export async function getPracticeSession(id: string): Promise<PracticeSession> {
  const { data } = await apiClient.get<PracticeSession>(`/practice/sessions/${id}`)
  return data
}

export async function startPracticeSession(id: string): Promise<PracticeReplyOut> {
  const { data } = await apiClient.post<PracticeReplyOut>(`/practice/sessions/${id}/start`)
  return data
}

export async function replyPracticeSession(
  id: string,
  payload: PracticeReplyCreate,
): Promise<PracticeReplyOut> {
  const { data } = await apiClient.post<PracticeReplyOut>(`/practice/sessions/${id}/reply`, payload)
  return data
}

export async function listPracticeMessages(id: string): Promise<Message[]> {
  const { data } = await apiClient.get<Message[]>(`/practice/sessions/${id}/messages`)
  return data
}

export async function getPracticeScore(id: string): Promise<PracticeScore> {
  const { data } = await apiClient.get<PracticeScore>(`/practice/sessions/${id}/score`)
  return data
}

export async function scorePracticeSession(id: string): Promise<PracticeScore> {
  const { data } = await apiClient.post<PracticeScore>(`/practice/sessions/${id}/score`)
  return data
}

// 【P4-3 修复】放弃演练（仅属主）
export async function cancelPracticeSession(id: string): Promise<PracticeSession> {
  const { data } = await apiClient.post<PracticeSession>(`/practice/sessions/${id}/cancel`)
  return data
}

export async function getPracticeHints(id: string): Promise<PracticeHint[]> {
  const { data } = await apiClient.get<PracticeHint[]>(`/practice/sessions/${id}/hints`)
  return data
}

export async function myPracticeScores(): Promise<PracticeScoreSummary[]> {
  const { data } = await apiClient.get<PracticeScoreSummary[]>("/practice/scores/me")
  return data
}

export async function allPracticeScores(): Promise<PracticeScoreSummary[]> {
  const { data } = await apiClient.get<PracticeScoreSummary[]>("/practice/scores/all")
  return data
}
