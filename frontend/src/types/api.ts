// 与后端 app/schemas.py 对齐

export type Role = "student" | "teacher" | "admin"

export type SessionStatus = "pending" | "in_progress" | "finished" | "canceled"

export type MessageRole = "customer" | "student" | "system"

export interface Token {
  access_token: string
  token_type: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  display_name?: string
  role?: Role
}

export interface User {
  id: string
  username: string
  display_name: string
  role: Role
}

export interface Scenario {
  id: string
  code: string
  title: string
  customer_persona: string
  opening: string
  knowledge_points: string[]
  reference_answer: string
  difficulty: number
  max_turns: number
  created_at: string
}

export interface ScenarioCreate {
  code: string
  title: string
  customer_persona: string
  opening: string
  knowledge_points?: string[]
  reference_answer?: string
  difficulty?: number
  max_turns?: number
}

export interface ScenarioBatchResult {
  created: number
  skipped: number
  skipped_codes: string[]
  items: Scenario[]
}

export interface ScenarioUpdate {
  code?: string
  title?: string
  customer_persona?: string
  opening?: string
  knowledge_points?: string[]
  reference_answer?: string
  difficulty?: number
  max_turns?: number
}

export interface DrillSession {
  id: string
  scenario_id: string
  student_id: string
  status: SessionStatus
  current_turn: number
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface DrillRecord {
  id: string
  scenario_id: string
  scenario_title: string
  student_id: string
  student_name?: string
  status: SessionStatus
  current_turn: number
  max_turns: number
  started_at: string | null
  finished_at: string | null
  created_at: string
  has_score: boolean
  total?: number | null
  accuracy?: number | null
  completeness?: number | null
  etiquette?: number | null
  responsiveness?: number | null
  knowledge_use?: number | null
  summary?: string | null
  weak_points?: string[] | null
}

export interface SessionCreate {
  scenario_id: string
}

export interface CustomerReply {
  content: string
  is_finished: boolean
  next_turn: number
}

export interface StudentReply {
  content: string
}

export interface Message {
  id: string
  role: MessageRole
  content: string
  turn: number
  created_at: string
}

export interface Score {
  id: string
  session_id: string
  total: number
  accuracy: number
  completeness: number
  etiquette: number
  responsiveness: number
  knowledge_use: number
  summary: string
  weak_points: string[]
}

export interface ScoreSummary {
  id: string
  session_id: string
  scenario_id: string
  scenario_title: string
  student_id?: string
  student_name?: string
  total: number
  accuracy: number
  completeness: number
  etiquette: number
  responsiveness: number
  knowledge_use: number
  summary: string
  weak_points: string[]
  current_turn: number
  status: SessionStatus
  created_at: string
}

export interface ApiError {
  detail: string
}

// ===== CodexFDE 工作台 =====
export interface FdeProject { id: string; code: string; name: string; purpose: string; path: string; owner_id: string; created_at: string }
export interface FdeProjectCreate { code: string; name: string; purpose?: string; path?: string }
/** L04 状态机位置；queued/rework 也在内，界面按 state 而不是自由字符串渲染 */
export type FdeState = "queued" | "spec_ready" | "executing" | "evaluating" | "review" | "accepted" | "rework" | "canceled"
export type FdeAcceptance = "pending_human_review" | "accepted" | "rejected"
export interface FdeTask {
  id: string; project_id: string; project_name: string; code: string; title: string; request: string
  spec_snapshot: string; spec_hash: string; spec_issues: string[]
  state: FdeState; state_label: string
  acceptance: FdeAcceptance; accepted_by: string | null; accepted_at: string | null
  depends_on: string[]; created_by: string; created_at: string
}
export interface FdeTaskCreate { project_id: string; code: string; title: string; request?: string; spec_snapshot: string; depends_on?: string[] }
export interface FdeEvidence { id: string; task_id: string; phase: "red" | "diff" | "green" | "observation"; command_text: string; output: string; output_hash: string; return_code: number; observed_at: string; created_at: string }
export interface FdeEvidenceCreate { phase: FdeEvidence["phase"]; command_text: string; output: string; return_code: number; observed_at: string }
export interface FdeEvent { id: string; task_id: string; kind: string; from_state: string | null; to_state: string | null; actor: string; detail: string; created_at: string }
/** 资格门禁结论：evidence_complete 与 accepted 是两个独立字段，不得互相顶替 */
export interface FdeGate {
  allowed: boolean; code: number; reason: string; blockers: string[]
  evidence_complete: boolean; accepted: boolean; state: FdeState
}
export interface FdeChain { counts: Record<string, number>; total: number; evidence_complete: boolean; issues: string[] }

/** L10 有界修复回路：只读投影，判定「还能不能继续修」 */
export interface FdeRepairRound {
  round: number
  entered_at: string
  ended_at: string | null
  actor: string
  reason: string
  /** in_rework / verifying / converged / accepted / canceled / failed_again */
  outcome: string
  /** 只有自动复验退回的轮次有结构化原因；人工流转的为 null（不可比） */
  issues: string[] | null
}

export interface FdeRepairLoop {
  max_rounds: number
  rounds: number
  /** ready / continue / verifying / converged / closed / stopped_max_rounds / stopped_no_progress */
  status: string
  reason: string
  can_continue: boolean
  history: FdeRepairRound[]
  handoff: { stop_reason: string; rounds: number; last_issues: string[] | null; next_action: string } | null
}

/** L15 交付摘要：交付四要素（结果/证据/边界/交接）投影 + 可复制的 Markdown */
export interface FdeDeliverySummary {
  converged: boolean
  four: Record<string, Record<string, unknown>>
  markdown: string
}
export interface FdeTaskDetail extends FdeTask {
  evidences: FdeEvidence[]; events: FdeEvent[]
  evidence_complete: boolean; issues: string[]; chain: FdeChain
  gate: FdeGate; next_states: FdeState[]
  blockers_detail: { code: string; exists: boolean; state: FdeState | null; acceptance: FdeAcceptance | null; title: string | null }[]
  repair_loop: FdeRepairLoop
  delivery_summary: FdeDeliverySummary
}
export interface FdeSpecValidate { ok: boolean; issues: string[]; sections: Record<string, string>; missing: string[]; template: string }
export interface FdeMeta {
  spec_sections: string[]
  stages: { key: FdeState; label: string }[]
  transitions: Record<string, string[]>
  terminal_states: string[]
  agent_prefix: string
  evidence_phases: string[]
  event_kinds: string[]
  principle: string
}
export interface FdeLedgerSummary {
  projects: number; tasks: number
  states: Record<string, number>; acceptance: Record<string, number>
  waiting_human_review: { code: string; title: string; created_by: string }[]
  blocked_by_unaccepted_dependency: { code: string; title: string; depends_on: string; dep_state: string | null; dep_acceptance: string | null }[]
  principle: string
}

// ===== Knowledge =====
export interface KnowledgeItem {
  id: string
  title: string
  content: string
  tags: string[]
  source_url: string
  created_at: string
}

export interface KnowledgeItemCreate {
  title: string
  content: string
  tags?: string[]
  source_url?: string
}

// 【P4-5 修复】知识条目编辑：仅传需要修改的字段
export interface KnowledgeItemUpdate {
  title?: string
  content?: string
  tags?: string[]
  source_url?: string
}

export interface KnowledgeImportUrl {
  url: string
  title?: string
  tags?: string[]
}

export interface KnowledgeImportFailure {
  url: string
  error: string
}

export interface KnowledgeBatchImportResult {
  succeeded: number
  failed: number
  failures: KnowledgeImportFailure[]
  items: KnowledgeItem[]
}

// ===== Practice (Q&A 演练场) =====
export interface PracticeCategory {
  key: string
  label: string
  description: string
  tags: string[]
}

export interface PracticeSessionCreate {
  category: string
  difficulty?: number
  max_turns?: number
}

export interface PracticeSession {
  id: string
  student_id: string
  category: string
  difficulty: number
  persona: string
  opening: string
  max_turns: number
  status: SessionStatus
  current_turn: number
  /** 会话来源：practice=演练场打字练习；live_sim=模拟进线（点话术回复客户） */
  channel: "practice" | "live_sim"
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface PracticeReplyOut {
  content: string
  is_finished: boolean
  next_turn: number
}

/** 演练场/模拟通话的消息（后端 PracticeMessageOut） */
export interface PracticeMessage {
  id: string
  role: MessageRole
  content: string
  turn: number
  /** 坐席点话术回复时记录的话术 id；自由输入/客户消息为 null */
  script_id: string | null
  /** script=点话术回复；free=自由输入；auto=AI 客户 */
  via: string
  created_at: string
}

export interface PracticeReplyCreate {
  content: string
}

export interface PracticeScore {
  id: string
  session_id: string
  total: number
  accuracy: number
  completeness: number
  etiquette: number
  responsiveness: number
  knowledge_use: number
  summary: string
  weak_points: string[]
  suggestions: string
  business_summary?: string
}

export interface PracticeHint {
  title: string
  content: string
  tags: string[]
}

export interface PracticeScoreSummary {
  id: string
  session_id: string
  category: string
  student_id?: string
  student_name?: string
  total: number
  accuracy: number
  completeness: number
  etiquette: number
  responsiveness: number
  knowledge_use: number
  summary: string
  weak_points: string[]
  suggestions: string
  business_summary?: string
  current_turn: number
  status: SessionStatus
  created_at: string
}

// ===== 实战话术（坐席接听真实来电时的辅助面板）=====
export type LivePhaseKey = "opening" | "support" | "business" | "closing"

/** 音频来源：file = 磁盘上的专业录音；record = 系统内当场录的；tts = 没录音，前端实时合成兜底 */
export type LiveAudioStatus = "file" | "record" | "tts"

export interface LivePhase {
  key: LivePhaseKey
  label: string
  scene_count: number
}

export interface LiveScriptItem {
  id: string
  scene_id: string
  /** 快捷码，同时也是录音文件名（audio/live/<code>.mp3） */
  code: string
  /** 可读短标题（业务话术库的「问题场景」；快捷码库为空） */
  label: string
  text: string
  auto_play: boolean
  sort_order: number
  /** 「常用」标签：进场模式为 auto 的场景，进场自动播打这个标签的第一条 */
  is_common: boolean
  /** 手动排序位（Top1/Top2…）；null = 没排过，按热度排 */
  manual_rank: number | null
  tags: string[]
  use_count: number
  audio_status: LiveAudioStatus
  /** 有没有声音可用（file 或 record 都为真）。界面按这个决定「录音 / 合成」标记 */
  has_audio: boolean
  audio_url: string | null
  audio_name: string
  /** 当场录音的元信息（专业录音为 0 / 空串） */
  recording_size: number
  recording_duration_ms: number
  recorded_by: string
  recorded_at: string
  /** 仅搜索结果带回 */
  scene_name?: string
}

export interface LiveScene {
  id: string
  code: string
  name: string
  phase: LivePhaseKey
  source: "quick" | "business" | "faq"
  description: string
  sort_order: number
  pinned: boolean
  /** 进场模式：silent 进场不出声（默认）；auto 进场自动播「常用」第一条 */
  entry_mode: "auto" | "silent"
  script_count: number
  recorded_count: number
  scripts: LiveScriptItem[]
}

export interface LiveBootstrap {
  phases: LivePhase[]
  scenes: LiveScene[]
  script_total: number
  recorded_total: number
  audio_enabled: boolean
  tts_fallback: boolean
}

export interface LiveAudioGap {
  code: string
  scene_name: string
  label: string
  text: string
  use_count: number
  reason: "missing" | "override"
}

export interface LiveAudioIndex {
  scenes: number
  scripts: number
  recorded: number
  /** 其中来自磁盘专业录音 / 系统内当场录音的条数 */
  recorded_from_file: number
  recorded_from_db: number
  pending_recording: number
  audio_dir: string
  total: number
  missing: number
  override_broken: number
  items: LiveAudioGap[]
}

// ===== 模拟进线（模拟客户来电，坐席点话术回复）=====
/** 挂断后的话术小结：这通电话用了哪些话术（audio 字段即完整话术条目，可直接播放） */
export interface LiveCallScriptsSummary {
  used_count: number
  scripts: LiveScriptItem[]
}
