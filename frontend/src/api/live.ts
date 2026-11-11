import { apiClient, getToken } from "./client"
import type { LiveAudioIndex, LiveBootstrap, LiveScene, LiveScriptItem } from "../types/api"

/** 实战面板一次性拉全量：接起电话那一刻多一次往返就是当场听得见的卡顿。 */
export async function fetchBootstrap(): Promise<LiveBootstrap> {
  const { data } = await apiClient.get<LiveBootstrap>("/live/bootstrap")
  return data
}

/**
 * 把服务端给的 audio_url 变成 ``<audio src>`` 能直接用的地址。
 *
 * 磁盘录音走静态目录（``/audio/live/xx.mp3``，本来就不需要令牌）；
 * 库内录音走后端接口，而 ``<audio>`` 标签**带不了请求头**，只能把 JWT 挂查询参数上。
 * 这是全项目唯一为「浏览器原生播放器」开的口子，其余接口仍旧只认 Authorization 头。
 */
export function playableAudioUrl(item: LiveScriptItem): string | null {
  if (!item.audio_url) return null
  if (!item.audio_url.startsWith("/api/")) return item.audio_url
  const token = getToken()
  if (!token) return item.audio_url
  return `${item.audio_url}?token=${encodeURIComponent(token)}`
}

export async function listScenes(): Promise<LiveScene[]> {
  const { data } = await apiClient.get<LiveScene[]>("/live/scenes")
  return data
}

/** 按快捷码 / 标题 / 正文 / 场景名搜索。坐席主要输快捷码（如 hy2）。 */
export async function searchLiveScripts(q: string, limit = 30): Promise<LiveScriptItem[]> {
  const { data } = await apiClient.get<LiveScriptItem[]>("/live/search", { params: { q, limit } })
  return data
}

/** 播放时上报一次使用，高频话术会因此在待录音清单里排前面。 */
export async function markScriptUsed(id: string): Promise<LiveScriptItem> {
  const { data } = await apiClient.post<LiveScriptItem>(`/live/scripts/${id}/use`)
  return data
}

export async function toggleScenePin(sceneId: string): Promise<LiveScene> {
  const { data } = await apiClient.post<LiveScene>(`/live/scenes/${sceneId}/pin`)
  return data
}

/** 切换场景进场模式：silent 进场不出声；auto 进场自动播「常用」第一条。 */
export async function setSceneEntryMode(sceneId: string, mode: "auto" | "silent"): Promise<LiveScene> {
  const { data } = await apiClient.post<LiveScene>(`/live/scenes/${sceneId}/entry-mode`, { mode })
  return data
}

/** 打/摘「常用」标签。任何登录用户都能操作——这是坐席自己的面板。 */
export async function setScriptCommon(id: string, isCommon: boolean): Promise<LiveScriptItem> {
  const { data } = await apiClient.post<LiveScriptItem>(`/live/scripts/${id}/common`, {
    is_common: isCommon,
  })
  return data
}

/**
 * 手动排序（Top1/Top2…）：position 1 起插进 Top 榜；0 = 退出 Top 榜回热度序。
 * 返回整个场景——位次变动会波及同场景其他话术的展示顺序。
 */
export async function reorderScript(id: string, position: number): Promise<LiveScene> {
  const { data } = await apiClient.post<LiveScene>(`/live/scripts/${id}/reorder`, { position })
  return data
}

/** 待录音清单 + 录音进度（给录音同事排期用）。 */
export async function fetchAudioIndex(): Promise<LiveAudioIndex> {
  const { data } = await apiClient.get<LiveAudioIndex>("/live/audio-index")
  return data
}

export async function updateLiveScript(
  id: string,
  payload: { text?: string; label?: string; code?: string; auto_play?: boolean },
): Promise<LiveScriptItem> {
  const { data } = await apiClient.put<LiveScriptItem>(`/live/scripts/${id}`, payload)
  return data
}

/** 新增一条话术。code 留空由后端自动生成不冲突的快捷码。 */
export async function createLiveScript(
  sceneId: string,
  payload: { code?: string; label: string; text: string; auto_play?: boolean },
): Promise<LiveScriptItem> {
  const { data } = await apiClient.post<LiveScriptItem>(`/live/scenes/${sceneId}/scripts`, {
    scene_id: sceneId,
    code: payload.code ?? "",
    label: payload.label,
    text: payload.text,
    auto_play: payload.auto_play ?? false,
  })
  return data
}

/** 删除话术（连带清掉它的现场录音）。后端对登录用户开放，前端有二次确认。 */
export async function deleteLiveScript(id: string): Promise<void> {
  await apiClient.delete(`/live/scripts/${id}`)
}

/** 按 MIME 起个像样的文件名——服务端只把它当 fallback，真正生效的是 content-type。 */
function recordingFilename(mime: string): string {
  const bare = mime.split(";")[0].trim().toLowerCase()
  const ext =
    { "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav" }[
      bare
    ] ?? "webm"
  return `recording.${ext}`
}

/** 上传（或覆盖）一条当场录音。任何登录用户都能录——见后端 live.py 的说明。 */
export async function uploadRecording(
  scriptId: string,
  blob: Blob,
  durationMs: number,
): Promise<LiveScriptItem> {
  const form = new FormData()
  // 第三个参数是文件名。不能手写 Content-Type，要让 axios 自己带 boundary。
  form.append("file", blob, recordingFilename(blob.type))
  form.append("duration_ms", String(Math.max(0, Math.round(durationMs))))
  const { data } = await apiClient.post<LiveScriptItem>(`/live/scripts/${scriptId}/audio`, form)
  return data
}

/** 删掉当场录音。上传者本人或讲师可以删。 */
export async function deleteRecording(scriptId: string): Promise<void> {
  await apiClient.delete(`/live/scripts/${scriptId}/audio`)
}
