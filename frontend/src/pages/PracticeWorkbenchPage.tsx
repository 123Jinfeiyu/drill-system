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
  UserOutlined,
} from "@ant-design/icons"
import { useParams, useNavigate } from "react-router-dom"
import { practiceApi } from "../api"
import { errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import AiProgressBar from "../components/AiProgressBar"
import { PRACTICE_SCRIPTS } from "../data/practiceScripts"
import type {
  PracticeSession,
  PracticeReplyOut,
  Message,
  PracticeScore,
  PracticeHint,
} from "../types/api"

const STATUS_LABEL: Record<string, string> = {
  pending: "待开始",
  in_progress: "进行中",
  finished: "已完成",
  canceled: "已取消",
}

const CATEGORY_LABELS: Record<string, string> = {
  member: "会员相关",
  rate: "利率与资方",
  overdue: "逾期与催收",
  repayment: "还款问题",
  complaint: "投诉与外投",
  settlement: "结清与退费",
  audit: "审核与订单",
  credentials: "凭证与合同",
}

const DIFFICULTY_LABELS: Record<number, string> = {
  1: "入门",
  2: "标准",
  3: "进阶",
  4: "困难",
  5: "极限",
}

const DIFFICULTY_COLORS: Record<number, string> = {
  1: "green",
  2: "blue",
  3: "gold",
  4: "orange",
  5: "red",
}

export default function PracticeWorkbenchPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const nav = useNavigate()
  const { message } = AntdApp.useApp()
  const { token } = theme.useToken()
  const { user } = useAuth()

  const [session, setSession] = useState<PracticeSession | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const [scoring, setScoring] = useState(false)
  const [score, setScore] = useState<PracticeScore | null>(null)
  const [hints, setHints] = useState<PracticeHint[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingHints, setLoadingHints] = useState(false)
  const [canceling, setCanceling] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const loadHints = useCallback(
    async (sid: string) => {
      if (!sid) return
      setLoadingHints(true)
      try {
        const h = await practiceApi.getPracticeHints(sid)
        setHints(h)
      } catch {
        // 静默失败，提示是辅助功能
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
        const s = await practiceApi.getPracticeSession(sessionId)
        if (!alive) return
        setSession(s)
        if (s.status === "pending") {
          // 【P2-5 修复】自动 start 在双开标签页时会 400（会话已被另一个 tab 启动），
          // 属正常情况。原先 400 会抛到外层 catch 中断整页加载，现在单独捕获继续加载
          try {
            await practiceApi.startPracticeSession(sessionId)
          } catch {
            // 已被其他标签页启动：直接拉取消息继续
          }
        }
        const msgs = await practiceApi.listPracticeMessages(sessionId)
        if (!alive) return
        setMessages(msgs)
        setSession((prev) =>
          prev
            ? { ...prev, status: prev.status === "pending" ? "in_progress" : prev.status }
            : prev,
        )
        // 加载知识提示
        loadHints(sessionId)
        // 尝试加载已有评分
        try {
          const existingScore = await practiceApi.getPracticeScore(sessionId)
          if (!alive) return
          setScore(existingScore)
        } catch {
          // 没有评分是正常的
        }
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

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // 【P4-3 修复】"已取消"同样视为结束：否则被放弃的会话输入框仍可编辑、发送必然 400
  const isFinished =
    session?.status === "finished" || session?.status === "canceled" || !!score
  const isOwner = !!user && !!session && user.id === session.student_id
  const hasScore = !!score
  const maxTurns = session?.max_turns ?? 8
  const progressPercent = session ? (session.current_turn / maxTurns) * 100 : 0

  const handleSend = async () => {
    const content = input.trim()
    if (!content || !sessionId || !session || sending || isFinished) return
    setInput("")
    setSending(true)
    const optimisticStudent: Message = {
      id: `temp-${Date.now()}`,
      role: "student",
      content,
      turn: session.current_turn,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticStudent])
    try {
      const reply: PracticeReplyOut = await practiceApi.replyPracticeSession(sessionId, { content })
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
        message.warning("对话已结束，请点击结束并评分")
      }
      // 刷新提示
      loadHints(sessionId)
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
      const result = await practiceApi.scorePracticeSession(sessionId)
      setScore(result)
      setSession((prev) => (prev ? { ...prev, status: "finished" } : prev))
      message.success("评分完成")
    } catch (e) {
      message.error(errMsg(e, "评分失败"))
    } finally {
      setScoring(false)
    }
  }

  // 【P4-3 修复】放弃演练场会话：置为 canceled，避免永久挂起污染统计
  const handleCancelPractice = async () => {
    if (!sessionId) return
    setCanceling(true)
    try {
      const updated = await practiceApi.cancelPracticeSession(sessionId)
      setSession(updated)
      message.success("已放弃本次演练")
      nav("/practice")
    } catch (e) {
      message.error(errMsg(e, "放弃失败"))
    } finally {
      setCanceling(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" tip="正在生成客户人设..." />
      </div>
    )
  }

  if (!session) {
    return <Empty description="演练会话不存在" style={{ marginTop: 80 }} />
  }

  const categoryLabel = CATEGORY_LABELS[session.category] || session.category

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={17}>
        <Card
          title={
            <Space>
              <Typography.Text strong>{categoryLabel} - Q&A 演练</Typography.Text>
              <Tag color={DIFFICULTY_COLORS[session.difficulty] || "blue"}>
                {DIFFICULTY_LABELS[session.difficulty] || session.difficulty}
              </Tag>
              <Tag
                color={
                  session.status === "in_progress"
                    ? "processing"
                    : session.status === "finished"
                      ? "success"
                      : "default"
                }
              >
                {STATUS_LABEL[session.status]}
              </Tag>
            </Space>
          }
          extra={
            <Space>
              <Button
                icon={<ReloadOutlined />}
                onClick={() => nav("/practice")}
              >
                换一个
              </Button>
              {/* 【P4-3 修复】放弃演练：仅属主、且会话仍在进行中时可见 */}
              {isOwner && !isFinished && (
                <Popconfirm
                  title="放弃本次演练？"
                  description="放弃后不可继续，且不会生成评分。"
                  okText="放弃"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={handleCancelPractice}
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
                disabled={hasScore || messages.length === 0}
                onClick={handleScore}
              >
                结束并评分
              </Button>
            </Space>
          }
          styles={{
            body: {
              padding: 0,
              display: "flex",
              flexDirection: "column",
              height: "calc(100vh - 220px)",
              minHeight: 400,
            },
          }}
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
                      {m.role === "student" ? "客服（你）" : "客户"} · 第 {m.turn} 轮
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
            <Collapse
              size="small"
              ghost
              style={{ marginBottom: 8 }}
              items={[
                {
                  key: "scripts",
                  label: (
                    <Typography.Text style={{ fontSize: 12 }}>
                      💡 回复话术备选（点击填入回复框，可编辑后发送）
                    </Typography.Text>
                  ),
                  children: (
                    <div style={{ maxHeight: 220, overflowY: "auto" }}>
                      {PRACTICE_SCRIPTS.map((g) => (
                        <div key={g.title} style={{ marginBottom: 10 }}>
                          <div style={{ fontSize: 11, color: token.colorTextTertiary, marginBottom: 4 }}>
                            {g.title}
                          </div>
                          <Space size={[4, 4]} wrap>
                            {g.items.map((it) => (
                              <Button
                                key={it.key}
                                size="small"
                                style={{ fontSize: 12 }}
                                disabled={isFinished}
                                onClick={() => setInput(it.text)}
                              >
                                {it.label}
                              </Button>
                            ))}
                          </Space>
                        </div>
                      ))}
                    </div>
                  ),
                },
              ]}
            />
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
            <div
              style={{
                marginTop: 8,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
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
        <Card title="演练信息" size="small" style={{ marginBottom: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="业务分类">{categoryLabel}</Descriptions.Item>
            <Descriptions.Item label="难度">
              <Tag color={DIFFICULTY_COLORS[session.difficulty] || "blue"}>
                {DIFFICULTY_LABELS[session.difficulty] || session.difficulty}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="最大轮数">{session.max_turns}</Descriptions.Item>
            <Descriptions.Item label="当前轮数">{session.current_turn}</Descriptions.Item>
          </Descriptions>
          <Progress percent={Math.min(progressPercent, 100)} status="active" />
          <Divider style={{ margin: "12px 0" }} />
          <div
            style={{
              padding: 8,
              background: token.colorFillQuaternary,
              borderRadius: 6,
              fontSize: 12,
              color: token.colorTextSecondary,
            }}
          >
            <Space>
              <UserOutlined />
              <Typography.Text strong style={{ fontSize: 12 }}>
                客户人设
              </Typography.Text>
            </Space>
            <Typography.Paragraph
              type="secondary"
              ellipsis={{ rows: 5 }}
              style={{ fontSize: 12, marginBottom: 0, marginTop: 4 }}
            >
              {session.persona}
            </Typography.Paragraph>
          </div>
        </Card>

        {/* 知识提示卡片 */}
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

        {/* 评分中进度 */}
        {scoring && !score && (
          <Card title="正在评分" size="small">
            <AiProgressBar active label="AI 多维评分" tip="本地模型约 40–60 秒" />
          </Card>
        )}

        {/* 评分结果 */}
        {score && (
          <Card title="评分结果" size="small">
            <Row gutter={[8, 8]}>
              <Col span={24} style={{ textAlign: "center" }}>
                <Statistic
                  title="总分"
                  value={score.total}
                  suffix="/ 100"
                  valueStyle={{
                    color: score.total >= 80 ? "#52c41a" : score.total >= 60 ? "#faad14" : "#ff4d4f",
                  }}
                />
              </Col>
            </Row>
            <Divider style={{ margin: "12px 0" }} />
            <Descriptions column={1} size="small">
              <Descriptions.Item label="准确性">{score.accuracy.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="完整度">{score.completeness.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="话术规范">{score.etiquette.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="响应速度">{score.responsiveness.toFixed(1)}</Descriptions.Item>
              <Descriptions.Item label="知识运用">{score.knowledge_use.toFixed(1)}</Descriptions.Item>
            </Descriptions>
            <Divider style={{ margin: "12px 0" }} />
            <Typography.Paragraph style={{ fontSize: 12 }}>
              <Typography.Text strong>总结：</Typography.Text>
              {score.summary}
            </Typography.Paragraph>
            {score.weak_points.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <Typography.Text strong style={{ fontSize: 12 }}>
                  薄弱点：
                </Typography.Text>
                <div style={{ marginTop: 4 }}>
                  {score.weak_points.map((p, i) => (
                    <Tag key={i} color="orange" style={{ marginBottom: 4 }}>
                      {p}
                    </Tag>
                  ))}
                </div>
              </div>
            )}
            {score.suggestions && (
              <Alert
                type="warning"
                showIcon
                message="改进建议"
                description={score.suggestions}
                style={{ marginTop: 8 }}
              />
            )}
            {score.business_summary && (
              <div style={{ marginTop: 12, padding: 8, background: token.colorFillQuaternary, borderRadius: 6 }}>
                <Typography.Text strong style={{ fontSize: 12 }}>
                  📋 业务小结：
                </Typography.Text>
                <Typography.Paragraph
                  style={{ fontSize: 12, marginBottom: 0, marginTop: 4, whiteSpace: "pre-wrap" }}
                >
                  {score.business_summary}
                </Typography.Paragraph>
              </div>
            )}
            <Button
              type="link"
              block
              onClick={() => nav("/practice")}
              style={{ marginTop: 8 }}
            >
              再练一次 →
            </Button>
          </Card>
        )}
      </Col>
    </Row>
  )
}
