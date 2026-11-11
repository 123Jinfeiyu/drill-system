import { useEffect, useMemo, useState } from "react"
import {
  Card,
  Table,
  Tag,
  Button,
  Typography,
  Spin,
  Empty,
  App as AntdApp,
  Statistic,
  Row,
  Col,
  Select,
} from "antd"
import { useNavigate } from "react-router-dom"
import { EyeOutlined } from "@ant-design/icons"
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
} from "recharts"
import { sessionsApi } from "../api"
import { errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import type { DrillRecord, SessionStatus } from "../types/api"

const STATUS_LABEL: Record<SessionStatus, string> = {
  pending: "待开始",
  in_progress: "进行中",
  finished: "已完成",
  canceled: "已取消",
}

const STATUS_COLOR: Record<SessionStatus, string> = {
  pending: "default",
  in_progress: "processing",
  finished: "success",
  canceled: "error",
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  const hh = String(d.getHours()).padStart(2, "0")
  const mi = String(d.getMinutes()).padStart(2, "0")
  return `${mm}-${dd} ${hh}:${mi}`
}

function truncate(s: string, max = 12): string {
  return s.length > max ? s.slice(0, max) + "…" : s
}

function totalColor(total: number): string {
  if (total >= 80) return "#52c41a"
  if (total >= 60) return "#faad14"
  return "#ff4d4f"
}

export default function SessionsPage() {
  const nav = useNavigate()
  const { message } = AntdApp.useApp()
  const { user } = useAuth()
  const isTeacher = user?.role === "teacher" || user?.role === "admin"
  const [records, setRecords] = useState<DrillRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [scenarioFilter, setScenarioFilter] = useState<string | undefined>(undefined)
  const [studentFilter, setStudentFilter] = useState<string | undefined>(undefined)

  useEffect(() => {
    const fetchRecords = isTeacher ? sessionsApi.allDrillRecords() : sessionsApi.myDrillRecords()
    fetchRecords
      .then((rc) => setRecords(rc))
      .catch((e) => message.error(errMsg(e, "加载演练记录失败")))
      .finally(() => setLoading(false))
  }, [message, isTeacher])

  const filtered = useMemo(
    () =>
      records.filter(
        (s) =>
          (!scenarioFilter || s.scenario_title === scenarioFilter) &&
          (!studentFilter || s.student_name === studentFilter),
      ),
    [records, scenarioFilter, studentFilter],
  )

  // 已评分部分用于图表统计
  const scored = useMemo(() => filtered.filter((s) => s.has_score && s.total != null), [filtered])

  const scenarioOptions = useMemo(() => {
    const set = new Set<string>()
    records.forEach((s) => set.add(s.scenario_title))
    return Array.from(set).map((v) => ({ label: v, value: v }))
  }, [records])

  const studentOptions = useMemo(() => {
    const set = new Set<string>()
    records.forEach((s) => {
      if (s.student_name) set.add(s.student_name)
    })
    return Array.from(set).map((v) => ({ label: v, value: v }))
  }, [records])

  const finished = filtered.filter((s) => s.status === "finished").length
  const avgTotal = scored.length
    ? (scored.reduce((sum, s) => sum + (s.total as number), 0) / scored.length).toFixed(1)
    : "0"
  const avgTurns = filtered.length
    ? (filtered.reduce((sum, s) => sum + s.current_turn, 0) / filtered.length).toFixed(1)
    : "0"

  // 分数趋势：按时间升序（仅已评分）
  const lineData = useMemo(
    () =>
      [...scored]
        .sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at))
        .map((s) => ({ time: fmtTime(s.created_at), total: s.total as number })),
    [scored],
  )

  // 维度平均（仅已评分）
  const radarData = useMemo(() => {
    const avg = (key: keyof DrillRecord): number =>
      scored.length
        ? scored.reduce((sum, s) => sum + (s[key] as number), 0) / scored.length
        : 0
    return [
      { subject: "准确性", value: avg("accuracy") },
      { subject: "完整度", value: avg("completeness") },
      { subject: "礼仪", value: avg("etiquette") },
      { subject: "响应速度", value: avg("responsiveness") },
      { subject: "知识运用", value: avg("knowledge_use") },
    ]
  }, [scored])

  // 薄弱点分布
  const weakData = useMemo(() => {
    const counts: Record<string, number> = {}
    scored.forEach((s) => {
      ;(s.weak_points || []).forEach((wp) => {
        counts[wp] = (counts[wp] || 0) + 1
      })
    })
    return Object.entries(counts)
      .map(([name, count]) => ({ name: truncate(name), count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [scored])

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (records.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Empty description="暂无演练记录，去剧本库开始第一次演练吧" style={{ padding: 40 }}>
          <Button type="primary" onClick={() => nav("/scenarios")}>
            去剧本库
          </Button>
        </Empty>
      </div>
    )
  }

  const columns = [
    {
      title: "剧本",
      dataIndex: "scenario_title",
      render: (v: string) => v || "-",
    },
    ...(isTeacher
      ? [
          {
            title: "学员",
            dataIndex: "student_name",
            render: (v: string) => v || "-",
          },
        ]
      : []),
    {
      title: "状态",
      dataIndex: "status",
      render: (s: SessionStatus) => <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>,
    },
    {
      title: "总分",
      dataIndex: "total",
      width: 90,
      render: (v: number | null | undefined, r: DrillRecord) =>
        r.has_score && v != null ? (
          <span style={{ color: totalColor(v), fontWeight: 600 }}>{v.toFixed(1)}</span>
        ) : (
          <Typography.Text type="secondary">未评分</Typography.Text>
        ),
    },
    {
      title: "轮数",
      dataIndex: "current_turn",
      width: 90,
      render: (_: unknown, r: DrillRecord) => `${r.current_turn}/${r.max_turns}`,
    },
    {
      title: "演练时间",
      dataIndex: "created_at",
      render: (v: string) => new Date(v).toLocaleString("zh-CN"),
    },
    {
      title: "操作",
      width: 120,
      render: (_: unknown, r: DrillRecord) => (
        <Button
          size="small"
          type="link"
          icon={<EyeOutlined />}
          onClick={() => nav(`/drill/${r.id}`)}
        >
          查看
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        演练回顾
      </Typography.Title>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={isTeacher ? 8 : 12}>
          <Select
            style={{ width: "100%" }}
            allowClear
            placeholder="全部剧本"
            options={scenarioOptions}
            value={scenarioFilter}
            onChange={(v: string | undefined) => setScenarioFilter(v)}
          />
        </Col>
        {isTeacher && (
          <Col span={8}>
            <Select
              style={{ width: "100%" }}
              allowClear
              placeholder="全部学员"
              options={studentOptions}
              value={studentFilter}
              onChange={(v: string | undefined) => setStudentFilter(v)}
            />
          </Col>
        )}
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总演练次数" value={filtered.length} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已完成" value={finished} valueStyle={{ color: "#52c41a" }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="平均总分"
              value={avgTotal}
              valueStyle={{ color: "#1677ff" }}
              suffix={scored.length ? "" : "（未评分）"}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="平均轮数" value={avgTurns} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={24}>
          <Card size="small" title="分数趋势">
            {lineData.length === 0 ? (
              <Empty description="暂无评分数据（完成并评分后展示）" style={{ padding: 40 }} />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={lineData} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" fontSize={12} />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="total"
                    stroke="#1677ff"
                    strokeWidth={2}
                    name="总分"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="维度平均">
            {radarData.every((d) => d.value === 0) ? (
              <Empty description="暂无评分数据（完成并评分后展示）" style={{ padding: 40 }} />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <RadarChart data={radarData} outerRadius="70%">
                  <PolarGrid />
                  <PolarAngleAxis dataKey="subject" fontSize={12} />
                  <PolarRadiusAxis domain={[0, 100]} />
                  <Radar
                    name="平均"
                    dataKey="value"
                    stroke="#1677ff"
                    fill="#1677ff"
                    fillOpacity={0.3}
                  />
                  <Tooltip />
                </RadarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="薄弱点分布">
            {weakData.length === 0 ? (
              <Empty description="暂无薄弱点数据（完成并评分后展示）" style={{ padding: 40 }} />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={weakData} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" fontSize={12} />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" name="出现次数" fill="#fa8c16" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="演练记录">
        <Table
          rowKey="id"
          dataSource={filtered}
          pagination={{ pageSize: 10 }}
          columns={columns}
          expandable={{
            expandedRowRender: (r: DrillRecord) =>
              r.has_score ? (
                <div style={{ fontSize: 13 }}>
                  {r.summary && (
                    <p style={{ marginBottom: 8 }}>
                      <b>总结：</b>
                      {r.summary}
                    </p>
                  )}
                  {(r.weak_points?.length ?? 0) > 0 && (
                    <p style={{ marginBottom: 0 }}>
                      <b>薄弱点：</b>
                      {r.weak_points!.join("；")}
                    </p>
                  )}
                </div>
              ) : (
                <Typography.Text type="secondary">
                  该演练尚未评分，结束后点击“结束并评分”可查看 AI 反馈。
                </Typography.Text>
              ),
          }}
        />
      </Card>
    </div>
  )
}
