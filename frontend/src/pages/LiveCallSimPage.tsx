import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Avatar,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
  theme,
} from "antd"
import {
  AudioOutlined,
  CustomerServiceOutlined,
  PauseCircleOutlined,
  PhoneOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SendOutlined,
  UserOutlined,
} from "@ant-design/icons"
import * as callsApi from "../api/calls"
import * as liveApi from "../api/live"
import { getCategories } from "../api/practice"
import { errMsg } from "../api/client"
import type {
  LiveBootstrap,
  LiveCallScriptsSummary,
  LiveScriptItem,
  PracticeCategory,
  PracticeMessage,
  PracticeSession,
} from "../types/api"
import { releaseTts, speak, stopSpeaking, ttsSupported } from "../utils/tts"

/**
 * 模拟客户进线：点「模拟来电」→ AI 客户打进来 → 接听 → 点话术回复客户。
 *
 * 和实战话术面板（/live）的分工：那边是接真实来电时的提词器；这边是练习场——
 * 客户是真的（AI），你的话术也是真的（点哪条播哪条、计哪条的使用量），
 * 只有电话是假的。挂断后给一页话术小结，方便复盘这通电话用了什么。
 */

type Phase = "idle" | "ringing" | "active" | "ended"

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  pending: { color: "warning", label: "待接听" },
  in_progress: { color: "processing", label: "通话中" },
  finished: { color: "default", label: "已结束" },
  canceled: { color: "default", label: "已取消" },
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function fmtClock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

