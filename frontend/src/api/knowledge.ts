import { apiClient } from "./client"
import type {
  KnowledgeBatchImportResult,
  KnowledgeImportUrl,
  KnowledgeItem,
  KnowledgeItemCreate,
  KnowledgeItemUpdate,
} from "../types/api"

export async function listKnowledge(): Promise<KnowledgeItem[]> {
  const { data } = await apiClient.get<KnowledgeItem[]>("/knowledge")
  return data
}

export async function createKnowledge(payload: KnowledgeItemCreate): Promise<KnowledgeItem> {
  const { data } = await apiClient.post<KnowledgeItem>("/knowledge", payload)
  return data
}

// 【P4-5 修复】编辑知识条目（后端 PUT /knowledge/{id} 早已存在，前端此前无入口）
export async function updateKnowledge(
  id: string,
  payload: KnowledgeItemUpdate,
): Promise<KnowledgeItem> {
  const { data } = await apiClient.put<KnowledgeItem>(`/knowledge/${id}`, payload)
  return data
}

// 【P4-5 修复】站内搜索：走后端 bigram 召回接口
export async function searchKnowledge(q: string, topK = 20): Promise<KnowledgeItem[]> {
  const { data } = await apiClient.get<KnowledgeItem[]>("/knowledge/search", {
    params: { q, top_k: topK },
  })
  return data
}

export async function deleteKnowledge(id: string): Promise<void> {
  await apiClient.delete(`/knowledge/${id}`)
}

export async function importKnowledgeUrl(payload: KnowledgeImportUrl): Promise<KnowledgeItem> {
  const { data } = await apiClient.post<KnowledgeItem>("/knowledge/import-url", payload)
  return data
}

export async function importKnowledgeUrls(payload: {
  urls: { url: string; title?: string; tags?: string[] }[]
}): Promise<KnowledgeBatchImportResult> {
  const { data } = await apiClient.post<KnowledgeBatchImportResult>("/knowledge/import-urls", payload)
  return data
}
