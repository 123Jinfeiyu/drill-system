import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Collapse, Descriptions, Divider, Drawer, Empty, Form, Input,
  InputNumber, Modal, Row, Select, Space, Statistic, Steps, Table, Tag, Timeline, Tooltip,
  Typography, message,
} from "antd"
import {
  AuditOutlined, CheckCircleOutlined, CopyOutlined, FileTextOutlined, FolderAddOutlined, PlusOutlined,
  SafetyCertificateOutlined, SyncOutlined, ThunderboltOutlined,
} from "@ant-design/icons"
import { fdeApi } from "../api/fde"
import { errIssues, errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import type {
  FdeAcceptance, FdeEvidenceCreate, FdeProject, FdeState, FdeTask, FdeTaskDetail,
} from "../types/api"

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

const phaseColor = { red: "red", diff: "gold", green: "green", observation: "blue" } as const
const phaseText = { red: "红灯", diff: "改动", green: "绿灯", observation: "观察" }

const stateColor: Record<FdeState, string> = {
  queued: "default", spec_ready: "cyan", executing: "blue", evaluating: "purple",
  review: "orange", accepted: "green", rework: "red", canceled: "default",
}
const acceptanceMeta: Record<FdeAcceptance, { color: string; text: string }> = {
  pending_human_review: { color: "orange", text: "待人审" },
  accepted: { color: "green", text: "已具名接受" },
  rejected: { color: "red", text: "已驳回" },
}
const kindColor: Record<string, string> = {
  spec: "cyan", evidence: "blue", transition: "geekblue", evaluate: "purple",
  acceptance: "green", rejected: "red",
}
const kindText: Record<string, string> = {
  spec: "需求冻结", evidence: "证据追加", transition: "状态流转",
  evaluate: "自动复验", acceptance: "人工接受", rejected: "被门禁拒绝",
}
// 主线状态（用于 Steps 展示）；rework / canceled 是支线，单独用 Tag 标出
const MAINLINE = ["queued", "spec_ready", "executing", "evaluating", "review", "accepted"] as const
const mainLabel: Record<string, string> = {
  queued: "已登记", spec_ready: "需求已冻结", executing: "受控执行",
  evaluating: "自动复验", review: "待人审", accepted: "已接受",
}

// L10 修复回路的状态与轮次结局的呈现口径
const loopStatusMeta: Record<string, { color: string; text: string }> = {
  ready: { color: "default", text: "未返工" },
  continue: { color: "blue", text: "在界内" },
  verifying: { color: "cyan", text: "开修待复验" },
  converged: { color: "green", text: "已收敛" },
  closed: { color: "default", text: "已关闭" },
  stopped_max_rounds: { color: "red", text: "已达轮数上限" },
  stopped_no_progress: { color: "red", text: "连续两轮无进展" },
}
const loopOutcomeText: Record<string, string> = {
  in_rework: "返工待处理", verifying: "开修待复验", converged: "复验通过",
  accepted: "已接受", canceled: "已取消", failed_again: "复验又未过",
}

const fmt = (v: string | null) => (v ? new Date(v).toLocaleString("zh-CN") : "—")

export default function FdeWorkbenchPage() {
  const { user } = useAuth()
  const me = user?.display_name || user?.username || ""

  const [projects, setProjects] = useState<FdeProject[]>([])
  const [tasks, setTasks] = useState<FdeTask[]>([])
  const [detail, setDetail] = useState<FdeTaskDetail | null>(null)
  const [open, setOpen] = useState({ project: false, task: false, evidence: false })
  const [specIssues, setSpecIssues] = useState<string[]>([])
  const [checking, setChecking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [projectForm] = Form.useForm()
  const [taskForm] = Form.useForm()
  const [evidenceForm] = Form.useForm()

  const load = useCallback(async () => {
    try {
      const [p, t] = await Promise.all([fdeApi.listProjects(), fdeApi.listTasks()])
      setProjects(p)
      setTasks(t)
    } catch (e) {
      message.error(errMsg(e, "加载失败"))
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const showDetail = useCallback(async (id: string) => {
    try { setDetail(await fdeApi.getTask(id)) } catch (e) { message.error(errMsg(e, "加载失败")) }
  }, [])

  const refresh = async (id: string) => { await showDetail(id); await load() }

  const createProject = async () => {
    const values = await projectForm.validateFields()
    try {
      await fdeApi.createProject(values)
      message.success("项目已登记")
      setOpen({ ...open, project: false })
      projectForm.resetFields()
      await load()
    } catch (e) { message.error(errMsg(e, "登记失败")) }
  }

  const checkSpec = async () => {
    const text = taskForm.getFieldValue("spec_snapshot") as string | undefined
    if (!text?.trim()) { message.warning("请先填写需求合同"); return }
    setChecking(true)
    try {
      const res = await fdeApi.validateSpec(text)
      setSpecIssues(res.issues)
      if (res.ok) message.success("合同结构合格：六节齐全")
      else message.warning(`合同不完整，登记会被拒绝（缺 ${res.issues.length} 项）`)
    } catch (e) { message.error(errMsg(e, "校验失败")) } finally { setChecking(false) }
  }

  const fillTemplate = async () => {
    try {
      const res = await fdeApi.validateSpec("")
      taskForm.setFieldValue("spec_snapshot", res.template)
      setSpecIssues([])
    } catch (e) { message.error(errMsg(e, "获取模板失败")) }
  }

  const createTask = async () => {
    const values = await taskForm.validateFields()
    try {
      await fdeApi.createTask({ ...values, depends_on: values.depends_on ?? [] })
      message.success("任务已登记，需求快照已冻结")
      setOpen({ ...open, task: false })
      taskForm.resetFields()
      setSpecIssues([])
      await load()
    } catch (e) {
      const issues = errIssues(e)
      setSpecIssues(issues)
      message.error(issues.length ? `登记被拒：${errMsg(e)}` : errMsg(e, "登记失败"))
    }
  }

  const addEvidence = async () => {
    if (!detail) return
    const values = await evidenceForm.validateFields()
    setBusy(true)
    try {
      await fdeApi.addEvidence(detail.id, {
        ...values,
        observed_at: new Date(values.observed_at).toISOString(),
      } as FdeEvidenceCreate)
      message.success("原始运行记录已追加")
      setOpen({ ...open, evidence: false })
      evidenceForm.resetFields()
      await refresh(detail.id)
    } catch (e) { message.error(errMsg(e, "追加失败")) } finally { setBusy(false) }
  }

  const act = async (fn: () => Promise<FdeTaskDetail>, okText: string) => {
    if (!detail) return
    setBusy(true)
    try {
      const next = await fn()
      setDetail(next)
      message.success(`${okText}（当前状态：${next.state_label}）`)
      await load()
    } catch (e) { message.error(errMsg(e, "操作被拒绝")) } finally { setBusy(false) }
  }

  const waiting = tasks.filter((t) => t.state === "review" && t.acceptance !== "accepted")
  const accepted = tasks.filter((t) => t.acceptance === "accepted")
  const mainIndex = detail ? (MAINLINE as readonly string[]).indexOf(detail.state) : 0

  return (
    <div style={{ maxWidth: 1320, margin: "0 auto" }}>
      <Space direction="vertical" size={4} style={{ marginBottom: 20 }}>
        <Typography.Title level={2} style={{ margin: 0 }}>CodexFDE 工作台</Typography.Title>
        <Typography.Text type="secondary">
          需求先变成可验收的合同，执行留下红-改-绿原始证据，交付前必须由构建者以外的人具名接受。
        </Typography.Text>
      </Space>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        message="工作台只判断证据，不执行命令"
        description="它接收「已经发生过的运行输出」并按合同判定；真正的执行留在操作者与其智能体一侧。证据齐全只是程序的结论，能否交付由具名的人决定。"
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} md={6}><Card><Statistic title="已登记项目" value={projects.length} prefix={<FolderAddOutlined />} /></Card></Col>
        <Col xs={24} md={6}><Card><Statistic title="交付任务" value={tasks.length} prefix={<FileTextOutlined />} /></Card></Col>
        <Col xs={24} md={6}><Card><Statistic title="待人审" value={waiting.length} prefix={<AuditOutlined />} valueStyle={{ color: "#fa8c16" }} /></Card></Col>
        <Col xs={24} md={6}><Card><Statistic title="已具名接受" value={accepted.length} prefix={<CheckCircleOutlined />} valueStyle={{ color: "#52c41a" }} /></Card></Col>
      </Row>

      <Card title="交付状态机" style={{ marginBottom: 20 }}
        extra={<Typography.Text type="secondary">跳阶段会被服务端拒绝</Typography.Text>}>
        <Steps
          size="small"
          labelPlacement="vertical"
          current={mainIndex < 0 ? 0 : mainIndex}
          status={detail?.state === "rework" ? "error" : "process"}
          items={MAINLINE.map((s) => ({ title: mainLabel[s] }))}
        />
        {(detail?.state === "rework" || detail?.state === "canceled") && (
          <Tag color={stateColor[detail.state]} style={{ marginTop: 12 }}>
            当前处于支线状态：{detail.state_label}
          </Tag>
        )}
      </Card>

      <Card
        title="交付任务"
        extra={<Space>
          <Button onClick={() => setOpen({ ...open, project: true })}>登记项目</Button>
          <Button type="primary" icon={<PlusOutlined />} disabled={!projects.length}
            onClick={() => { setSpecIssues([]); setOpen({ ...open, task: true }) }}>新建任务</Button>
        </Space>}
      >
        <Table
          rowKey="id"
          dataSource={tasks}
          pagination={{ pageSize: 8 }}
          onRow={(r) => ({ onClick: () => void showDetail(r.id), style: { cursor: "pointer" } })}
          columns={[
            {
              title: "任务", dataIndex: "title",
              render: (_, r) => <>
                <b>{r.title}</b><br />
                <Typography.Text type="secondary">{r.code}</Typography.Text>
              </>,
            },
            { title: "项目", dataIndex: "project_name", responsive: ["md"] },
            {
              title: "状态", dataIndex: "state",
              render: (v: FdeState, r) => <Tag color={stateColor[v]}>{r.state_label}</Tag>,
            },
            {
              title: "接受状态", dataIndex: "acceptance",
              render: (v: FdeAcceptance, r) => (
                <Tooltip title={v === "accepted" ? `签收人：${r.accepted_by} · ${fmt(r.accepted_at)}` : "程序不会自动置位"}>
                  <Tag color={acceptanceMeta[v].color}>{acceptanceMeta[v].text}</Tag>
                </Tooltip>
              ),
            },
            {
              title: "合同", dataIndex: "spec_issues",
              render: (v: string[]) => v.length === 0
                ? <Tag color="green">六节齐全</Tag>
                : <Tag color="red">缺 {v.length} 项</Tag>,
            },
            {
              title: "依赖", dataIndex: "depends_on",
              render: (v: string[]) => v.length ? v.map((c) => <Tag key={c}>{c}</Tag>) : <Typography.Text type="secondary">—</Typography.Text>,
            },
          ]}
        />
      </Card>

      <Drawer
        title={detail ? `${detail.code} · ${detail.title}` : "交付任务详情"}
        width={760}
        open={!!detail}
        onClose={() => setDetail(null)}
        extra={detail && (
          <Space>
            <Button icon={<SyncOutlined />} disabled={busy} onClick={() => act(() => fdeApi.evaluate(detail.id), "自动复验完成")}>自动复验</Button>
            <Button onClick={() => setOpen({ ...open, evidence: true })}>追加证据</Button>
          </Space>
        )}
      >
        {detail && <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Descriptions column={2} size="small" items={[
            { key: "p", label: "项目", children: detail.project_name },
            { key: "c", label: "构建者", children: detail.created_by },
            { key: "r", label: "原始请求", span: 2, children: detail.request || "—" },
            { key: "h", label: "需求快照 SHA-256", span: 2, children: <Typography.Text code>{detail.spec_hash}</Typography.Text> },
            { key: "a", label: "签收人", children: detail.accepted_by ?? "尚未签收" },
            { key: "t", label: "签收时间", children: fmt(detail.accepted_at) },
          ]} />

          <Alert
            type={detail.gate.allowed ? "success" : "warning"}
            showIcon
            message={detail.gate.allowed ? "资格门禁：放行" : "资格门禁：拒绝"}
            description={<>
              <div>{detail.gate.reason}</div>
              {detail.gate.blockers.length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>
                  {detail.gate.blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              )}
            </>}
          />

          <Row gutter={12}>
            <Col span={12}>
              <Card size="small" title="程序的判断" style={{ height: "100%" }}>
                <Tag color={detail.evidence_complete ? "green" : "red"}>
                  {detail.evidence_complete ? "证据链完整" : "证据链不完整"}
                </Tag>
                <div style={{ marginTop: 8 }}>
                  <Typography.Text type="secondary">
                    红灯 {detail.chain.counts.red ?? 0} · 改动 {detail.chain.counts.diff ?? 0} ·
                    绿灯 {detail.chain.counts.green ?? 0} · 观察 {detail.chain.counts.observation ?? 0}
                  </Typography.Text>
                </div>
                {detail.chain.issues.map((i) => <div key={i}><Typography.Text type="danger">{i}</Typography.Text></div>)}
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title="人的判断" style={{ height: "100%" }}>
                <Tag color={acceptanceMeta[detail.acceptance].color}>{acceptanceMeta[detail.acceptance].text}</Tag>
                <div style={{ marginTop: 8 }}>
                  <Typography.Text type="secondary">
                    {detail.acceptance === "accepted"
                      ? `${detail.accepted_by} 于 ${fmt(detail.accepted_at)} 签收`
                      : "必须由构建者以外的人具名完成，程序不代签"}
                  </Typography.Text>
                </div>
                {detail.state === "review" && detail.acceptance !== "accepted" && (
                  <Button
                    type="primary" size="small" style={{ marginTop: 10 }}
                    icon={<SafetyCertificateOutlined />} disabled={busy}
                    onClick={() => act(() => fdeApi.accept(detail.id, "由复核者在工作台具名接受"), "已具名接受")}
                  >
                    以「{me}」具名接受
                  </Button>
                )}
              </Card>
            </Col>
          </Row>

          <Card size="small" title="状态机操作">
            <Space wrap>
              <Tag color={stateColor[detail.state]}>{detail.state_label}</Tag>
              <Typography.Text type="secondary">可流转到：</Typography.Text>
              {detail.next_states.length === 0
                ? <Typography.Text type="secondary">终态，无后续</Typography.Text>
                : detail.next_states.map((s) => (
                  <Button key={s} size="small" disabled={busy}
                    icon={<ThunderboltOutlined />}
                    onClick={() => act(() => fdeApi.transition(detail.id, s, `由 ${me} 流转`), `已流转到 ${s}`)}>
                    {s}
                  </Button>
                ))}
            </Space>
          </Card>

          <Card
            size="small"
            title={`修复回路（L10 有界，最多 ${detail.repair_loop.max_rounds} 轮；只判定不拦流程）`}
            extra={
              <Tag color={loopStatusMeta[detail.repair_loop.status]?.color ?? "default"}>
                {loopStatusMeta[detail.repair_loop.status]?.text ?? detail.repair_loop.status}
              </Tag>
            }
          >
            <Typography.Text type="secondary">{detail.repair_loop.reason}</Typography.Text>
            {detail.repair_loop.handoff && (
              <Alert
                type="warning" showIcon style={{ marginTop: 8 }}
                message="修复回路已到边界，继续照原样修没有意义"
                description={
                  <>
                    {detail.repair_loop.handoff.last_issues?.length ? (
                      <ul style={{ margin: "0 0 6px", paddingLeft: 18 }}>
                        {detail.repair_loop.handoff.last_issues.map((i) => <li key={i}>{i}</li>)}
                      </ul>
                    ) : null}
                    <div>{detail.repair_loop.handoff.next_action}</div>
                  </>
                }
              />
            )}
            {detail.repair_loop.history.length === 0 ? (
              <Typography.Text type="secondary" style={{ display: "block", marginTop: 8 }}>
                还没有返工记录；每次「退回返工」会在这里开新一轮。
              </Typography.Text>
            ) : (
              <Timeline
                style={{ marginTop: 10 }}
                items={detail.repair_loop.history.map((r) => ({
                  color: r.outcome === "converged" || r.outcome === "accepted" ? "green" : "red",
                  children: (
                    <div>
                      <Space size={6} wrap>
                        <Typography.Text strong>第 {r.round} 轮</Typography.Text>
                        <Tag style={{ margin: 0 }}>{loopOutcomeText[r.outcome] ?? r.outcome}</Tag>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {new Date(r.entered_at).toLocaleString("zh-CN")} · {r.actor}
                        </Typography.Text>
                      </Space>
                      <div style={{ fontSize: 12 }}>{r.reason}</div>
                    </div>
                  ),
                }))}
              />
            )}
          </Card>

          <Card
            size="small"
            title="交付摘要（结果 · 证据 · 边界 · 交接，直接取自台账与冻结合同）"
            extra={
              <Button
                size="small" icon={<CopyOutlined />}
                onClick={async () => {
                  const ok = await copyText(detail.delivery_summary.markdown)
                  if (ok) message.success("交付摘要已复制，可直接贴进交接单")
                  else message.warning("复制失败，请手动选中文本")
                }}
              >
                复制 Markdown
              </Button>
            }
          >
            <Descriptions
              bordered column={1} size="small"
              items={Object.entries(detail.delivery_summary.four).map(([key, values]) => ({
                key,
                label: <Typography.Text strong>{key}</Typography.Text>,
                children: (
                  <div>
                    {Object.entries(values).map(([name, value]) => (
                      <div key={name}>
                        <Typography.Text type="secondary">{name}：</Typography.Text>
                        <Typography.Text>
                          {Array.isArray(value)
                            ? ((value as { code: string }[]).map((d) => d.code).join("、") || "无")
                            : (String(value) || "—")}
                        </Typography.Text>
                      </div>
                    ))}
                  </div>
                ),
              }))}
            />
          </Card>

          <Card size="small" title={`需求合同（${detail.spec_issues.length === 0 ? "六节齐全" : `缺 ${detail.spec_issues.length} 项`}）`}>
            {detail.spec_issues.length > 0 && (
              <Alert type="error" showIcon style={{ marginBottom: 10 }}
                message="合同不完整" description={<ul style={{ margin: 0, paddingLeft: 18 }}>{detail.spec_issues.map((i) => <li key={i}>{i}</li>)}</ul>} />
            )}
            <Collapse
              size="small"
              items={detail.spec_snapshot.split(/\n(?=#{1,6}\s)/).map((block, idx) => {
                const firstLine = block.split("\n")[0].replace(/^#+\s*/, "").replace(/[：:]\s*$/, "")
                const body = block.split("\n").slice(1).join("\n").trim()
                return {
                  key: idx,
                  label: firstLine || `片段 ${idx + 1}`,
                  children: <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>{body || "（空）"}</Typography.Paragraph>,
                }
              })}
            />
          </Card>

          <Card size="small" title={`运行证据（${detail.evidences.length} 条，只追加不覆盖）`}>
            {detail.evidences.length === 0
              ? <Empty description="尚未追加运行证据" />
              : <Timeline items={detail.evidences.map((e) => ({
                color: phaseColor[e.phase],
                children: (
                  <div>
                    <Tag color={phaseColor[e.phase]}>{phaseText[e.phase]}</Tag>
                    <Typography.Text type="secondary">{new Date(e.observed_at).toLocaleString("zh-CN")}</Typography.Text>
                    <br />
                    <Typography.Text code>{e.command_text}</Typography.Text>
                    <br />
                    <Typography.Text>
                      返回码：
                      <Typography.Text type={e.return_code === 0 ? "success" : "danger"} strong>{e.return_code}</Typography.Text>
                      {" · 输出 SHA-256："}<Typography.Text code>{e.output_hash.slice(0, 12)}…</Typography.Text>
                    </Typography.Text>
                    <Collapse size="small" ghost items={[{
                      key: "o", label: "查看原始输出",
                      children: <Typography.Paragraph style={{ whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto", background: "#fafafa", padding: 8, borderRadius: 6, fontSize: 12 }}>{e.output}</Typography.Paragraph>,
                    }]} />
                  </div>
                ),
              }))} />}
          </Card>

          <Card size="small" title={`任务事件（${detail.events.length} 条，含被门禁拒绝的尝试）`}>
            {detail.events.length === 0
              ? <Empty description="暂无事件" />
              : <Timeline items={[...detail.events].reverse().map((ev) => ({
                color: kindColor[ev.kind] ?? "gray",
                children: (
                  <div>
                    <Tag color={kindColor[ev.kind] ?? "default"}>{kindText[ev.kind] ?? ev.kind}</Tag>
                    <Typography.Text type="secondary">{new Date(ev.created_at).toLocaleString("zh-CN")} · {ev.actor}</Typography.Text>
                    {ev.from_state && <Typography.Text type="secondary">{` ${ev.from_state} → ${ev.to_state}`}</Typography.Text>}
                    <div><Typography.Text>{ev.detail}</Typography.Text></div>
                  </div>
                ),
              }))} />}
          </Card>

          <Card size="small" title="前置任务（依赖未接受则本任务无资格交付）">
            {detail.blockers_detail.length === 0
              ? <Typography.Text type="secondary">无前置依赖</Typography.Text>
              : <Table size="small" rowKey="code" pagination={false} dataSource={detail.blockers_detail}
                columns={[
                  { title: "前置任务", dataIndex: "code" },
                  { title: "标题", dataIndex: "title", render: (v: string | null) => v ?? "（不存在）" },
                  { title: "状态", dataIndex: "state", render: (v: FdeState | null) => v ? <Tag color={stateColor[v]}>{v}</Tag> : <Tag color="red">缺失</Tag> },
                  {
                    title: "是否已被具名接受", dataIndex: "acceptance",
                    render: (v: FdeAcceptance | null) => v ? <Tag color={acceptanceMeta[v].color}>{acceptanceMeta[v].text}</Tag> : <Tag color="red">—</Tag>,
                  },
                ]} />}
          </Card>
        </Space>}
      </Drawer>

      <Modal title="登记项目" open={open.project} onCancel={() => setOpen({ ...open, project: false })}
        onOk={() => void createProject()} okText="登记">
        <Form form={projectForm} layout="vertical" initialValues={{ path: "E:\\drill-system" }}>
          <Form.Item name="code" label="项目编号" rules={[{ required: true }]}><Input placeholder="例如 CUSTOMER-DRILL" /></Form.Item>
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="purpose" label="用途"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="path" label="代码路径"><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal title="新建交付任务（登记即冻结需求）" open={open.task} width={720}
        onCancel={() => setOpen({ ...open, task: false })} onOk={() => void createTask()} okText="登记并冻结">
        <Form form={taskForm} layout="vertical">
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true }]}>
            <Select placeholder="选择已登记项目" options={projects.map((p) => ({ value: p.id, label: `${p.name} · ${p.code}` }))} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="code" label="任务编号" rules={[{ required: true }]}><Input placeholder="例如 L05-A" /></Form.Item></Col>
            <Col span={12}><Form.Item name="title" label="任务标题" rules={[{ required: true }]}><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="request" label="原始请求"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="depends_on" label="前置任务编号（未具名接受则本任务无资格交付）">
            <Select mode="tags" placeholder="例如 L05-A，可留空" options={tasks.map((t) => ({ value: t.code, label: `${t.code} · ${t.title}` }))} />
          </Form.Item>
          <Form.Item name="spec_snapshot" label="需求合同（六段式：目标 / 范围 / 非目标 / 约束 / 验收标准 / 完成定义）"
            rules={[{ required: true, message: "需求合同不能为空" }]}>
            <Input.TextArea rows={10} placeholder="缺任何一节都会被拒绝登记" />
          </Form.Item>
          {specIssues.length > 0 && (
            <Alert type="error" showIcon style={{ marginBottom: 12 }} message="合同不完整，登记会被拒绝"
              description={<ul style={{ margin: 0, paddingLeft: 18 }}>{specIssues.map((i) => <li key={i}>{i}</li>)}</ul>} />
          )}
          <Space>
            <Button size="small" loading={checking} onClick={() => void checkSpec()}>校验合同</Button>
            <Button size="small" onClick={() => void fillTemplate()}>插入模板</Button>
            <Typography.Text type="secondary">模板自带占位说明，能通过结构校验——结构合格不代表需求想清楚了。</Typography.Text>
          </Space>
        </Form>
      </Modal>

      <Modal title="追加原始运行证据" open={open.evidence}
        onCancel={() => setOpen({ ...open, evidence: false })} onOk={() => void addEvidence()} okText="追加（不覆盖既有记录）">
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="这里登记的是已经发生过的运行"
          description="红灯必须是真实失败（返回码非 0），绿灯必须用同一条命令并通过。工作台不会替你执行命令。" />
        <Form form={evidenceForm} layout="vertical"
          initialValues={{ phase: "observation", return_code: 0, observed_at: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) }}>
          <Form.Item name="phase" label="阶段" rules={[{ required: true }]}>
            <Select options={[
              { value: "red", label: "red · 红灯（先失败）" },
              { value: "diff", label: "diff · 改动" },
              { value: "green", label: "green · 绿灯（同命令通过）" },
              { value: "observation", label: "observation · 观察" },
            ]} />
          </Form.Item>
          <Form.Item name="command_text" label="实际命令" rules={[{ required: true }]}><Input placeholder="必须与绿灯完全一致" /></Form.Item>
          <Form.Item name="output" label="完整原始输出" rules={[{ required: true }]}><Input.TextArea rows={5} /></Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="return_code" label="返回码" rules={[{ required: true }]}><InputNumber style={{ width: "100%" }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="observed_at" label="观察时间" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Divider />
      <Typography.Text type="secondary">
        台账规则来自 backend/app/services/fde_ledger.py，只有一份实现。
        页面与命令行判断永远一致——因为它们读的是同一套规则。
      </Typography.Text>
    </div>
  )
}