export default function LiveCallSimPage() {
  const { token } = theme.useToken()

  const [phase, setPhase] = useState<Phase>("idle")
  const [call, setCall] = useState<PracticeSession | null>(null)
  const [messages, setMessages] = useState<PracticeMessage[]>([])
  const [callSec, setCallSec] = useState(0)
  const [summary, setSummary] = useState<LiveCallScriptsSummary | null>(null)

  // 来电设置
  const [categories, setCategories] = useState<PracticeCategory[]>([])
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [difficulty, setDifficulty] = useState(2)
  const [simulating, setSimulating] = useState(false)
  const [answering, setAnswering] = useState(false)

  // 话术面板
  const [boot, setBoot] = useState<LiveBootstrap | null>(null)
  const [sceneId, setSceneId] = useState("")
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<LiveScriptItem[]>([])

  // 发送与播放
  const [sending, setSending] = useState(false)
  const [sendingId, setSendingId] = useState("")
  const [freeInput, setFreeInput] = useState("")
  const [playingId, setPlayingId] = useState("")
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // 通话记录与回放
  const [history, setHistory] = useState<PracticeSession[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [replayCall, setReplayCall] = useState<PracticeSession | null>(null)
  const [replayMessages, setReplayMessages] = useState<PracticeMessage[]>([])
  const [replaySummary, setReplaySummary] = useState<LiveCallScriptsSummary | null>(null)

  const chatEndRef = useRef<HTMLDivElement | null>(null)

  const stopAll = useCallback(() => {
    stopSpeaking()
    const el = audioRef.current
    if (el) {
      el.pause()
      el.currentTime = 0
    }
    setPlayingId("")
  }, [])

  // 离开页面把声音还掉：下一通电话不该听见上一通的余音
  useEffect(() => {
    return () => {
      releaseTts()
      audioRef.current?.pause()
    }
  }, [])

  useEffect(() => {
    if (phase !== "active") return
    const timer = window.setInterval(() => setCallSec((v) => v + 1), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  // 通话中的 Esc = 停声
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") stopAll()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [stopAll])

  const loadCategories = useCallback(async () => {
    try {
      setCategories(await getCategories())
    } catch {
      // 品类拉不到就用「随机」，不挡来电话
    }
  }, [])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      setHistory(await callsApi.listMyCalls())
    } catch {
      // 记录拉不到不挡主流程
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadCategories()
    void loadHistory()
  }, [loadCategories, loadHistory])

  // 新消息自动滚到底
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, sending])

  const loadBoot = useCallback(async () => {
    try {
      const data = await liveApi.fetchBootstrap()
      setBoot(data)
      if (!sceneId && data.scenes.length) setSceneId(data.scenes[0].id)
    } catch (err) {
      message.error(errMsg(err, "话术面板加载失败"))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 搜索：输快捷码直达，防抖同实战面板
  useEffect(() => {
    const needle = query.trim()
    if (!needle) {
      setResults([])
      return
    }
    const timer = window.setTimeout(async () => {
      try {
        setResults(await liveApi.searchLiveScripts(needle))
      } catch {
        setResults([])
      }
    }, 180)
    return () => window.clearTimeout(timer)
  }, [query])

  /** 试听：把这条话术播给坐席自己听（录音优先，合成兜底），不发给客户。 */
  const playItem = useCallback(
    (item: LiveScriptItem) => {
      stopAll()
      setPlayingId(item.id)
      void liveApi.markScriptUsed(item.id).catch(() => undefined)
      const done = () => setPlayingId("")
      if (item.has_audio) {
        const src = liveApi.playableAudioUrl(item)
        if (src) {
          const el = audioRef.current ?? new Audio()
          audioRef.current = el
          el.src = src
          el.onended = done
          el.onerror = () => speak(item.text, { onEnd: done, onError: done })
          void el.play().catch(() => speak(item.text, { onEnd: done, onError: done }))
          return
        }
      }
      if (!ttsSupported()) {
        message.warning("当前浏览器不支持语音合成，且这条话术还没有录音")
        done()
        return
      }
      speak(item.text, {
        onEnd: done,
        onError: (msg) => {
          message.warning(msg)
          done()
        },
      })
    },
    [stopAll],
  )

  const loadSummary = useCallback(async (callId: string) => {
    try {
      setSummary(await callsApi.getCallScriptsSummary(callId))
    } catch {
      // 小结拉不到不挡收尾
    }
  }, [])

  const simulate = async () => {
    setSimulating(true)
    try {
      const c = await callsApi.simulateCall({ category, difficulty })
      setCall(c)
      setMessages([])
      setSummary(null)
      setCallSec(0)
      setFreeInput("")
      setPhase("ringing")
    } catch (err) {
      message.error(errMsg(err, "模拟来电失败"))
    } finally {
      setSimulating(false)
    }
  }

  const answer = async () => {
    if (!call) return
    setAnswering(true)
    try {
      await callsApi.answerCall(call.id)
      setMessages(await callsApi.getCallTranscript(call.id))
      setPhase("active")
      void loadBoot()
    } catch (err) {
      message.error(errMsg(err, "接听失败"))
    } finally {
      setAnswering(false)
    }
  }

  /** 挂断（通话中手动挂）。 */
  const hangup = async () => {
    if (!call) return
    stopAll()
    try {
      await callsApi.hangupCall(call.id)
    } catch (err) {
      message.error(errMsg(err, "挂断失败"))
    }
    setPhase("ended")
    void loadSummary(call.id)
    void loadHistory()
  }

  /** 拒接（响铃中）：直接挂断回列表。 */
  const refuse = async () => {
    if (!call) return
    try {
      await callsApi.hangupCall(call.id)
    } catch {
      // 拒接失败也回列表
    }
    setPhase("idle")
    setCall(null)
    void loadHistory()
  }

  /** 客户自己说完（is_finished）：后端已置 FINISHED，本地转已结束并出小结。 */
  const finishByCustomer = useCallback(
    (callId: string) => {
      stopAll()
      setPhase("ended")
      void loadSummary(callId)
      void loadHistory()
    },
    [loadHistory, loadSummary, stopAll],
  )

  const appendTurn = useCallback(
    (agentMsg: PracticeMessage, reply: PracticeReplyLocal) => {
      setMessages((prev) => [
        ...prev,
        agentMsg,
        {
          id: `local-c-${Date.now()}`,
          role: "customer",
          content: reply.content,
          turn: reply.next_turn,
          script_id: null,
          via: "auto",
          created_at: new Date().toISOString(),
        },
      ])
    },
    [],
  )

  /** 点话术 = 回复客户：先播给自己听，正文作为坐席发言，AI 客户接着说。 */
  const sendScript = async (item: LiveScriptItem) => {
    if (!call || phase !== "active" || sending) return
    stopAll()
    setSending(true)
    setSendingId(item.id)
    try {
      const reply = await callsApi.useScriptReply(call.id, item.id)
      playItem(item) // 点了就说：像真打电话一样，说出口的声音立刻听到
      appendTurn(
        {
          id: `local-s-${Date.now()}`,
          role: "student",
          content: item.text,
          turn: reply.next_turn,
          script_id: item.id,
          via: "script",
          created_at: new Date().toISOString(),
        },
        reply,
      )
      if (reply.is_finished) finishByCustomer(call.id)
    } catch (err) {
      // LLM 挂了后端整笔回滚，这条话术不会落库——放心重发
      message.error(errMsg(err, "客户没接上话，稍等片刻再发一次"))
    } finally {
      setSending(false)
      setSendingId("")
    }
  }

  /** 自由输入：话术覆盖不了时自己说。 */
  const sendFree = async () => {
    if (!call || phase !== "active" || sending) return
    const content = freeInput.trim()
    if (!content) return
    stopAll()
    setSending(true)
    setSendingId("free")
    try {
      const reply = await callsApi.freeReply(call.id, content)
      appendTurn(
        {
          id: `local-s-${Date.now()}`,
          role: "student",
          content,
          turn: reply.next_turn,
          script_id: null,
          via: "free",
          created_at: new Date().toISOString(),
        },
        reply,
      )
      setFreeInput("")
      if (reply.is_finished) finishByCustomer(call.id)
    } catch (err) {
      message.error(errMsg(err, "客户没接上话，稍等片刻再发一次"))
    } finally {
      setSending(false)
      setSendingId("")
    }
  }

  const resetToIdle = () => {
    stopAll()
    setPhase("idle")
    setCall(null)
    setMessages([])
    setSummary(null)
    setCallSec(0)
    setFreeInput("")
  }

  const openReplay = async (c: PracticeSession) => {
    setReplayCall(c)
    setReplayMessages([])
    setReplaySummary(null)
    try {
      setReplayMessages(await callsApi.getCallTranscript(c.id))
    } catch (err) {
      message.error(errMsg(err, "读取通话记录失败"))
    }
  }

  const loadReplaySummary = async (callId: string) => {
    try {
      setReplaySummary(await callsApi.getCallScriptsSummary(callId))
    } catch (err) {
      message.error(errMsg(err, "读取话术小结失败"))
    }
  }

  const scenes = boot?.scenes ?? []
  const currentScene = useMemo(() => scenes.find((s) => s.id === sceneId) ?? null, [scenes, sceneId])
  const categoryLabel = useMemo(() => {
    if (!call) return ""
    return categories.find((c) => c.key === call.category)?.label ?? call.category
  }, [call, categories])

  // -------------------------------------------------------------------------
  // 渲染件
  // -------------------------------------------------------------------------

  const renderBubble = (m: PracticeMessage, forReplay = false) => {
    if (m.role === "system") {
      return (
        <div key={m.id} style={{ textAlign: "center", margin: "6px 0" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {m.content}
          </Typography.Text>
        </div>
      )
    }
    const mine = m.role === "student"
    return (
      <div
        key={`${forReplay ? "r-" : ""}${m.id}`}
        style={{
          display: "flex",
          justifyContent: mine ? "flex-end" : "flex-start",
          gap: 8,
          marginBottom: 12,
        }}
      >
        {!mine ? (
          <Avatar size={28} icon={<CustomerServiceOutlined />} style={{ background: token.colorPrimary, flexShrink: 0 }} />
        ) : null}
        <div
          style={{
            maxWidth: "76%",
            padding: "8px 12px",
            borderRadius: token.borderRadiusLG,
            background: mine ? token.colorPrimaryBg : token.colorFillQuaternary,
            border: `1px solid ${mine ? token.colorPrimaryBorder : token.colorBorderSecondary}`,
          }}
        >
          <Space size={6} style={{ marginBottom: 2 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {mine ? "我" : "客户"}
            </Typography.Text>
            {m.via === "script" ? (
              <Tag color="blue" style={{ margin: 0, fontSize: 11, lineHeight: "16px" }}>
                话术
              </Tag>
            ) : null}
          </Space>
          <div style={{ fontSize: 14, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{m.content}</div>
        </div>
        {mine ? (
          <Avatar size={28} icon={<UserOutlined />} style={{ background: token.colorSuccess, flexShrink: 0 }} />
        ) : null}
      </div>
    )
  }

  const renderScriptRow = (item: LiveScriptItem, sendingBlocked: boolean) => {
    const playing = playingId === item.id
    return (
      <div
        key={item.id}
        style={{
          display: "flex",
          gap: 10,
          alignItems: "flex-start",
          padding: "8px 10px",
          borderRadius: token.borderRadius,
          border: `1px solid ${playing ? token.colorPrimary : token.colorBorderSecondary}`,
          background: playing ? token.colorPrimaryBg : token.colorBgContainer,
        }}
      >
        <Button
          type={playing ? "primary" : "default"}
          shape="circle"
          icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          onClick={() => playItem(item)}
          title="只播给自己听，不发给客户"
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={6} wrap style={{ marginBottom: 2 }}>
            <Tag
              style={{ margin: 0, fontFamily: "ui-monospace, Menlo, monospace", fontWeight: 600 }}
              color={item.has_audio ? "blue" : "default"}
            >
              {item.code}
            </Tag>
            {item.label ? (
              <Typography.Text strong style={{ fontSize: 12 }}>
                {item.label}
              </Typography.Text>
            ) : null}
          </Space>
          <Typography.Paragraph style={{ margin: 0, fontSize: 13, lineHeight: 1.6 }}>
            {item.text}
          </Typography.Paragraph>
        </div>
        <Button
          type="primary"
          size="small"
          icon={<SendOutlined />}
          loading={sending && sendingId === item.id}
          disabled={sendingBlocked || (sending && sendingId !== item.id)}
          onClick={() => void sendScript(item)}
        >
          发送
        </Button>
      </div>
    )
  }

  const renderSummaryList = (data: LiveCallScriptsSummary | null) => {
    if (!data) return <Typography.Text type="secondary">读取中…</Typography.Text>
    if (!data.scripts.length)
      return <Empty description="这通电话没有点过话术（全程自由发挥？）" />
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {data.scripts.map((item) => {
          const playing = playingId === item.id
          return (
            <div
              key={item.id}
              style={{
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                padding: "8px 10px",
                borderRadius: token.borderRadius,
                border: `1px solid ${token.colorBorderSecondary}`,
                background: token.colorBgContainer,
              }}
            >
              <Button
                type={playing ? "primary" : "default"}
                shape="circle"
                size="small"
                icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                onClick={() => playItem(item)}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <Space size={6} wrap>
                  <Tag
                    style={{ margin: 0, fontFamily: "ui-monospace, Menlo, monospace", fontWeight: 600 }}
                  >
                    {item.code}
                  </Tag>
                  {item.label ? (
                    <Typography.Text strong style={{ fontSize: 12 }}>
                      {item.label}
                    </Typography.Text>
                  ) : null}
                </Space>
                <Typography.Paragraph style={{ margin: 0, fontSize: 13 }}>
                  {item.text}
                </Typography.Paragraph>
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  // -------------------------------------------------------------------------
  // 页面
  // -------------------------------------------------------------------------

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ---------- 空闲：来电设置 + 历史记录 ---------- */}
      {phase === "idle" ? (
        <>
          <Card size="small" title={<Space><PhoneOutlined /> 模拟来电</Space>}>
            <Row gutter={[16, 12]} align="middle">
              <Col xs={24} md={8}>
                <Select
                  allowClear
                  placeholder="随机品类"
                  style={{ width: "100%" }}
                  value={category}
                  onChange={(v) => setCategory(v)}
                  options={categories.map((c) => ({ value: c.key, label: c.label }))}
                />
              </Col>
              <Col xs={24} md={8}>
                <Space size={8}>
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    难度
                  </Typography.Text>
                  <Segmented
                    value={difficulty}
                    onChange={(v) => setDifficulty(v as number)}
                    options={[1, 2, 3, 4, 5]}
                  />
                </Space>
              </Col>
              <Col xs={24} md={8} style={{ textAlign: "right" }}>
                <Button
                  type="primary"
                  size="large"
                  icon={<PhoneOutlined />}
                  loading={simulating}
                  onClick={() => void simulate()}
                >
                  模拟来电
                </Button>
              </Col>
            </Row>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 8 }}>
              AI 客户会随机打进来一个品类的问题（可选品类与难度）；接听后从右边点话术回复客户，
              也可以像真实通话一样自己输入。挂断后可回放对话并查看话术小结。
            </Typography.Text>
          </Card>

          <Card size="small" title="我的模拟通话">
            <Table
              size="small"
              rowKey="id"
              loading={historyLoading}
              dataSource={history}
              pagination={{ pageSize: 8, size: "small" }}
              locale={{ emptyText: "还没有模拟通话记录" }}
              columns={[
                {
                  title: "时间",
                  dataIndex: "created_at",
                  width: 130,
                  render: (v: string) => fmtTime(v),
                },
                {
                  title: "品类",
                  dataIndex: "category",
                  width: 140,
                  render: (v: string) => categories.find((c) => c.key === v)?.label ?? v,
                },
                {
                  title: "状态",
                  dataIndex: "status",
                  width: 90,
                  render: (v: string) => {
                    const t = STATUS_TAG[v] ?? STATUS_TAG.finished
                    return <Tag color={t.color}>{t.label}</Tag>
                  },
                },
                { title: "轮次", dataIndex: "current_turn", width: 70 },
                {
                  title: "操作",
                  width: 90,
                  render: (_: unknown, record: PracticeSession) => (
                    <Button size="small" onClick={() => void openReplay(record)}>
                      回放
                    </Button>
                  ),
                },
              ]}
            />
          </Card>
        </>
      ) : null}

      {/* ---------- 响铃：客户来电 ---------- */}
      {phase === "ringing" && call ? (
        <Card size="small">
          <div style={{ textAlign: "center", padding: "28px 0" }}>
            <Space direction="vertical" size={14} align="center">
              <Avatar size={72} icon={<CustomerServiceOutlined />} style={{ background: token.colorPrimary }} />
              <Typography.Title level={4} style={{ margin: 0 }}>
                客户来电…
              </Typography.Title>
              <Typography.Text type="secondary">
                品类：{categoryLabel} · 难度 {call.difficulty}
              </Typography.Text>
              <Typography.Paragraph
                type="secondary"
                style={{ maxWidth: 560, marginBottom: 0 }}
                ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}
              >
                客户画像：{call.persona}
              </Typography.Paragraph>
              <Space size={16} style={{ marginTop: 8 }}>
                <Button
                  type="primary"
                  size="large"
                  shape="round"
                  icon={<PhoneOutlined />}
                  loading={answering}
                  onClick={() => void answer()}
                >
                  接听
                </Button>
                <Button size="large" shape="round" danger onClick={() => void refuse()}>
                  拒接
                </Button>
              </Space>
            </Space>
          </div>
        </Card>
      ) : null}

      {/* ---------- 通话中 / 已结束：对话 + 话术面板 ---------- */}
      {(phase === "active" || phase === "ended") && call ? (
        <>
          <Row gutter={16} align="top">
            <Col xs={24} lg={14}>
              <Card
                size="small"
                title={
                  <Space size={10} wrap>
                    <Typography.Text strong>客户</Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {categoryLabel} · {call.persona.slice(0, 24)}
                      {call.persona.length > 24 ? "…" : ""}
                    </Typography.Text>
                  </Space>
                }
                extra={
                  phase === "active" ? (
                    <Space size={12}>
                      <Typography.Text
                        style={{
                          fontSize: 18,
                          fontVariantNumeric: "tabular-nums",
                          fontFamily: "ui-monospace, Menlo, monospace",
                        }}
                      >
                        {fmtClock(callSec)}
                      </Typography.Text>
                      <Button danger size="small" icon={<PhoneOutlined />} onClick={() => void hangup()}>
                        挂断
                      </Button>
                    </Space>
                  ) : (
                    <Tag>{STATUS_TAG.finished.label}</Tag>
                  )
                }
                styles={{ body: { padding: 12 } }}
              >
                <div
                  style={{
                    maxHeight: "54vh",
                    overflowY: "auto",
                    padding: "4px 4px 0",
                  }}
                >
                  {messages.length === 0 ? (
                    <Empty description="接听后客户会先开口" />
                  ) : (
                    messages.map((m) => renderBubble(m))
                  )}
                  {sending ? (
                    <div style={{ textAlign: "center", margin: "4px 0 10px" }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        客户正在回应…
                      </Typography.Text>
                    </div>
                  ) : null}
                  <div ref={chatEndRef} />
                </div>
                {phase === "active" ? (
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <Input
                      placeholder="像真实通话一样自己说（话术面板覆盖不了时用）"
                      value={freeInput}
                      disabled={sending}
                      onChange={(e) => setFreeInput(e.target.value)}
                      onPressEnter={() => void sendFree()}
                    />
                    <Button
                      type="primary"
                      icon={<SendOutlined />}
                      loading={sending && sendingId === "free"}
                      disabled={sending && sendingId !== "free"}
                      onClick={() => void sendFree()}
                    >
                      发送
                    </Button>
                  </div>
                ) : null}
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card
                size="small"
                title={
                  currentScene ? (
                    <Space size={8} wrap>
                      <Typography.Text strong>{currentScene.name}</Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        共 {currentScene.script_count} 条
                      </Typography.Text>
                    </Space>
                  ) : (
                    "话术"
                  )
                }
                extra={
                  <Tooltip title="刷新会重新扫描录音目录，新放的 mp3 立即生效">
                    <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadBoot()} />
                  </Tooltip>
                }
                styles={{ body: { padding: 12 } }}
              >
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    placeholder="选场景"
                    style={{ width: "100%" }}
                    value={sceneId || undefined}
                    onChange={(v) => {
                      setSceneId(v)
                      setQuery("")
                    }}
                    options={scenes.map((s) => ({ value: s.id, label: s.name }))}
                  />
                  <Input
                    allowClear
                    prefix={<AudioOutlined />}
                    placeholder="输快捷码直达，如 hy2 / aa1"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <div
                    style={{
                      maxHeight: "42vh",
                      overflowY: "auto",
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                    }}
                  >
                    {query.trim() ? (
                      results.length === 0 ? (
                        <Empty description={`没有匹配「${query}」的话术`} />
                      ) : (
                        results.map((item) => renderScriptRow(item, phase !== "active"))
                      )
                    ) : !currentScene ? (
                      <Empty description="选一个场景开始" />
                    ) : currentScene.scripts.length === 0 ? (
                      <Empty description="这个场景还没有话术" />
                    ) : (
                      currentScene.scripts.map((item) => renderScriptRow(item, phase !== "active"))
                    )}
                  </div>
                </Space>
              </Card>
            </Col>
          </Row>

          {/* ---------- 挂断后：话术小结 ---------- */}
          {phase === "ended" ? (
            <Card
              size="small"
              title="这通电话用了哪些话术"
              extra={
                <Space>
                  <Button onClick={() => void openReplay(call)}>回放对话</Button>
                  <Button type="primary" icon={<PhoneOutlined />} onClick={resetToIdle}>
                    再来一通
                  </Button>
                </Space>
              }
            >
              <Space size={12} wrap style={{ marginBottom: 10 }}>
                <Typography.Text type="secondary">
                  通话时长 {fmtClock(callSec)} · 轮次 {messages.filter((m) => m.role === "student").length}
                </Typography.Text>
                {summary ? (
                  <Typography.Text type="secondary">话术 {summary.used_count} 条</Typography.Text>
                ) : null}
              </Space>
              {renderSummaryList(summary)}
            </Card>
          ) : null}
        </>
      ) : null}

      {/* ---------- 回放弹窗 ---------- */}
      <Modal
        open={!!replayCall}
        onCancel={() => {
          setReplayCall(null)
          setReplayMessages([])
          setReplaySummary(null)
        }}
        footer={null}
        width={720}
        title={
          replayCall ? (
            <Space size={8} wrap>
              <span>通话回放</span>
              <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                {fmtTime(replayCall.created_at)} · {categories.find((c) => c.key === replayCall.category)?.label ?? replayCall.category}
              </Typography.Text>
            </Space>
          ) : (
            "通话回放"
          )
        }
      >
        {replayCall ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            {replayMessages.length === 0 ? (
              <Empty description="这通电话没有对话记录（没接听就挂了？）" />
            ) : (
              <div style={{ maxHeight: "48vh", overflowY: "auto" }}>
                {replayMessages.map((m) => renderBubble(m, true))}
              </div>
            )}
            {replayCall.status === "finished" ? (
              <Card size="small" title="话术小结">
                {replaySummary ? (
                  renderSummaryList(replaySummary)
                ) : (
                  <Button size="small" onClick={() => void loadReplaySummary(replayCall.id)}>
                    查看用了哪些话术
                  </Button>
                )}
              </Card>
            ) : null}
          </Space>
        ) : null}
      </Modal>
    </div>
  )
}

/** 客户回复的本地形状（与后端 PracticeReplyOut 一致，这里仅用于内部传参） */
interface PracticeReplyLocal {
  content: string
  is_finished: boolean
  next_turn: number
}
