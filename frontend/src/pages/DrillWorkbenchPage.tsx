import { useEffect, useRef, useState, useCallback } from "react"
import {
  Row,
  Col,
  Card,
  Input,
  Button,
  Typography,
  Space,
  Tag,
  Spin,
  Empty,
  Progress,
  Descriptions,
  Statistic,
  theme,
  App as AntdApp,
  Divider,
  Collapse,
  Alert,
  Tooltip,
  Popconfirm,
} from "antd"
import {
  SendOutlined,
  StopOutlined,
  BulbOutlined,
  ReloadOutlined,
} from "@ant-design/icons"
import { useParams, useNavigate } from "react-router-dom"
import { scenariosApi, sessionsApi } from "../api"
import { useAuth } from "../context/AuthContext"
import { errMsg } from "../api/client"
import AiProgressBar from "../components/AiProgressBar"
import type { DrillSession, Scenario, Message, PracticeHint, Score } from "../types/api"

const STATUS_LABEL: Record<string, string> = {
  pending: "待开始",
  in_progress: "进行中",
  finished: "已完成",
  canceled: "已取消",
}

export default function DrillWorkbenchPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const nav = useNavigate()
  const { message } = AntdApp.useApp()
  const { token } = theme.useToken()
  const { user } = useAuth()

  const [session, setSession] = useState<DrillSession | null>(null)
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const [scoring, setScoring] = useState(false)
  const [score, setScore] = useState<Score | null>(null)
  const [hints, setHints] = useState<PracticeHint[]>([])
  const [loadingHints, setLoadingHints] = useState(false)
  const [loading, setLoading] = useState(true)
  const [canceling, setCanceling] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const loadHints = useCallback(
    async (sid: string) => {
      if (!sid) return
      setLoadingHints(true)
      try {
        const h = await sessionsApi.getSessionHints(sid)
        setHints(h)
      } catch {
        // 提示是辅助功能，失败静默
      } finally {
        setLoadingHints(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (!sessionId) return
    let alive = true
    ;(async () => {
      try {
        const s = await sessionsApi.getSession(sessionId)
        if (!alive) return
        setSession(s)
        const sc = await scenariosApi.getScenario(s.scenario_id)
        if (!alive) return
        setScenario(sc)
        if (s.status === "pending") {
          // 【P2-5 修复】自动 start 在双开标签页时会 400（会话已被另一个 tab 启动），
          // 属正常情况。原先 400 会抛到外层 catch 中断整页加载（消息/评分都不拉了），
          // 现在单独捕获，继续走正常回放加载
          try {
            await sessionsApi.startSession(sessionId)
          } catch {
            // 已被其他标签页启动：直接拉取消息继续
          }
        }
        // 拉对话历史
        const msgs = await sessionsApi.listMessages(sessionId)
        if (!alive) return
        setMessages(msgs)
        setSession((prev) =>
          prev ? { ...prev, status: prev.status === "pending" ? "in_progress" : prev.status } : prev,
        )
        // 【P1-1 修复】加载已有评分：与 PracticeWorkbenchPage 对齐。
        // 此前刷新页面或讲师回放已评分会话时 score 恒为 null，看不到评分结果卡片
        try {
          const existingScore = await sessionsApi.getScore(sessionId)
          if (!alive) return
          setScore(existingScore)
        } catch {
          // 尚未评分属正常情况，静默忽略
        }
        // 加载知识提示
        loadHints(sessionId)
      } catch (e) {
        message.error(errMsg(e, "加载会话失败"))
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [sessionId, message, loadHints])

  // 自动滚到底
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // 【P4-3 修复】"已取消"同样视为结束：否则被放弃的会话输入框仍可编辑、发送必然 400
  const isFinished =
    session?.status === "finished" || session?.status === "canceled" || !!score
  const isOwner = !!user && !!session && user.id === session.student_id
  const maxTurns = scenario?.max_turns ?? 5
  const progressPercent = session ? (session.current_turn / maxTurns) * 100 : 0

  const handleSend = async () => {
    const content = input.trim()
    if (!content || !sessionId || !session || sending || isFinished) return
    setInput("")
    setSending(true)
    // 乐观追加学员消息
    const optimisticStudent: Message = {
      id: `temp-${Date.now()}`,
      role: "student",
      content,
      turn: session.current_turn,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticStudent])
    try {
      const reply = await sessionsApi.replySession(sessionId, { content })
      setMessages((prev) => [
        ...prev,
        {
          id: `temp-c-${Date.now()}`,
          role: "customer",
          content: reply.content,
          turn: reply.next_turn,
          created_at: new Date().toISOString(),
        },
      ])
      setSession((prev) => (prev ? { ...prev, current_turn: reply.next_turn } : prev))
      if (reply.is_finished) {
        message.warning("剧本已演完，请点击结束并评分")
      }
    } catch (e) {
      message.error(errMsg(e, "回复失败"))
      setMessages((prev) => prev.filter((m) => m.id !== optimisticStudent.id))
    } finally {
      setSending(false)
    }
  }

  const handleScore = async () => {
    if (!sessionId) return
    setScoring(true)
    try {
      const result = await sessionsApi.scoreSession(sessionId)
      setScore(result)
      setSession((prev) => (prev ? { ...prev, status: "finished" } : prev))
      message.success("评分完成")
    } catch (e) {
      message.error(errMsg(e, "评分失败"))
    } finally {
      setScoring(false)
    }
  }

  // 【P4-3 修复】放弃演练：把 in_progress 会话置为 canceled，避免永久挂起污染统计
  const handleCancelSession = async () => {
    if (!sessionId) return
    setCanceling(true)
    try {
      const updated = await sessionsApi.cancelSession(sessionId)
      setSession(updated)
      message.success("已放弃本次演练")
      nav("/sessions")
    } catch (e) {
      message.error(errMsg(e, "放弃失败"))
    } finally {
      setCanceling(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!session || !scenario) {
    return <Empty description="会话不存在" style={{ marginTop: 80 }} />
  }

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={17}>
        <Card
          title={
            <Space>
              <Typography.Text strong>{scenario.title}</Typography.Text>
              <Tag>{scenario.code}</Tag>
              <Tag color={session.status === "in_progress" ? "processing" : session.status === "finished" ? "success" : "default"}>
                {STATUS_LABEL[session.status]}
              </Tag>
            </Space>
          }
          extra={
            <Space>
              {/* 【P4-3 修复】放弃演练：仅属主、且会话仍在进行中时可见 */}
              {isOwner && !isFinished && (
                <Popconfirm
                  title="放弃本次演练？"
                  description="放弃后不可继续，且不会生成评分。"
                  okText="放弃"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={handleCancelSession}
                >
                  <Button danger loading={canceling}>
                    放弃演练
                  </Button>
                </Popconfirm>
              )}
              <Button
                type="primary"
                danger
                icon={<StopOutlined />}
                loading={scoring}
                disabled={isFinished || messages.length === 0}
                onClick={handleScore}
              >
                结束并评分
              </Button>
            </Space>
          }
          styles={{ body: { padding: 0, display: "flex", flexDirection: "column", height: "calc(100vh - 220px)", minHeight: 400 } }}
        >
          <div style={{ flex: 1, overflowY: "auto", padding: 16, background: token.colorBgLayout }}>
            {messages.length === 0 ? (
              <Empty description="等待客户开场..." style={{ marginTop: 60 }} />
            ) : (
              messages.map((m) => (
                <div
                  key={m.id}
                  style={{
                    display: "flex",
                    justifyContent: m.role === "student" ? "flex-end" : "flex-start",
                    marginBottom: 12,
                  }}
                >
                  <div
                    style={{
                      maxWidth: "75%",
                      padding: "10px 14px",
                      borderRadius: 8,
                      background: m.role === "student" ? token.colorPrimary : token.colorBgContainer,
                      color: m.role === "student" ? token.colorWhite : token.colorText,
                      border: m.role === "student" ? "none" : `1px solid ${token.colorBorderSecondary}`,
                      boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4 }}>
                      {m.role === "student" ? "学员" : "客户"} · 第 {m.turn} 轮
                    </div>
                    {m.content}
                  </div>
                </div>
              ))
            )}
            {sending && (
              <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12 }}>
                <div
                  style={{
                    width: 300,
                    padding: "10px 14px",
                    borderRadius: 8,
                    background: token.colorBgContainer,
                    border: `1px solid ${token.colorBorderSecondary}`,
                  }}
                >
                  <div style={{ color: token.colorTextTertiary, marginBottom: 4 }}>
                    <Spin size="small" /> 客户正在输入...
                  </div>
                  <AiProgressBar active label="AI 生成回复" />
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
          <div style={{ padding: 12, background: token.colorBgContainer, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={isFinished ? "演练已结束" : "输入回复内容（Enter 发送，Shift+Enter 换行）"}
              autoSize={{ minRows: 2, maxRows: 4 }}
              disabled={isFinished}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              maxLength={2000}
            />
            <div style={{ marginTop: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {input.length}/2000
              </Typography.Text>
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={sending}
                disabled={!input.trim() || isFinished}
                onClick={handleSend}
              >
                发送
              </Button>
            </div>
          </div>
        </Card>
      </Col>

      <Col xs={24} lg={7}>
        <Card title="剧本信息" size="small" style={{ marginBottom: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="难度">{scenario.difficulty} / 5</Descriptions.Item>
            <Descriptions.Item label="最大轮数">{scenario.max_turns}</Descriptions.Item>
            <Descriptions.Item label="当前轮数">{session.current_turn}</Descriptions.Item>
          </Descriptions>
          <Progress percent={Math.min(progressPercent, 100)} status="active" />
          <Divider style={{ margin: "12px 0" }} />
          <Typography.Paragraph type="secondary" ellipsis={{ rows: 4 }} style={{ fontSize: 12, marginBottom: 0 }}>
            客户人设：{scenario.customer_persona}
          </Typography.Paragraph>
        </Card>

        <Card
          title={
            <Space>
              <BulbOutlined style={{ color: "#faad14" }} />
              <Typography.Text strong style={{ fontSize: 14 }}>
                知识提示
              </Typography.Text>
            </Space>
          }
          size="small"
          style={{ marginBottom: 16 }}
          extra={
            <Tooltip title="刷新提示">
              <Button
                size="small"
                type="text"
                icon={<ReloadOutlined />}
                loading={loadingHints}
                onClick={() => sessionId && loadHints(sessionId)}
              />
            </Tooltip>
          }
        >
          {hints.length === 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              暂无相关知识提示
            </Typography.Text>
          ) : (
            <Collapse
              size="small"
              items={hints.map((h, i) => ({
                key: i,
                label: (
                  <Typography.Text strong style={{ fontSize: 12 }}>
                    {h.title}
                  </Typography.Text>
                ),
                children: (
                  <div>
                    <Typography.Paragraph
                      style={{ fontSize: 12, marginBottom: 4, whiteSpace: "pre-wrap" }}
                    >
                      {h.content}
                    </Typography.Paragraph>
                    {h.tags.length > 0 && (
                      <Space size={4} wrap>
                        {h.tags.map((t) => (
                          <Tag key={t} style={{ fontSize: 10 }}>
                            {t}
                          </Tag>
                        ))}
                      </Space>
                    )}
                  </div>
                ),
              }))}
            />
          )}
          <Alert
            type="info"
            showIcon
            message="参考话术仅供学习，实际演练中请用自己的话回复客户"
            style={{ marginTop: 8, fontSize: 11 }}
          />
        </Card>

        {scoring && !score && (
          <Card title="正在评分" size="small">
            <AiProgressBar active label="AI 多维评分" tip="本地模型约 40–60 秒" />
          </Card>
        )}

        {score && (
          <Card title="评分结果" size="small">
            <Row gutter={[8, 8]}>
              <Col span={24} style={{ textAlign: "center" }}>
                <Statistic
                  title="总分"
                  value={score.total}
                  suffix="/ 100"
                  valueStyle={{ color: score.total >= 80 ? "#52c41a" : score.total >= 60 ? "#faad14" : "#ff4d4f" }}
                />
              </Col>
            </Row>
            <Divider style={{ margin: "12px 0" }} />
            <Descriptions column={1} size="small">
              <Descriptions.Item label="准确性">{score.accuracy.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="完整性">{score.completeness.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="礼仪">{score.etiquette.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="响应速度">{score.responsiveness.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="知识运用">{score.knowledge_use.toFixed(1)}</Descriptions.Item>
            </Descriptions>
            <Divider style={{ margin: "12px 0" }} />
            <Typography.Paragraph style={{ fontSize: 12 }}>
              <Typography.Text strong>总结：</Typography.Text>
              {score.summary}
            </Typography.Paragraph>
            {score.weak_points.length > 0 && (
              <div>
                <Typography.Text strong style={{ fontSize: 12 }}>薄弱点：</Typography.Text>
                <div style={{ marginTop: 4 }}>
                  {score.weak_points.map((p, i) => (
                    <Tag key={i} color="orange" style={{ marginBottom: 4 }}>{p}</Tag>
                  ))}
                </div>
              </div>
            )}
            <Button type="link" block onClick={() => nav("/sessions")} style={{ marginTop: 8 }}>
              查看演练记录 →
            </Button>
          </Card>
        )}
      </Col>
    </Row>
  )
}
