import { useEffect, useState, useMemo } from "react"
import {
  Card,
  Row,
  Col,
  Spin,
  Empty,
  Table,
  Tag,
  Statistic,
  Space,
  Segmented,
} from "antd"
import {
  ThunderboltOutlined,
  TrophyOutlined,
  AimOutlined,
  BarChartOutlined,
} from "@ant-design/icons"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  BarChart,
  Bar,
  Legend,
} from "recharts"
import { practiceApi } from "../api"
import { errMsg } from "../api/client"
import { App as AntdApp } from "antd"
import { useAuth } from "../context/AuthContext"
import type { PracticeScoreSummary } from "../types/api"
import { useNavigate } from "react-router-dom"

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

const CATEGORY_COLORS: Record<string, string> = {
  member: "#1677ff",
  rate: "#722ed1",
  overdue: "#fa8c16",
  repayment: "#52c41a",
  complaint: "#ff4d4f",
  settlement: "#13c2c2",
  audit: "#eb2f96",
  credentials: "#faad14",
}

export default function PracticeHistoryPage() {
  const nav = useNavigate()
  const { message } = AntdApp.useApp()
  // 【P1-4 修复】"全部"视图依赖讲师接口 /practice/scores/all（require_teacher），
  // 学生切换必然 403；这里按角色决定是否提供该选项，学生强制停留在"我的"
  const { user } = useAuth()
  const isManager = user?.role === "teacher" || user?.role === "admin"
  const [scores, setScores] = useState<PracticeScoreSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<"mine" | "all">("mine")

  useEffect(() => {
    // 【P1-4 修复】非管理员防御性回落到"我的"，避免异常状态下仍请求讲师接口
    const effectiveView = isManager ? view : "mine"
    let alive = true
    ;(async () => {
      setLoading(true)
      try {
        const data =
          effectiveView === "mine"
            ? await practiceApi.myPracticeScores()
            : await practiceApi.allPracticeScores()
        if (alive) setScores(data)
      } catch (e) {
        message.error(errMsg(e, "加载评分记录失败"))
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [view, isManager, message])

  const stats = useMemo(() => {
    if (scores.length === 0)
      return { total: 0, avgTotal: 0, avgTurns: 0, categories: 0 }
    const total = scores.length
    const avgTotal = scores.reduce((s, r) => s + r.total, 0) / total
    const avgTurns = scores.reduce((s, r) => s + r.current_turn, 0) / total
    const categories = new Set(scores.map((r) => r.category)).size
    return { total, avgTotal, avgTurns, categories }
  }, [scores])

  const trendData = useMemo(() => {
    return [...scores]
      .reverse()
      .slice(-20)
      .map((r, i) => ({
        name: `#${i + 1}`,
        总分: r.total,
        准确性: r.accuracy,
        话术: r.etiquette,
      }))
  }, [scores])

  const radarData = useMemo(() => {
    if (scores.length === 0) return []
    const dims = ["accuracy", "completeness", "etiquette", "responsiveness", "knowledge_use"] as const
    const labels: Record<string, string> = {
      accuracy: "准确性",
      completeness: "完整度",
      etiquette: "话术规范",
      responsiveness: "响应速度",
      knowledge_use: "知识运用",
    }
    return dims.map((d) => ({
      dim: labels[d],
      score: Math.round(scores.reduce((s, r) => s + (r[d] || 0), 0) / scores.length),
    }))
  }, [scores])

  const categoryData = useMemo(() => {
    const map: Record<string, { total: number; count: number }> = {}
    for (const r of scores) {
      if (!map[r.category]) map[r.category] = { total: 0, count: 0 }
      map[r.category].total += r.total
      map[r.category].count += 1
    }
    return Object.entries(map).map(([key, v]) => ({
      name: CATEGORY_LABELS[key] || key,
      avg: Math.round(v.total / v.count),
      count: v.count,
    }))
  }, [scores])

  const weakPointsData = useMemo(() => {
    const map: Record<string, number> = {}
    for (const r of scores) {
      for (const p of r.weak_points || []) {
        const key = p.length > 20 ? p.slice(0, 20) + "..." : p
        map[key] = (map[key] || 0) + 1
      }
    }
    return Object.entries(map)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [scores])

  const columns = [
    {
      title: "分类",
      dataIndex: "category",
      render: (cat: string) => (
        <Tag color={CATEGORY_COLORS[cat] || "blue"}>
          {CATEGORY_LABELS[cat] || cat}
        </Tag>
      ),
    },
    { title: "学员", dataIndex: "student_name", width: 100 },
    {
      title: "总分",
      dataIndex: "total",
      width: 80,
      render: (v: number) => (
        <span style={{ color: v >= 80 ? "#52c41a" : v >= 60 ? "#faad14" : "#ff4d4f", fontWeight: 600 }}>
          {v.toFixed(1)}
        </span>
      ),
    },
    { title: "准确性", dataIndex: "accuracy", width: 80, render: (v: number) => v?.toFixed(1) },
    { title: "完整度", dataIndex: "completeness", width: 80, render: (v: number) => v?.toFixed(1) },
    { title: "话术", dataIndex: "etiquette", width: 80, render: (v: number) => v?.toFixed(1) },
    { title: "响应", dataIndex: "responsiveness", width: 80, render: (v: number) => v?.toFixed(1) },
    { title: "知识", dataIndex: "knowledge_use", width: 80, render: (v: number) => v?.toFixed(1) },
    { title: "轮数", dataIndex: "current_turn", width: 60 },
    {
      title: "操作",
      width: 80,
      render: (_: unknown, r: PracticeScoreSummary) => (
        <a onClick={() => nav(`/practice/${r.session_id}`)}>查看</a>
      ),
    },
  ]

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (scores.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Empty
          description="暂无演练记录，去练习一下吧"
          style={{ marginBottom: 24 }}
        />
        <Space>
          <ThunderboltOutlined style={{ fontSize: 48, color: "#1677ff" }} />
        </Space>
        <div style={{ marginTop: 16 }}>
          <a onClick={() => nav("/practice")}>前往 Q&A 演练场 →</a>
        </div>
      </div>
    )
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={6}>
          <Card>
            <Statistic
              title="演练次数"
              value={stats.total}
              prefix={<AimOutlined style={{ color: "#1677ff" }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card>
            <Statistic
              title="平均总分"
              value={stats.avgTotal}
              precision={1}
              suffix="/100"
              prefix={<TrophyOutlined style={{ color: "#faad14" }} />}
              valueStyle={{ color: stats.avgTotal >= 80 ? "#52c41a" : "#faad14" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card>
            <Statistic
              title="覆盖分类"
              value={stats.categories}
              suffix="/8"
              prefix={<BarChartOutlined style={{ color: "#722ed1" }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={6}>
          <Card>
            <Statistic
              title="平均轮数"
              value={stats.avgTurns}
              precision={1}
              prefix={<ThunderboltOutlined style={{ color: "#13c2c2" }} />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="分数趋势" size="small">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" style={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} style={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="总分" stroke="#1677ff" strokeWidth={2} />
                <Line type="monotone" dataKey="准确性" stroke="#52c41a" strokeWidth={1} />
                <Line type="monotone" dataKey="话术" stroke="#fa8c16" strokeWidth={1} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="维度雷达图" size="small">
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={radarData}>
                <PolarGrid />
                <PolarAngleAxis dataKey="dim" style={{ fontSize: 11 }} />
                <PolarRadiusAxis domain={[0, 100]} />
                <Radar
                  name="平均分"
                  dataKey="score"
                  stroke="#1677ff"
                  fill="#1677ff"
                  fillOpacity={0.3}
                />
                <Tooltip />
              </RadarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="分类平均分" size="small">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={categoryData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" style={{ fontSize: 10 }} angle={-15} textAnchor="end" height={60} />
                <YAxis domain={[0, 100]} style={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="avg" fill="#1677ff" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="薄弱点分布" size="small">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={weakPointsData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" style={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={120}
                  style={{ fontSize: 10 }}
                />
                <Tooltip />
                <Bar dataKey="count" fill="#ff4d4f" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      <Card
        title="演练记录"
        size="small"
        style={{ marginTop: 16 }}
        extra={
          // 【P1-4 修复】学生不显示"全部"选项（后端为讲师接口，学生请求必 403）
          <Segmented
            value={isManager ? view : "mine"}
            onChange={(v) => isManager && setView(v as "mine" | "all")}
            options={
              isManager
                ? [
                    { label: "我的", value: "mine" },
                    { label: "全部", value: "all" },
                  ]
                : [{ label: "我的", value: "mine" }]
            }
          />
        }
      >
        <Table
          columns={columns}
          dataSource={scores}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10 }}
          scroll={{ x: 800 }}
          expandable={{
            expandedRowRender: (r: PracticeScoreSummary) => (
              <div style={{ fontSize: 13 }}>
                {r.summary && (
                  <p style={{ marginBottom: 8 }}>
                    <b>总结：</b>
                    {r.summary}
                  </p>
                )}
                {(r.weak_points?.length ?? 0) > 0 && (
                  <p style={{ marginBottom: 8 }}>
                    <b>薄弱点：</b>
                    {r.weak_points.join("；")}
                  </p>
                )}
                {r.suggestions && (
                  <p style={{ marginBottom: 0 }}>
                    <b>改进建议：</b>
                    {r.suggestions}
                  </p>
                )}
                {r.business_summary && (
                  <p style={{ marginBottom: 0, marginTop: 8 }}>
                    <b>业务小结：</b>
                    {r.business_summary}
                  </p>
                )}
              </div>
            ),
          }}
        />
      </Card>
    </div>
  )
}
