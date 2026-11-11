import { useEffect, useState } from "react"
import {
  Card,
  Row,
  Col,
  Typography,
  Tag,
  Spin,
  Empty,
  Modal,
  Slider,
  InputNumber,
  Button,
  Space,
  Statistic,
  List,
  App as AntdApp,
  theme,
} from "antd"
import {
  ThunderboltOutlined,
  AimOutlined,
  RightOutlined,
  HistoryOutlined,
  TrophyOutlined,
} from "@ant-design/icons"
import { useNavigate } from "react-router-dom"
import { practiceApi } from "../api"
import { errMsg } from "../api/client"
import type { PracticeCategory, PracticeSession } from "../types/api"

const CATEGORY_ICONS: Record<string, string> = {
  member: "\uD83C\uDF1F",
  rate: "\uD83D\uDCB0",
  overdue: "\u23F0",
  repayment: "\uD83D\uDCB3",
  complaint: "\u26A1",
  settlement: "\uD83E\uDDFE",
  audit: "\uD83D\uDD0D",
  credentials: "\uD83D\uDDC4",
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

const STATUS_LABELS: Record<string, string> = {
  pending: "待开始",
  in_progress: "进行中",
  finished: "已完成",
  canceled: "已取消",
}

export default function PracticePage() {
  const nav = useNavigate()
  const { message } = AntdApp.useApp()
  const { token } = theme.useToken()
  const [categories, setCategories] = useState<PracticeCategory[]>([])
  const [recentSessions, setRecentSessions] = useState<PracticeSession[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [selected, setSelected] = useState<PracticeCategory | null>(null)
  const [difficulty, setDifficulty] = useState(2)
  const [maxTurns, setMaxTurns] = useState(10)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [cats, sessions] = await Promise.all([
          practiceApi.getCategories(),
          practiceApi.listMyPracticeSessions(),
        ])
        if (alive) {
          setCategories(cats)
          setRecentSessions(sessions.slice(0, 5))
        }
      } catch (e) {
        message.error(errMsg(e, "加载数据失败"))
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [message])

  const handleSelectCategory = (cat: PracticeCategory) => {
    setSelected(cat)
    setDifficulty(2)
    setMaxTurns(10)
    setModalOpen(true)
  }

  const handleStart = async () => {
    if (!selected) return
    setCreating(true)
    try {
      const session = await practiceApi.createPracticeSession({
        category: selected.key,
        difficulty,
        max_turns: maxTurns,
      })
      setModalOpen(false)
      nav(`/practice/${session.id}`)
    } catch (e) {
      message.error(errMsg(e, "创建演练失败"))
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (categories.length === 0) {
    return <Empty description="暂无可用业务分类" style={{ marginTop: 80 }} />
  }

  const completedCount = recentSessions.filter((s) => s.status === "finished").length

  return (
    <div>
      <Card
        style={{
          marginBottom: 16,
          background: "linear-gradient(135deg, #1677ff 0%, #0052d4 100%)",
          color: "#fff",
          border: "none",
        }}
      >
        <Row align="middle" gutter={[16, 8]}>
          <Col flex="auto">
            <Space align="center">
              <ThunderboltOutlined style={{ fontSize: 32 }} />
              <div>
                <Typography.Title level={3} style={{ color: "#fff", margin: 0 }}>
                  Q&A 演练场
                </Typography.Title>
                <Typography.Text style={{ color: "rgba(255,255,255,0.85)" }}>
                  AI 扮演客户咨询，你扮演客服应对。选择业务分类开始实战练习
                </Typography.Text>
              </div>
            </Space>
          </Col>
          <Col>
            <Row gutter={24}>
              <Col>
                <Statistic
                  title={<span style={{ color: "rgba(255,255,255,0.7)" }}>最近演练</span>}
                  value={recentSessions.length}
                  valueStyle={{ color: "#fff" }}
                />
              </Col>
              <Col>
                <Statistic
                  title={<span style={{ color: "rgba(255,255,255,0.7)" }}>已完成</span>}
                  value={completedCount}
                  valueStyle={{ color: "#fff" }}
                />
              </Col>
            </Row>
          </Col>
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        {categories.map((cat) => (
          <Col xs={24} sm={12} lg={6} key={cat.key}>
            <Card
              hoverable
              onClick={() => handleSelectCategory(cat)}
              style={{ height: "100%" }}
              styles={{ body: { padding: 20 } }}
            >
              <div style={{ fontSize: 32, marginBottom: 8 }}>
                {CATEGORY_ICONS[cat.key] || "\uD83D\uDCA1"}
              </div>
              <Typography.Title level={5} style={{ marginBottom: 4 }}>
                {cat.label}
              </Typography.Title>
              <Typography.Paragraph
                type="secondary"
                ellipsis={{ rows: 2 }}
                style={{ fontSize: 12, marginBottom: 8 }}
              >
                {cat.description}
              </Typography.Paragraph>
              <div>
                {cat.tags.slice(0, 4).map((t) => (
                  <Tag key={t} style={{ marginBottom: 4 }}>
                    {t}
                  </Tag>
                ))}
              </div>
              <Button
                type="link"
                style={{ padding: "4px 0", marginTop: 8 }}
                icon={<RightOutlined />}
              >
                开始练习
              </Button>
            </Card>
          </Col>
        ))}
      </Row>

      {recentSessions.length > 0 && (
        <Card
          title={
            <Space>
              <HistoryOutlined />
              <span>最近演练</span>
            </Space>
          }
          size="small"
          style={{ marginTop: 16 }}
          extra={
            <Button
              type="link"
              icon={<TrophyOutlined />}
              onClick={() => nav("/practice/history")}
            >
              演练统计
            </Button>
          }
        >
          <List
            size="small"
            dataSource={recentSessions}
            renderItem={(s) => (
              <List.Item
                actions={[
                  <a key="go" onClick={() => nav(`/practice/${s.id}`)}>
                    {s.status === "finished" ? "查看回放" : "继续练习"}
                  </a>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag color="blue">{CATEGORY_LABELS[s.category] || s.category}</Tag>
                      <Tag>{DIFFICULTY_LABELS[s.difficulty] || s.difficulty}</Tag>
                      <Tag color={s.status === "finished" ? "success" : "processing"}>
                        {STATUS_LABELS[s.status]}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                      {s.persona?.slice(0, 60) || "..."}
                    </Typography.Text>
                  }
                />
                <div style={{ textAlign: "right", fontSize: 12, color: "#999" }}>
                  第 {s.current_turn}/{s.max_turns} 轮
                </div>
              </List.Item>
            )}
          />
        </Card>
      )}

      <Modal
        title={selected ? `${CATEGORY_ICONS[selected.key] || ""} ${selected.label} - 演练设置` : ""}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleStart}
        okText="开始演练"
        cancelText="取消"
        confirmLoading={creating}
        okButtonProps={{ icon: <AimOutlined /> }}
      >
        {selected && (
          <div style={{ padding: "8px 0" }}>
            <Typography.Paragraph type="secondary">{selected.description}</Typography.Paragraph>
            <div style={{ marginBottom: 24 }}>
              <Typography.Text strong>难度等级</Typography.Text>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
                <Slider
                  min={1}
                  max={5}
                  value={difficulty}
                  onChange={setDifficulty}
                  style={{ flex: 1 }}
                  marks={DIFFICULTY_LABELS}
                />
                <Tag color={difficulty >= 4 ? "red" : difficulty >= 3 ? "orange" : "blue"}>
                  {DIFFICULTY_LABELS[difficulty]}
                </Tag>
              </div>
            </div>
            <div>
              <Typography.Text strong>最大对话轮数</Typography.Text>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
                <InputNumber
                  min={3}
                  max={20}
                  value={maxTurns}
                  onChange={(v) => setMaxTurns(v || 8)}
                  style={{ width: 120 }}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  建议 8-15 轮
                </Typography.Text>
              </div>
            </div>
            <div
              style={{
                marginTop: 16,
                padding: 12,
                background: token.colorFillQuaternary,
                borderRadius: 6,
                fontSize: 12,
                color: token.colorTextSecondary,
              }}
            >
              {"\u26A1"} AI 将根据分类和难度动态生成客户人设和开场白，每次练习的客户都不一样
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
