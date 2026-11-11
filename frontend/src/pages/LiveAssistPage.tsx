import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Slider,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
  theme,
} from "antd"
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  AudioOutlined,
  ClockCircleOutlined,
  CopyOutlined,
  DeleteOutlined,
  FileTextOutlined,
  PauseCircleOutlined,
  PhoneOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  StarFilled,
  StarOutlined,
  StopOutlined,
} from "@ant-design/icons"
import { useNavigate } from "react-router-dom"
import * as liveApi from "../api/live"
import { errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import LiveScriptManager from "../components/LiveScriptManager"
import type { LiveAudioIndex, LiveBootstrap, LivePhaseKey, LiveScene, LiveScriptItem } from "../types/api"
import { releaseTts, speak, stopSpeaking, ttsSupported } from "../utils/tts"
import { recordingSupported, startRecording } from "../utils/recorder"
import type { RecordingSession } from "../utils/recorder"

const PHASE_COLOR: Record<LivePhaseKey, string> = {
  opening: "blue",
  support: "green",
  business: "orange",
  closing: "purple",
}

const SOURCE_LABEL: Record<LiveScene["source"], string> = {
  quick: "快捷码库",
  business: "业务应答库",
  faq: "常见问题",
}

/** 录音来源标记：磁盘专业录音 / 系统内当场录的 / 都没有（用合成） */
const AUDIO_TAG: Record<string, { color: string; label: string }> = {
  file: { color: "green", label: "专业录音" },
  record: { color: "cyan", label: "现场录音" },
  tts: { color: "gold", label: "合成" },
}

function fmtSize(bytes: number): string {
  if (!bytes) return ""
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fmtClock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

/** 剪贴板兜底：非安全上下文里 navigator.clipboard 可能不可用。 */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const area = document.createElement("textarea")
      area.value = text
      area.style.position = "fixed"
      area.style.opacity = "0"
      document.body.appendChild(area)
      area.select()
      const ok = document.execCommand("copy")
      document.body.removeChild(area)
      return ok
    } catch {
      return false
    }
  }
}

