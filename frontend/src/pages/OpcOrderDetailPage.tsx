import { useCallback, useEffect, useState } from "react"
import {
  Alert, Badge, Button, Card, Col, Descriptions, Divider, Empty, Form, Input,
  InputNumber, Modal, Row, Select, Space, Steps, Table, Tag, Timeline,
  Typography, message, theme,
} from "antd"
import {
  ArrowLeftOutlined, CheckCircleOutlined, PlusOutlined, ReloadOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons"
import { useNavigate, useParams } from "react-router-dom"
import { opcApi, errMsg } from "../api/opc"
import type { OpcDesigner, OpcMeta, OpcOrderDetail, OpcState } from "../types/opc"

const { Title, Text, Paragraph } = Typography

/**
 * 订单工作台 —— 一张订单的全部台账。
 *
 * 四块：
 * 1. 履约进度（状态机 + 可执行的下一步）
 * 2. 需求单（六段式，可编辑）
 * 3. 交付证据链（红 → 改 → 绿）
 * 4. 结算门禁 + 返工回路 + 交付摘要
 */
export default function OpcOrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const nav = useNavigate()
  const { token } = theme.useToken()
  const [detail, setDetail] = useState<OpcOrderDetail | null>(null)
  const [meta, setMeta] = useState<OpcMeta | null>(null)
  const [designers, setDesigners] = useState<OpcDesigner[]>([])
  const [loading, setLoading] = useState(false)
  const [deliverOpen, setDeliverOpen] = useState(false)
  const [deliverForm] = Form.useForm()
  const [acceptOpen, setAcceptOpen] = useState(false)
  const [acceptForm] = Form.useForm()
  const [specOpen, setSpecOpen] = useState(false)
  const [specForm] = Form.useForm()
  const [specIssues, setSpecIssues] = useState<string[]>([])

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const d = await opcApi.getOrder(id)
      setDetail(d)
      setSpecIssues(d.order.spec_issues)
    } catch (e) {
      message.error(errMsg(e, "订单加载失败"))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    void opcApi.meta().then(setMeta).catch(() => undefined)
    void opcApi.listDesigners().then(setDesigners).catch(() => undefined)
  }, [])

  const doTransition = async (to: string) => {
    if (!detail) return
    try {
      await opcApi.transition(detail.order.id, to)
      message.success(`已流转到「${meta?.states.find((s) => s.value === to)?.label ?? to}」`)
      await load()
    } catch (e) {
      message.error(errMsg(e, "流转失败"))
    }
  }

  const doEvaluate = async () => {
    if (!detail) return
    try {
      const d = await opcApi.evaluate(detail.order.id)
      setDetail(d)
      if (d.order.state === "pending_review") message.success("复验通过，进入待验收")
      else message.warning("证据链还不完整，已退回返工")
    } catch (e) {
      message.error(errMsg(e, "复验失败"))
    }
  }

  const doAssign = async (designerId: string) => {
    if (!detail) return
    try {
      await opcApi.assign(detail.order.id, designerId)
      message.success("派单成功")
      await load()
    } catch (e) {
      message.error(errMsg(e, "派单失败"))
    }
  }

  const doClaim = async (designerId: string) => {
    if (!detail) return
    try {
      await opcApi.claim(detail.order.id, designerId)
      message.success("接单成功")
      await load()
    } catch (e) {
      message.error(errMsg(e, "接单失败"))
    }
  }

  const submitDelivery = async () => {
    if (!detail) return
    try {
      const v = await deliverForm.validateFields()
      await opcApi.addDelivery(detail.order.id, v)
      message.success("证据已记录")
      setDeliverOpen(false)
      deliverForm.resetFields()
      await load()
    } catch (e) {
      message.error(errMsg(e, "记录失败"))
    }
  }

  const submitAccept = async () => {
    if (!detail) return
    try {
      const v = await acceptForm.validateFields()
      await opcApi.accept(detail.order.id, v.actor, v.note ?? "")
      message.success("已具名验收")
      setAcceptOpen(false)
      acceptForm.resetFields()
      await load()
    } catch (e) {
      message.error(errMsg(e, "验收失败"))
    }
  }

  const saveSpec = async () => {
    if (!detail) return
    try {
      const v = await specForm.validateFields()
      await opcApi.editOrder(detail.order.id, { spec_snapshot: v.spec_snapshot })
      message.success("需求单已更新")
      setSpecOpen(false)
      await load()
    } catch (e) {
      message.error(errMsg(e, "保存失败"))
    }
  }

  const checkSpec = async () => {
    const text = specForm.getFieldValue("spec_snapshot") as string | undefined
    if (!text) return
    try {
      const res = await opcApi.validateSpec(text)
      setSpecIssues(res.issues)
      if (res.ok) message.success("需求单结构合格")
    } catch (e) {
      message.error(errMsg(e, "校验失败"))
    }
  }

  if (!detail) {
    return <Card loading={loading}><Empty description="订单不存在或加载中" /></Card>
  }

  const o = detail.order
  const mainline = meta?.mainline ?? []
  const currentStep = mainline.indexOf(o.state)
  const chain = detail.chain
  const loop = detail.repair_loop

  const nextActions: { label: string; onClick: () => void; type?: "primary" }[] = []
  if (o.state === "pending_assign") {
    nextActions.push({ label: "派单", onClick: () => doAssign(designers[0]?.id ?? ""), type: "primary" })
  }
  if (o.state === "assigned") {
    nextActions.push({ label: "标记接单", onClick: () => doClaim(designers[0]?.id ?? ""), type: "primary" })
  }
  if (["drafting", "finalizing"].includes(o.state)) {
    nextActions.push({ label: "复验", onClick: () => void doEvaluate(), type: "primary" })
  }
  if (o.state === "pending_review") {
    nextActions.push({ label: "具名验收", onClick: () => setAcceptOpen(true), type: "primary" })
  }
  if (o.state === "pending_settle") {
    nextActions.push({ label: "去结算", onClick: () => nav("/opc/settlements"), type: "primary" })
  }

  /** 可去状态由后端下发，前端不自己抄流转表。 */
  const nextStates = (meta?.transitions?.[o.state] ?? [])
    .map((s) => meta?.states.find((x) => x.value === s))
    .filter((x): x is { value: OpcState; label: string } => Boolean(x))

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav("/opc/orders")}>返回列表</Button>
        <Title level={4} style={{ margin: 0 }}>{o.order_sn}</Title>
        <Tag color="blue">{o.state_label}</Tag>
        {o.acceptance === "accepted"
          ? <Tag color="green" icon={<CheckCircleOutlined />}>已由 {detail.summary.four?.交接?.验收人 as string} 验收</Tag>
          : <Tag color="orange">待具名验收</Tag>}
        <Button icon={<ReloadOutlined />} onClick={() => void load()} />
      </Space>

      <Row gutter={[16, 16]}>
        <Col span={16}>
          <Card size="small" title="履约进度"
            extra={<Text type="secondary">{o.title || "（未填标题）"}</Text>}>
            <Steps
              size="small"
              current={currentStep < 0 ? 0 : currentStep}
              items={mainline.map((s) => ({
                title: meta?.states.find((x) => x.value === s)?.label ?? s,
                status: o.state === s ? "process" : undefined,
              }))}
            />
            <Space style={{ marginTop: 16 }} wrap>
              {nextActions.map((a) => (
                <Button key={a.label} type={a.type} onClick={a.onClick}>{a.label}</Button>
              ))}
              <Button icon={<PlusOutlined />} onClick={() => setDeliverOpen(true)}>
                记录交付证据
              </Button>
              <Button onClick={() => {
                specForm.setFieldValue("spec_snapshot", detail.spec_snapshot)
                setSpecIssues(o.spec_issues)
                setSpecOpen(true)
              }}>编辑需求单</Button>
              {o.state === "pending_assign" && (
                <Select
                  style={{ width: 200 }} placeholder="选设计师派单"
                  options={designers.map((d) => ({
                    value: d.id, label: `${d.name}（${d.design_tags || "未标注"}）`,
                  }))}
                  onChange={(v: string) => void doAssign(v)}
                />
              )}
              {nextStates.length > 0 && (
                <Select
                  style={{ width: 160 }} placeholder="人工流转到…"
                  value={undefined}
                  options={nextStates.map((s) => ({
                    value: s.value,
                    label: `→ ${s.label}`,
                  }))}
                  onChange={(v: string) => void doTransition(v)}
                />
              )}
            </Space>
          </Card>

          <Card size="small" title="交付证据链" style={{ marginTop: 16 }}
            extra={
              <Space>
                <Tag color={chain.evidence_complete ? "green" : "orange"}>
                  {chain.evidence_complete ? "链完整" : "链不完整"}
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  红 {chain.counts.red} · 改 {chain.counts.diff} · 绿 {chain.counts.green}
                </Text>
              </Space>
            }>
            {detail.deliveries.length === 0 ? (
              <Empty description="还没有交付证据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={detail.deliveries}
                columns={[
                  { title: "阶段", dataIndex: "phase_label", width: 100,
                    render: (v: string, r: { phase: string }) => (
                      <Badge status={r.phase === "green" ? "success"
                        : r.phase === "red" ? "error" : "processing"} text={v} />
                    ) },
                  { title: "验收命令", dataIndex: "command_text",
                    render: (v: string) => (
                      <Text code style={{ fontSize: 12 }}>{v || "—"}</Text>
                    ) },
                  { title: "返回码", dataIndex: "return_code", width: 80,
                    align: "right" as const,
                    render: (v: number) => (
                      <Tag color={v === 0 ? "green" : "red"}>{v}</Tag>
                    ) },
                  { title: "输出", dataIndex: "output", ellipsis: true },
                ]}
              />
            )}
            {chain.issues.length > 0 && (
              <Alert style={{ marginTop: 12 }} type="warning" showIcon
                message="证据链还差这些" description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {chain.issues.map((i) => <li key={i}>{i}</li>)}
                  </ul>
                } />
            )}
          </Card>

          <Card size="small" title="交付四要素（可交接）" style={{ marginTop: 16 }}
            extra={
              <Button size="small" icon={<ThunderboltOutlined />} onClick={() => {
                void navigator.clipboard?.writeText(detail.summary.markdown ?? "")
                message.success("已复制 Markdown")
              }}>复制</Button>
            }>
            <Row gutter={[16, 16]}>
              {Object.entries(detail.summary.four ?? {}).map(([k, v]) => (
                <Col span={6} key={k}>
                  <Text strong>{k}</Text>
                  <div style={{ marginTop: 4 }}>
                    {Object.entries(v as Record<string, unknown>).map(([kk, vv]) => (
                      <div key={kk} style={{ fontSize: 12, marginBottom: 3 }}>
                        <Text type="secondary">{kk}：</Text>
                        <span style={{ wordBreak: "break-all" }}>
                          {Array.isArray(vv)
                            ? (vv as unknown[]).map((x) =>
                                typeof x === "object" && x
                                  ? `${(x as Record<string, unknown>).code}（${(x as Record<string, unknown>).acceptance ?? "—"}）`
                                  : String(x)).join("、")
                            : String(vv ?? "—")}
                        </span>
                      </div>
                    ))}
                  </div>
                </Col>
              ))}
            </Row>
            {detail.money.length > 0 && (
              <>
                <Divider style={{ margin: "12px 0" }} />
                <Table
                  rowKey="scope"
                  size="small"
                  pagination={false}
                  dataSource={detail.money}
                  columns={[
                    { title: "口径", dataIndex: "label", width: 140 },
                    { title: "金额", dataIndex: "amount", align: "right" as const,
                      render: (v: string) => `¥${v}` },
                    { title: "占比", dataIndex: "percent", align: "right" as const,
                      render: (v: string) => `${v}%` },
                  ]}
                />
              </>
            )}
          </Card>
        </Col>

        <Col span={8}>
          <Card size="small" title="结算门禁"
            extra={
              <Tag color={detail.gate.allowed ? "green" : "red"}>
                {detail.gate.allowed ? "可结算" : "不可结算"}
              </Tag>
            }>
            {detail.gate.allowed ? (
              <Alert type="success" showIcon message="全部条件满足，可以进入结算" />
            ) : (
              <Alert type="error" showIcon message="还差这些才能结算" description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {detail.gate.blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              } />
            )}
            <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
              <Descriptions.Item label="证据链">
                {detail.gate.evidence_complete
                  ? <Tag color="green">完整</Tag> : <Tag color="orange">不完整</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="具名验收">
                {detail.gate.accepted
                  ? <Tag color="green">已验收</Tag> : <Tag color="orange">未验收</Tag>}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card size="small" title="返工回路" style={{ marginTop: 16 }}
            extra={
              <Tag color={
                loop.status.startsWith("stopped") ? "red"
                  : loop.status === "converged" ? "green" : "blue"
              }>
                {loop.status}
              </Tag>
            }>
            <Paragraph style={{ fontSize: 13, marginBottom: 8 }}>{loop.reason}</Paragraph>
            {loop.history.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>还没返工过</Text>
            ) : (
              <Timeline
                items={loop.history.map((h) => ({
                  color: h.outcome === "converged" ? "green"
                    : h.outcome === "failed_again" ? "red" : "blue",
                  children: (
                    <div style={{ fontSize: 12 }}>
                      <strong>第 {h.round} 轮</strong> · {h.actor}
                      {h.issues && h.issues.length > 0 && (
                        <div style={{ color: token.colorTextSecondary }}>
                          {h.issues.join("；")}
                        </div>
                      )}
                    </div>
                  ),
                }))}
              />
            )}
            {loop.handoff && (
              <Alert type="warning" showIcon style={{ marginTop: 8 }}
                message="已停止自动修复"
                description={loop.handoff.next_action} />
            )}
          </Card>

          <Card size="small" title="履约时间轴" style={{ marginTop: 16 }}>
            <Timeline
              items={[...detail.events].reverse().map((e) => ({
                color: e.kind === "acceptance" ? "green" : e.kind === "evaluate" ? "blue" : "gray",
                children: (
                  <div style={{ fontSize: 12 }}>
                    <strong>{e.kind}</strong>
                    {e.from_state && e.to_state && <> · {e.from_state} → {e.to_state}</>}
                    <div style={{ color: token.colorTextSecondary }}>{e.detail}</div>
                    <div style={{ color: token.colorTextTertiary }}>
                      {e.actor} · {e.created_at ? new Date(e.created_at).toLocaleString("zh-CN") : ""}
                    </div>
                  </div>
                ),
              }))}
            />
          </Card>
        </Col>
      </Row>

      {/* 记录交付证据 */}
      <Modal title="记录交付证据" open={deliverOpen}
        onCancel={() => setDeliverOpen(false)} onOk={() => void submitDelivery()}
        okText="记录">
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="证据链规则"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              <li><strong>红灯</strong>：初稿不合格（返回码非 0）</li>
              <li><strong>返工</strong>：改动记录（返回码 0）</li>
              <li><strong>绿灯</strong>：终稿合格（返回码 0，<strong>必须与红灯同一条命令</strong>）</li>
            </ul>
          } />
        <Form form={deliverForm} layout="vertical"
          initialValues={{ phase: "green", return_code: 0 }}>
          <Form.Item name="phase" label="阶段" rules={[{ required: true }]}>
            <Select options={[
              { value: "red", label: "红灯 · 初稿不合格" },
              { value: "diff", label: "返工 · 改动记录" },
              { value: "green", label: "绿灯 · 终稿合格" },
              { value: "observation", label: "观察记录" },
            ]} />
          </Form.Item>
          <Form.Item name="command_text" label="验收命令"
            rules={[{ required: true, message: "验收命令必填 —— 绿灯必须与红灯同一条命令" }]}>
            <Input placeholder="如 check_images.py --dir ./out" />
          </Form.Item>
          <Form.Item name="output" label="输出">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="return_code" label="返回码">
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 具名验收 */}
      <Modal title="具名验收" open={acceptOpen}
        onCancel={() => setAcceptOpen(false)} onOk={() => void submitAccept()}
        okText="验收">
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="两条硬规则"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              <li>验收人必须是<strong>具名的人</strong>，机器署名（agent: 前缀）不被接受</li>
              <li>设计师<strong>不能验收自己的稿</strong></li>
            </ul>
          } />
        <Form form={acceptForm} layout="vertical">
          <Form.Item name="actor" label="验收人" rules={[{ required: true, message: "验收人必填" }]}>
            <Input placeholder="如 张老板" />
          </Form.Item>
          <Form.Item name="note" label="验收备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑需求单 */}
      <Modal title="编辑需求单（六段式）" open={specOpen} width={720}
        onCancel={() => setSpecOpen(false)}
        onOk={() => void saveSpec()}
        okText="保存">
        <div style={{ marginBottom: 8 }}>
          <Button size="small" onClick={() => void checkSpec()}>校验需求单</Button>
        </div>
        <Form form={specForm} layout="vertical">
          <Form.Item name="spec_snapshot" label="需求单原文">
            <Input.TextArea rows={18}
              style={{ fontFamily: "Consolas, monospace", fontSize: 13 }} />
          </Form.Item>
        </Form>
        {specIssues.length > 0 ? (
          <Alert type="warning" showIcon message="还缺：" description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {specIssues.map((i) => <li key={i}>{i}</li>)}
            </ul>
          } />
        ) : (
          <Alert type="success" showIcon message="结构合格" />
        )}
      </Modal>
    </div>
  )
}
