import { apiClient } from "./client"
import type {
  Scenario,
  ScenarioBatchResult,
  ScenarioCreate,
  ScenarioUpdate,
} from "../types/api"

export async function listScenarios(): Promise<Scenario[]> {
  const { data } = await apiClient.get<Scenario[]>("/scenarios")
  return data
}

export async function getScenario(id: string): Promise<Scenario> {
  const { data } = await apiClient.get<Scenario>(`/scenarios/${id}`)
  return data
}

export async function createScenario(payload: ScenarioCreate): Promise<Scenario> {
  const { data } = await apiClient.post<Scenario>("/scenarios", payload)
  return data
}

export async function updateScenario(id: string, payload: ScenarioUpdate): Promise<Scenario> {
  const { data } = await apiClient.put<Scenario>(`/scenarios/${id}`, payload)
  return data
}

export async function deleteScenario(id: string): Promise<void> {
  await apiClient.delete(`/scenarios/${id}`)
}

export async function batchCreateScenarios(payload: { scenarios: ScenarioCreate[] }): Promise<ScenarioBatchResult> {
  const { data } = await apiClient.post<ScenarioBatchResult>("/scenarios/batch", payload)
  return data
}