export default function LiveAssistPage() {
  const { token } = theme.useToken()
  const { user } = useAuth()
  const nav = useNavigate()
  const isTeacher = user?.role === "teacher" || user?.role === "admin"

  const [boot, setBoot] = useState<LiveBootstrap | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")

  const [sceneId, setSceneId] = useState("")
  const [playingId, setPlayingId] = useState("")
  const [rate, setRate] = useState(1)
  const [volume, setVolume] = useState(1)

  const [query, setQuery] = useState("")
  const [results, setResults] = useState<LiveScriptItem[]>([])
  const [searching, setSearching] = useState(false)
  const [sceneOnly, setSceneOnly] = useState(false)

  const [callOn, setCallOn] = useState(false)
  const [callSec, setCallSec] = useState(0)

  const [gapOpen, setGapOpen] = useState(false)
  const [gapData, setGapData] = useState<LiveAudioIndex | null>(null)
  const [manageOpen, setManageOpen] = useState(false)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const lastPlayedRef = useRef<LiveScriptItem | null>(null)

  // --- 当场录音 ---
  const [recTarget, setRecTarget] = useState<LiveScriptItem | null>(null)
  const [recState, setRecState] = useState<"idle" | "recording" | "review" | "saving">("idle")
  const [recSec, setRecSec] = useState(0)
  const [draft, setDraft] = useState<{ blob: Blob; url: string; durationMs: number } | null>(null)
  const recSessionRef = useRef<RecordingSession | null>(null)
  const micOk = recordingSupported()

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError("")
    try {
      const data = await liveApi.fetchBootstrap()
      setBoot(data)
    } catch (err) {
      setLoadError(errMsg(err, "加载实战话术失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // 离开页面时把语音与音频都掐掉：接下一通电话不该听见上一通的声音
  useEffect(() => {
    return () => {
      releaseTts()
      audioRef.current?.pause()
    }
  }, [])

  // 录音相关的资源（麦克风、试听用的 object URL）也必须随页面卸载一起还掉
  useEffect(() => {
    return () => {
      recSessionRef.current?.cancel()
      recSessionRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!callOn) return
    const timer = window.setInterval(() => setCallSec((v) => v + 1), 1000)
    return () => window.clearInterval(timer)
  }, [callOn])

  const stopAll = useCallback(() => {
    stopSpeaking()
    const el = audioRef.current
    if (el) {
      el.pause()
      el.currentTime = 0
    }
    setPlayingId("")
  }, [])

  // -------------------------------------------------------------------------
  // 当场录音：开始 → 停 → 试听 → 保存。录错了能重来，不必上传垃圾数据。
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (recState !== "recording") return
    const timer = window.setInterval(() => {
      const session = recSessionRef.current
      if (session) setRecSec(Math.floor(session.elapsed() / 1000))
    }, 200)
    return () => window.clearInterval(timer)
  }, [recState])

  const revokeDraft = useCallback(() => {
    setDraft((prev) => {
      if (prev) URL.revokeObjectURL(prev.url)
      return null
    })
  }, [])

  const openRecorder = (item: LiveScriptItem) => {
    stopAll() // 别让上一通电话的声音混进录音里
    revokeDraft()
    setRecTarget(item)
    setRecState("idle")
    setRecSec(0)
  }

  const closeRecorder = () => {
    recSessionRef.current?.cancel()
    recSessionRef.current = null
    revokeDraft()
    setRecTarget(null)
    setRecState("idle")
    setRecSec(0)
  }

  const beginRec = async () => {
    try {
      recSessionRef.current = await startRecording()
      setRecSec(0)
      setRecState("recording")
    } catch (err) {
      message.error(errMsg(err, "打不开麦克风"))
    }
  }

  const finishRec = async () => {
    const session = recSessionRef.current
    if (!session) return
    try {
      const result = await session.stop()
      recSessionRef.current = null
      setDraft({
        blob: result.blob,
        url: URL.createObjectURL(result.blob),
        durationMs: result.durationMs,
      })
      setRecState("review")
    } catch (err) {
      recSessionRef.current = null
      setRecState("idle")
      message.error(errMsg(err, "录制失败"))
    }
  }

  const saveDraft = async () => {
    if (!recTarget || !draft) return
    setRecState("saving")
    try {
      const updated = await liveApi.uploadRecording(recTarget.id, draft.blob, draft.durationMs)
      message.success(`${updated.code} 录音已保存，点播放就能听到你自己的声音`)
      closeRecorder()
      // 整页重拉：场景板上的「已录 x/y」和顶部进度条都要跟着变
      await load()
    } catch (err) {
      setRecState("review")
      message.error(errMsg(err, "上传录音失败"))
    }
  }

  const removeRecording = async (item: LiveScriptItem) => {
    try {
      await liveApi.deleteRecording(item.id)
      message.success(`${item.code} 的现场录音已删除`)
      await load()
    } catch (err) {
      message.error(errMsg(err, "删除录音失败"))
    }
  }

  const speakFallback = useCallback(
    (item: LiveScriptItem, reason?: string) => {
      if (!ttsSupported()) {
        message.warning("当前浏览器不支持语音合成，且这条话术还没有真人录音")
        setPlayingId("")
        return
      }
      if (reason) message.info(reason)
      speak(item.text, {
        rate,
        volume,
        onEnd: () => setPlayingId(""),
        onError: (msg) => {
          message.warning(msg)
          setPlayingId("")
        },
      })
    },
    [rate, volume],
  )

  const play = useCallback(
    (item: LiveScriptItem) => {
      const wasPlaying = playingId === item.id
      stopAll()
      if (wasPlaying) return // 再点一次 = 停止

      setPlayingId(item.id)
      lastPlayedRef.current = item
      // 使用计数是后台顺手记的，失败不影响播报
      void liveApi.markScriptUsed(item.id).catch(() => undefined)

      if (item.has_audio) {
        const src = liveApi.playableAudioUrl(item)
        if (!src) {
          speakFallback(item)
          return
        }
        const el = audioRef.current ?? new Audio()
        audioRef.current = el
        el.src = src
        el.playbackRate = rate
        el.volume = volume
        el.onended = () => setPlayingId("")
        el.onerror = () => speakFallback(item, "录音读不出来，先用合成语音顶上")
        void el.play().catch(() => speakFallback(item, "浏览器拦下了自动播放，改用合成语音"))
        return
      }
      speakFallback(item)
    },
    [playingId, rate, volume, speakFallback, stopAll],
  )

  // 进场行为由场景自己的 entry_mode 决定（存库，随时可切）：
  //   silent —— 进来不出声（默认）
  //   auto   —— 进来自动播「常用」标记的第一条；一条都没标就不播
  const openScene = useCallback(
    (scene: LiveScene) => {
      setSceneId(scene.id)
      stopAll()
      if (scene.entry_mode === "auto") {
        const target = scene.scripts.find((s) => s.is_common)
        if (target) play(target)
      }
    },
    [play, stopAll],
  )

  // 搜索：坐席多数直接敲快捷码，所以防抖做短一点
  useEffect(() => {
    const needle = query.trim()
    if (!needle) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = window.setTimeout(async () => {
      try {
        setResults(await liveApi.searchLiveScripts(needle))
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 180)
    return () => window.clearTimeout(timer)
  }, [query])

  // 快捷键：Esc 停止，空格重播上一条（不在输入框里时）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      const typing = tag === "INPUT" || tag === "TEXTAREA"
      if (e.key === "Escape") {
        stopAll()
        return
      }
      if (e.key === " " && !typing) {
        e.preventDefault()
        const last = lastPlayedRef.current
        if (last) play(last)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [play, stopAll])

  const scenes = boot?.scenes ?? []
  const current = useMemo(() => scenes.find((s) => s.id === sceneId) ?? null, [scenes, sceneId])

  const grouped = useMemo(() => {
    const order: LivePhaseKey[] = ["opening", "support", "business", "closing"]
    const pinned = scenes.filter((s) => s.pinned)
    const rest = scenes.filter((s) => !s.pinned)
    const groups: { key: LivePhaseKey | "pinned"; label: string; scenes: LiveScene[] }[] = []
    if (pinned.length) groups.push({ key: "pinned", label: "置顶", scenes: pinned })
    for (const key of order) {
      const list = rest.filter((s) => s.phase === key)
      if (!list.length) continue
      const label = boot?.phases.find((p) => p.key === key)?.label ?? key
      groups.push({ key, label, scenes: list })
    }
    return groups
  }, [scenes, boot])

  const recordedTotal = boot?.recorded_total ?? 0
  const scriptTotal = boot?.script_total ?? 0
  const recordedPercent = scriptTotal ? Math.round((recordedTotal / scriptTotal) * 100) : 0

  const openGaps = async () => {
    setGapOpen(true)
    if (gapData) return
    try {
      setGapData(await liveApi.fetchAudioIndex())
    } catch (err) {
      message.error(errMsg(err, "读取录音进度失败"))
    }
  }

  const togglePin = async (scene: LiveScene) => {
    try {
      const updated = await liveApi.toggleScenePin(scene.id)
      patchScene(updated)
    } catch (err) {
      message.error(errMsg(err, "操作失败"))
    }
  }

  /** 用服务端返回的场景整包替换本地——排序/进场模式的变动是场景级的。 */
  const patchScene = (updated: LiveScene) => {
    setBoot((prev) =>
      prev ? { ...prev, scenes: prev.scenes.map((s) => (s.id === updated.id ? updated : s)) } : prev,
    )
  }

  /** 切换进场模式（存库）：开 = 进来自动播「常用」第一条；关 = 进来不出声。 */
  const setEntryMode = async (scene: LiveScene, auto: boolean) => {
    try {
      patchScene(await liveApi.setSceneEntryMode(scene.id, auto ? "auto" : "silent"))
    } catch (err) {
      message.error(errMsg(err, "操作失败"))
    }
  }

  const toggleCommon = async (item: LiveScriptItem) => {
    try {
      const updated = await liveApi.setScriptCommon(item.id, !item.is_common)
      setBoot((prev) =>
        prev
          ? {
              ...prev,
              scenes: prev.scenes.map((sc) =>
                sc.id === updated.scene_id
                  ? { ...sc, scripts: sc.scripts.map((s) => (s.id === updated.id ? updated : s)) }
                  : sc,
              ),
            }
          : prev,
      )
    } catch (err) {
      message.error(errMsg(err, "操作失败"))
    }
  }

  /**
   * Top 榜排序：↑ 进榜/上移；↓ 下移，推到榜尾再按一次就退出榜单、回到热度序。
   * 没进榜的话术始终按热度自动排，手动只维护 Top1/Top2… 这些「置顶位」。
   */
  const moveScript = async (item: LiveScriptItem, dir: "up" | "down") => {
    if (!current) return
    const ranked = current.scripts.filter((s) => s.manual_rank != null)
    const isLastRanked = ranked.length > 0 && ranked[ranked.length - 1].id === item.id
    let position: number
    if (dir === "up") {
      position = item.manual_rank ? Math.max(1, item.manual_rank - 1) : ranked.length + 1
    } else {
      if (item.manual_rank == null) return
      position = isLastRanked ? 0 : item.manual_rank + 1
    }
    try {
      patchScene(await liveApi.reorderScript(item.id, position))
    } catch (err) {
      message.error(errMsg(err, "排序失败"))
    }
  }

  const clearRanking = async (scene: LiveScene) => {
    try {
      const ranked = scene.scripts.filter((s) => s.manual_rank != null)
      let updated = scene
      for (const s of ranked) {
        updated = await liveApi.reorderScript(s.id, 0)
      }
      patchScene(updated)
      message.success("已清除手动排序，按使用热度自动排")
    } catch (err) {
      message.error(errMsg(err, "清除失败"))
    }
  }

  const onCopy = async (item: LiveScriptItem) => {
    const ok = await copyText(item.label ? `${item.label}\n${item.text}` : item.text)
    if (ok) message.success(`已复制 ${item.code}`)
    else message.warning("复制失败，请手动选中文本")
  }

  // Top 榜里排在最后的一位（↓ 推它 = 退出榜单回热度序）
  const rankedIds = current ? current.scripts.filter((s) => s.manual_rank != null).map((s) => s.id) : []
  const isLastRanked = (item: LiveScriptItem) =>
    rankedIds.length > 0 && rankedIds[rankedIds.length - 1] === item.id

  const renderItem = (item: LiveScriptItem, showScene = false) => {
    const playing = playingId === item.id
    const hasAudio = item.has_audio
    const audioTag = AUDIO_TAG[item.audio_status] ?? AUDIO_TAG.tts
    const audioHint =
      item.audio_status === "file"
        ? `专业录音：${item.audio_name}`
        : item.audio_status === "record"
          ? `现场录音${item.recorded_by ? ` · ${item.recorded_by}` : ""}${
              item.recording_size ? ` · ${fmtSize(item.recording_size)}` : ""
            }`
          : "暂无录音，用浏览器合成兜底。点右边的麦克风自己录一条。"
    return (
      <div
        key={item.id}
        style={{
          display: "flex",
          gap: 12,
          alignItems: "flex-start",
          padding: "10px 12px",
          borderRadius: token.borderRadiusLG,
          border: `1px solid ${playing ? token.colorPrimary : token.colorBorderSecondary}`,
          background: playing ? token.colorPrimaryBg : token.colorBgContainer,
          transition: "background .15s, border-color .15s",
        }}
      >
        <Button
          type={playing ? "primary" : "default"}
          shape="circle"
          size="large"
          icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          onClick={() => play(item)}
          title={playing ? "停止" : hasAudio ? "播放这条话术的录音" : "用合成语音念这条话术"}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={6} wrap style={{ marginBottom: 4 }}>
            <Tag
              style={{
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontWeight: 600,
                margin: 0,
              }}
              color={hasAudio ? "blue" : "default"}
            >
              {item.code}
            </Tag>
            {item.manual_rank != null ? (
              <Tooltip title={`手动排序 Top${item.manual_rank}，排在按热度排的前面`}>
                <Tag color="geekblue" style={{ margin: 0 }}>
                  Top{item.manual_rank}
                </Tag>
              </Tooltip>
            ) : null}
            {item.is_common ? (
              <Tooltip title="常用：进场自动播报只播打这个标的第一条">
                <Tag color="volcano" style={{ margin: 0 }}>
                  常用
                </Tag>
              </Tooltip>
            ) : null}
            <Tooltip title={audioHint}>
              <Tag
                color={audioTag.color}
                icon={hasAudio ? <AudioOutlined /> : <ReloadOutlined />}
                style={{ margin: 0 }}
              >
                {audioTag.label}
              </Tag>
            </Tooltip>
            {showScene && item.scene_name ? <Tag style={{ margin: 0 }}>{item.scene_name}</Tag> : null}
            {item.use_count > 0 ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                用过 {item.use_count} 次
              </Typography.Text>
            ) : null}
          </Space>
          {item.label ? (
            <Typography.Text strong style={{ display: "block", fontSize: 13 }}>
              {item.label}
            </Typography.Text>
          ) : null}
          <Typography.Text style={{ fontSize: 15, lineHeight: 1.7 }}>{item.text}</Typography.Text>
        </div>
        <Space direction="vertical" size={4}>
          {!showScene && current ? (
            <Space size={2}>
              <Tooltip title={item.manual_rank ? `Top${item.manual_rank}，上移一位` : "设进 Top 榜（手动置顶位）"}>
                <Button size="small" icon={<ArrowUpOutlined />} onClick={() => void moveScript(item, "up")} />
              </Tooltip>
              <Tooltip
                title={
                  item.manual_rank == null
                    ? "没进 Top 榜，不用下移"
                    : isLastRanked(item)
                      ? "退出 Top 榜，回到按热度排"
                      : "下移一位"
                }
              >
                <Button
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={item.manual_rank == null}
                  onClick={() => void moveScript(item, "down")}
                />
              </Tooltip>
              <Tooltip title="常用：进场自动播报只播打这个标的第一条">
                <Button
                  size="small"
                  type={item.is_common ? "primary" : "default"}
                  icon={item.is_common ? <StarFilled /> : <StarOutlined />}
                  onClick={() => void toggleCommon(item)}
                >
                  {item.is_common ? "已常用" : "标常用"}
                </Button>
              </Tooltip>
            </Space>
          ) : null}
          <Tooltip title="复制文本">
            <Button size="small" icon={<CopyOutlined />} onClick={() => void onCopy(item)}>
              复制
            </Button>
          </Tooltip>
          <Tooltip title={hasAudio ? "重新录一条，覆盖现在的" : "用麦克风录一条，以后点播放就是你的声音"}>
            <Button
              size="small"
              icon={<AudioOutlined />}
              disabled={!micOk}
              onClick={() => openRecorder(item)}
            >
              {hasAudio ? "重录" : "录音"}
            </Button>
          </Tooltip>
          {item.audio_status === "record" ? (
            <Popconfirm
              title="删掉这条现场录音？"
              description="删了就回到合成语音；播不到原来的声音。"
              okText="删除"
              cancelText="算了"
              okButtonProps={{ danger: true }}
              onConfirm={() => void removeRecording(item)}
            >
              <Tooltip title="删除现场录音">
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          ) : null}
        </Space>
      </div>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {loadError ? (
        <Alert
          type="error"
          showIcon
          message="实战话术面板加载失败"
          description={loadError}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>重试</Button>}
        />
      ) : null}

      {!ttsSupported() ? (
        <Alert
          type="warning"
          showIcon
          message="当前浏览器不支持语音合成"
          description="没有真人录音的话术将无法播报。建议改用 Chrome / Edge，或尽快补齐 MP3 录音。"
        />
      ) : null}

      {!micOk ? (
        <Alert
          type="warning"
          showIcon
          message="当前环境不能录音"
          description="浏览器录音需要 https 或 localhost，且浏览器要支持 MediaRecorder。用 http + 内网 IP 打开时麦克风会被拦下——这是浏览器的安全限制，不是系统故障。"
        />
      ) : null}

      {/* 顶部控制条：接起电话后第一眼要看到的东西 */}
      <Card size="small" styles={{ body: { padding: "12px 16px" } }}>
        <Row gutter={[16, 12]} align="middle">
          <Col flex="none">
            <Space size={12}>
              <Button
                type={callOn ? "primary" : "default"}
                danger={callOn}
                icon={<ClockCircleOutlined />}
                onClick={() => setCallOn((v) => !v)}
              >
                {callOn ? "结束通话" : "客户已进线"}
              </Button>
              <Typography.Text
                style={{
                  fontSize: 22,
                  fontVariantNumeric: "tabular-nums",
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                }}
              >
                {fmtClock(callSec)}
              </Typography.Text>
              {callSec > 0 ? (
                <Button size="small" type="link" onClick={() => { setCallSec(0); setCallOn(false) }}>
                  归零
                </Button>
              ) : null}
            </Space>
          </Col>
          <Col flex="auto" style={{ minWidth: 220 }}>
            <Input
              allowClear
              size="large"
              prefix={<SearchOutlined />}
              placeholder="输快捷码直达，如 hy2 / aa1；也可搜关键词"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={() => {
                if (results.length) play(results[0])
              }}
            />
          </Col>
          <Col flex="none">
            <Space size={16}>
              <Space size={6}>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  语速
                </Typography.Text>
                <Slider
                  min={0.6}
                  max={1.6}
                  step={0.1}
                  value={rate}
                  onChange={setRate}
                  style={{ width: 90 }}
                />
              </Space>
              <Space size={6}>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  音量
                </Typography.Text>
                <Slider
                  min={0}
                  max={1}
                  step={0.1}
                  value={volume}
                  onChange={(v) => {
                    setVolume(v)
                    if (audioRef.current) audioRef.current.volume = v
                  }}
                  style={{ width: 80 }}
                />
              </Space>
              <Button icon={<StopOutlined />} onClick={stopAll} disabled={!playingId}>
                停止
              </Button>
            </Space>
          </Col>
        </Row>
        <Divider style={{ margin: "10px 0" }} />
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Space size={12} wrap>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                场景 {scenes.length} · 话术 {scriptTotal}
              </Typography.Text>
              <Tooltip title="真人录音已覆盖比例；其余用浏览器合成兜底">
                <Space size={8}>
                  <Progress
                    percent={recordedPercent}
                    size="small"
                    style={{ width: 140, margin: 0 }}
                    strokeColor={recordedPercent > 0 ? token.colorSuccess : token.colorTextTertiary}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    已录音 {recordedTotal}/{scriptTotal}
                  </Typography.Text>
                </Space>
              </Tooltip>
            </Space>
          </Col>
          <Col flex="none">
            <Space>
              <Button size="small" icon={<PhoneOutlined />} onClick={() => nav("/live/calls")}>
                模拟来电
              </Button>
              <Button size="small" icon={<FileTextOutlined />} onClick={() => void openGaps()}>
                待录音清单
              </Button>
              <Button size="small" icon={<SettingOutlined />} onClick={() => setManageOpen(true)}>
                管理话术
              </Button>
              <Tooltip title="刷新会重新扫描录音目录，新放的 mp3 立即生效">
                <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
                  刷新
                </Button>
              </Tooltip>
            </Space>
          </Col>
        </Row>
      </Card>

      <Row gutter={16} align="top">
        {/* 左：场景板 */}
        <Col xs={24} lg={8} xl={7}>
          <Card
            size="small"
            title="场景"
            styles={{ body: { maxHeight: "62vh", overflowY: "auto", padding: 8 } }}
          >
            {loading ? (
              <Typography.Text type="secondary">加载中…</Typography.Text>
            ) : scenes.length === 0 ? (
              <Empty description="还没有场景，请先运行 seed_live_scripts.py 导入话术库" />
            ) : (
              grouped.map((group) => (
                <div key={group.key} style={{ marginBottom: 10 }}>
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 12, paddingLeft: 4, letterSpacing: 1 }}
                  >
                    {group.label}
                  </Typography.Text>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                    {group.scenes.map((scene) => {
                      const active = scene.id === sceneId
                      return (
                        <div
                          key={scene.id}
                          onClick={() => openScene(scene)}
                          style={{
                            cursor: "pointer",
                            padding: "7px 10px",
                            borderRadius: token.borderRadius,
                            border: `1px solid ${active ? token.colorPrimary : "transparent"}`,
                            background: active ? token.colorPrimaryBg : token.colorFillQuaternary,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 8,
                          }}
                        >
                          <Space size={6} style={{ minWidth: 0 }}>
                            {scene.pinned ? <StarFilled style={{ color: token.colorWarning }} /> : null}
                            <Typography.Text strong={active} style={{ fontSize: 14 }}>
                              {scene.name}
                            </Typography.Text>
                          </Space>
                          <Space size={4}>
                            <Tag
                              color={PHASE_COLOR[scene.phase]}
                              style={{ margin: 0, fontSize: 11, lineHeight: "16px" }}
                            >
                              {SOURCE_LABEL[scene.source]}
                            </Tag>
                            <Typography.Text
                              type="secondary"
                              style={{ fontSize: 11, whiteSpace: "nowrap" }}
                            >
                              {scene.recorded_count}/{scene.script_count}
                            </Typography.Text>
                          </Space>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))
            )}
          </Card>
        </Col>

        {/* 右：话术板 */}
        <Col xs={24} lg={16} xl={17}>
          <Card
            size="small"
            title={
              current ? (
                <Space size={8} wrap>
                  <Typography.Text strong>{current.name}</Typography.Text>
                  <Tag color={PHASE_COLOR[current.phase]} style={{ margin: 0 }}>
                    {SOURCE_LABEL[current.source]}
                  </Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    共 {current.script_count} 条 · 已录 {current.recorded_count} 条
                  </Typography.Text>
                </Space>
              ) : query ? (
                `搜索「${query}」`
              ) : (
                "话术"
              )
            }
            extra={
              current ? (
                <Space size={8} wrap>
                  <Tooltip title="进场自动播报：开 = 点进场景自动播「常用」标记的第一条；关 = 进来不出声">
                    <Space size={4}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        进场播报
                      </Typography.Text>
                      <Switch
                        size="small"
                        checked={current.entry_mode === "auto"}
                        onChange={(v) => void setEntryMode(current, v)}
                      />
                    </Space>
                  </Tooltip>
                  {current.scripts.some((s) => s.manual_rank != null) ? (
                    <Popconfirm
                      title="清除本场景的全部手动排序？"
                      description="清完回到按使用热度自动排。"
                      okText="清除"
                      cancelText="算了"
                      onConfirm={() => void clearRanking(current)}
                    >
                      <Button size="small">清排序</Button>
                    </Popconfirm>
                  ) : null}
                  {isTeacher ? (
                    <Tooltip title={current.pinned ? "取消置顶" : "置顶这个场景"}>
                      <Button
                        size="small"
                        icon={current.pinned ? <StarFilled /> : <StarOutlined />}
                        onClick={() => void togglePin(current)}
                      />
                    </Tooltip>
                  ) : null}
                </Space>
              ) : null
            }
            styles={{ body: { maxHeight: "62vh", overflowY: "auto", padding: 12 } }}
          >
            {query.trim() ? (
              searching ? (
                <Typography.Text type="secondary">搜索中…</Typography.Text>
              ) : results.length === 0 ? (
                <Empty description={`没有匹配「${query}」的话术`} />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    找到 {results.length} 条 · 回车直接播第一条 · Esc 停止 · 空格重播上一条
                  </Typography.Text>
                  <Segmented
                    options={[
                      { label: "仅当前场景", value: "scene" },
                      { label: "全部结果", value: "all" },
                    ]}
                    value={sceneOnly ? "scene" : "all"}
                    onChange={(v) => setSceneOnly(v === "scene")}
                    size="small"
                  />
                  {(sceneOnly ? results.filter((r) => r.scene_id === sceneId) : results).map((item) =>
                    renderItem(item, true),
                  )}
                </div>
              )
            ) : !current ? (
              <Empty
                description={
                  <span>
                    从左边点一个场景开始
                    <br />
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      默认进场不出声；场景开了「进场播报」才会自动播「常用」标记的那条
                    </Typography.Text>
                  </span>
                }
              />
            ) : current.scripts.length === 0 ? (
              <Empty description="这个场景还没有话术" />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {current.scripts.map((item) => renderItem(item))}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        open={gapOpen}
        onCancel={() => setGapOpen(false)}
        footer={null}
        width={880}
        title={
          <Space size={10} wrap>
            <span>待录音清单</span>
            {gapData ? (
              <Typography.Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                已录 {gapData.recorded}/{gapData.scripts}（现场录 {gapData.recorded_from_db}）· 待录{" "}
                {gapData.pending_recording} 条
              </Typography.Text>
            ) : null}
          </Space>
        }
      >
        {gapData ? (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <Alert
              type="info"
              showIcon
              message="两条补录音的路子"
              description={
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Typography.Text style={{ fontSize: 13 }}>
                    ① 页面里点话术右边的 <AudioOutlined /> 麦克风按钮，当场录一条（任何登录用户都能录）
                  </Typography.Text>
                  <Typography.Text style={{ fontSize: 13 }}>
                    ② 把录音按文件名丢进下面这个目录，刷新即生效、不需要重启
                  </Typography.Text>
                  <Typography.Text code copyable style={{ fontSize: 12 }}>
                    {gapData.audio_dir}
                  </Typography.Text>
                </Space>
              }
            />
            {gapData.override_broken > 0 ? (
              <Alert
                type="warning"
                showIcon
                message={`有 ${gapData.override_broken} 条配了录音文件名但文件不存在，检查一下拼写`}
              />
            ) : null}
            <Table
              size="small"
              rowKey="code"
              dataSource={gapData.items.slice(0, 200)}
              pagination={{ pageSize: 20, size: "small" }}
              columns={[
                {
                  title: "文件名",
                  dataIndex: "code",
                  width: 130,
                  render: (code: string) => (
                    <Typography.Text code style={{ fontSize: 12 }}>
                      {code}.mp3
                    </Typography.Text>
                  ),
                },
                { title: "场景", dataIndex: "scene_name", width: 150 },
                { title: "标题", dataIndex: "label", width: 170, ellipsis: true },
                { title: "话术", dataIndex: "text", ellipsis: true },
                {
                  title: "用过",
                  dataIndex: "use_count",
                  width: 70,
                  render: (n: number) => <Badge count={n} showZero color={n ? "red" : "default"} />,
                },
              ]}
            />
          </Space>
        ) : (
          <Typography.Text type="secondary">读取中…</Typography.Text>
        )}
      </Modal>

      {/* 录音弹窗：把要念的文案放大摆好，录 → 试听 → 存，失败能重来 */}
      <Modal
        open={!!recTarget}
        onCancel={closeRecorder}
        footer={null}
        width={640}
        maskClosable={false}
        title={
          recTarget ? (
            <Space size={8} wrap>
              <span>录音</span>
              <Typography.Text code>{recTarget.code}</Typography.Text>
              {recTarget.audio_status === "record" ? (
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                  已有现场录音，保存后会被替换
                </Typography.Text>
              ) : recTarget.audio_status === "file" ? (
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                  目录里已有专业录音，优先级比这条高
                </Typography.Text>
              ) : null}
            </Space>
          ) : (
            "录音"
          )
        }
      >
        {recTarget ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                照着念：
              </Typography.Text>
              <div
                style={{
                  marginTop: 6,
                  padding: "14px 16px",
                  borderRadius: token.borderRadiusLG,
                  background: token.colorFillQuaternary,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  fontSize: 18,
                  lineHeight: 1.8,
                }}
              >
                {recTarget.text}
              </div>
            </div>

            {recState === "recording" ? (
              <div style={{ textAlign: "center" }}>
                <Space direction="vertical" size={12} align="center" style={{ width: "100%" }}>
                  <Space size={10}>
                    <Badge status="processing" />
                    <Typography.Text strong>正在录音…</Typography.Text>
                    <Typography.Text
                      strong
                      style={{ fontSize: 26, fontVariantNumeric: "tabular-nums" }}
                    >
                      {fmtClock(recSec)}
                    </Typography.Text>
                  </Space>
                  <Space>
                    <Button type="primary" danger size="large" icon={<StopOutlined />} onClick={() => void finishRec()}>
                      停止
                    </Button>
                    <Button size="large" onClick={closeRecorder}>
                      取消
                    </Button>
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    念完点「停止」，会先让你试听，确认了才会上传
                  </Typography.Text>
                </Space>
              </div>
            ) : draft ? (
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Alert
                  type="success"
                  showIcon
                  message={`录到 ${(draft.durationMs / 1000).toFixed(1)} 秒 · ${fmtSize(draft.blob.size)}`}
                  description="先听一遍。不满意就重录，满意再保存。"
                />
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <audio controls src={draft.url} style={{ width: "100%" }} />
                <Space>
                  <Button
                    type="primary"
                    loading={recState === "saving"}
                    onClick={() => void saveDraft()}
                  >
                    保存并启用
                  </Button>
                  <Button
                    disabled={recState === "saving"}
                    onClick={() => {
                      revokeDraft()
                      setRecState("idle")
                      setRecSec(0)
                    }}
                  >
                    重录
                  </Button>
                  <Button type="text" disabled={recState === "saving"} onClick={closeRecorder}>
                    放弃
                  </Button>
                </Space>
              </Space>
            ) : (
              <div style={{ textAlign: "center" }}>
                <Space direction="vertical" size={12} align="center" style={{ width: "100%" }}>
                  <Button type="primary" size="large" icon={<AudioOutlined />} onClick={() => void beginRec()}>
                    开始录制
                  </Button>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    第一次会弹出麦克风授权，点「允许」；录完先试听再保存
                  </Typography.Text>
                </Space>
              </div>
            )}
          </Space>
        ) : null}
      </Modal>
      <LiveScriptManager
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        scenes={boot?.scenes ?? []}
        defaultSceneId={sceneId}
        onChanged={(data) => setBoot(data)}
      />
    </div>
  )
}
