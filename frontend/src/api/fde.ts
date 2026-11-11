import { apiClient } from "./client"
import type {
  FdeEvidence, FdeEvidenceCreate, FdeGate, FdeLedgerSummary, FdeMeta,
  FdeProject, FdeProjectCreate, FdeSpecValidate, FdeTask, FdeTaskCreate, FdeTaskDetail,
} from "../types/api"

/** CodexFDE 工作台接口。所有判定都在服务端，前端只负责呈现与发起动作。 */
export const fdeApi = {
  meta: async () => (await apiClient.get<FdeMeta>("/fde/meta")).data,

  listProjects: async () => (await apiClient.get<FdeProject[]>("/fde/projects")).data,
  createProject: async (payload: FdeProjectCreate) => (await apiClient.post<FdeProject>("/fde/projects", payload)).data,

  listTasks: async () => (await apiClient.get<FdeTask[]>("/fde/tasks")).data,
  createTask: async (payload: FdeTaskCreate) => (await apiClient.post<FdeTask>("/fde/tasks", payload)).data,
  getTask: async (id: string) => (await apiClient.get<FdeTaskDetail>(`/fde/tasks/${id}`)).data,
  addEvidence: async (id: string, payload: FdeEvidenceCreate) =>
    (await apiClient.post<FdeEvidence>(`/fde/tasks/${id}/evidences`, payload)).data,

  /** 需求入口：结构不合格就当场列清缺哪一节，不静默放行。 */
  validateSpec: async (spec_snapshot: string) =>
    (await apiClient.post<FdeSpecValidate>("/fde/specs/validate", { spec_snapshot })).data,

  /** 只读门禁：不改状态，用来在动手之前先看会不会被拦。 */
  gate: async (id: string) => (await apiClient.get<FdeGate>(`/fde/tasks/${id}/gate`)).data,

  /** 受控流转：跳阶段会被服务端拒绝（409）。 */
  transition: async (id: string, target: string, note = "") =>
    (await apiClient.post<FdeTaskDetail>(`/fde/tasks/${id}/transition`, { target, note })).data,

  /** 自动复验：按已有证据判定，完整则待人审，不完整则返工。不重跑命令。 */
  evaluate: async (id: string) => (await apiClient.post<FdeTaskDetail>(`/fde/tasks/${id}/evaluate`)).data,

  /** 人工接受：构建者以外的人具名签收，程序不代签。 */
  accept: async (id: string, note = "") =>
    (await apiClient.post<FdeTaskDetail>(`/fde/tasks/${id}/accept`, { note })).data,

  summary: async () => (await apiClient.get<FdeLedgerSummary>("/fde/ledger/summary")).data,
}
