import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Alert, Button, Card, Col, DatePicker, Form, Input, InputNumber, Modal, Row, Select,
  Space, Table, Tag, Typography, message,
} from "antd"
import { DeleteOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons"
import { useNavigate, useSearchParams } from "react-router-dom"
import dayjs, { type Dayjs } from "dayjs"
import { settleApi, errMsg, issuesText } from "../api/settle"
import { STATE_COLOR, money, percent } from "../utils/settle"
import type { SlDesigner, SlMeta, SlOrder } from "../types/settle"

const { Title, Text } = Typography

/**
 * 订单登记 + 订单列表（模块三）。
 *
 * 课件模块三的登记表单有几处硬规矩，这里都落到了界面上：
 * - **佣金比例限制在 50%~70%**，输入框直接限死，不用等后端报错
 * - **订单编号初稿后才补**，所以登记时允许留空
 * - **订单类型三选一**：个人接单 / 内部协作 / 外部合作
 * - 登记完只是「设计待定」，派单是下一个动作（不在这一页做）
 */
export default function SettleOrdersPage() {
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const [rows, setRows] = useState<SlOrder[]>([])
  const [designers, setDesigners] = useState<SlDesigner[]>([])
  const [meta, setMeta] = useState<SlMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [form] = Form.useForm()

  const state = params.get("state") ?? ""
  const designerId = params.get("designer_id") ?? ""

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const q: Record<string, string> = {}
      if (state) q.state = state
      if (designerId) q.designer_id = designerId
      if (keyword) q.keyword = keyword
      const [list, ds, m] = await Promise.all([
        settleApi.listOrders(q),
        settleApi.listDesigners(),
        settleApi.meta(),
      ])
      setRows(list)
      setDesigners(ds)
      setMeta(m)
    } catch (e) {
      message.error(errMsg(e, "订单加载失败"))
    } finally {
      setLoading(false)
    }
  }, [state, designerId, keyword])

  useEffect(() => {
    void load()
  }, [load])

  const designerOptions = useMemo(
    () => designers.map((d) => ({ value: d.id, label: `${d.name}（${d.nickname}）` })),
    [designers],
  )

  const stateOptions = useMemo(
    () => (meta?.states ?? []).map((s) => ({ value: s.value, label: s.label })),
    [meta],
  )

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  const openForm = () => {
    form.resetFields()
    form.setFieldsValue({
      order_type: "personal",
      commission_rate: 0.6,
      order_date: dayjs(),
    })
    setOpen(true)
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      const payload: Record<string, unknown> = { ...v }
      if (v.order_date) {
        payload.order_date = (v.order_date as Dayjs).format("YYYY-MM-DD")
      }
      await settleApi.createOrder(payload)
      message.success("订单已登记，当前状态「设计待定」，待派单")
      setOpen(false)
      await load()
    } catch (e) {
      message.error(issuesText(e) || errMsg(e, "登记失败"))
    }
  }

  const remove = (o: SlOrder) => {
    Modal.confirm({
      title: `删除订单 ${o.order_no || o.id}？`,
      content: "制作中的订单可直接删除；已交付的订单需联系客服处理。",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await settleApi.deleteOrder(o.id)
          message.success("已删除")
          await load()
        } catch (e) {
          message.error(errMsg(e, "删除失败"))
        }
      },
    })
  }

  const columns = [
    {
      title: "订单编号",
      dataIndex: "order_no",
      width: 150,
      render: (v: string, r: SlOrder) => (
        <Button type="link" size="small" style={{ padding: 0 }}
          onClick={() => nav(`/settle/orders/${r.id}`)}>
          {v || <Text type="secondary">未填写</Text>}
        </Button>
      ),
    },
    { title: "客户 ID", dataIndex: "customer_id", width: 130 },
    { title: "战区", dataIndex: "war_zone", width: 100,
      render: (v: string) => v || "—" },
    { title: "客服", dataIndex: "customer_service", width: 90,
      render: (v: string) => v || "—" },
    { title: "设计师", dataIndex: "designer_name", width: 100,
      render: (v: string) => v || <Text type="warning">待派单</Text> },
    { title: "类型", dataIndex: "order_type_label", width: 90 },
    { title: "服务类型", dataIndex: "service_type", width: 110,
      render: (v: string) => v || "—" },
    { title: "项目金额", dataIndex: "order_amount", width: 110, align: "right" as const,
      render: (v: string) => `¥${money(v)}` },
    { title: "佣金比例", dataIndex: "commission_rate", width: 90, align: "right" as const,
      render: (v: string) => percent(v) },
    { title: "设计师佣金", dataIndex: "designer_commission", width: 110,
      align: "right" as const,
      render: (v: string) => <Text strong>¥{money(v)}</Text> },
    { title: "交期", dataIndex: "deliver_date", width: 110 },
    { title: "状态", dataIndex: "state", width: 110,
      render: (v: string, r: SlOrder) => (
        <Tag color={STATE_COLOR[v]}>{r.state_label}</Tag>
      ) },
    { title: "操作", width: 90, fixed: "right" as const,
      render: (_: unknown, r: SlOrder) => (
        <Space size={2}>
          <Button size="small" onClick={() => nav(`/settle/orders/${r.id}`)}>详情</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => remove(r)} />
        </Space>
      ) },
  ]

  const rateMeta = meta?.commission_rate
  const rateMin = Number(rateMeta?.min ?? 0.5)
  const rateMax = Number(rateMeta?.max ?? 0.7)

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>订单登记</Title>

      {rateMeta && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`佣金比例区间 ${percent(rateMeta.min)} ~ ${percent(rateMeta.max)}`}
          description={rateMeta.text}
        />
      )}

      <Card size="small">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="auto">
            <Space wrap>
              <Select
                allowClear
                style={{ width: 150 }}
                placeholder="全部状态"
                value={state || undefined}
                options={stateOptions}
                onChange={(v?: string) => setFilter("state", v ?? "")}
              />
              <Select
                allowClear
                style={{ width: 180 }}
                placeholder="全部设计师"
                value={designerId || undefined}
                options={designerOptions}
                onChange={(v?: string) => setFilter("designer_id", v ?? "")}
              />
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="搜编号 / 客户 ID / 设计师 / 客服"
                style={{ width: 260 }}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </Space>
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />} onClick={openForm}>
              登记新订单
            </Button>
          </Col>
        </Row>
        <Table rowKey="id" size="small" loading={loading} dataSource={rows}
          columns={columns} scroll={{ x: 1600 }} pagination={false} />
      </Card>

      <Modal title="登记新订单" open={open} onCancel={() => setOpen(false)}
        onOk={() => void submit()} okText="登记" width={760}>
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="customer_id" label="客户 ID"
                rules={[{ required: true, message: "客户 ID 为必填项" }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="war_zone" label="所属战区">
                <Input placeholder="按实际填写" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="customer_service" label="客服"
                rules={[{ required: true, message: "客服为必填项" }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="designer_id" label="承接设计师"
                extra="可留空 —— 登记后走「派单」动作再指定">
                <Select allowClear options={designerOptions} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="order_type" label="订单类型"
                rules={[{ required: true, message: "订单类型为必填项" }]}>
                <Select options={(meta?.order_types ?? []).map((t) => ({
                  value: t.value, label: t.label,
                }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="service_type" label="服务类型">
                <Input placeholder="如 PPT 定制" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="order_no" label="订单编号"
                extra="初稿完成后才拿到，留空即可">
                <Input placeholder="留空待补" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="order_amount" label="项目金额"
                rules={[{ required: true, message: "项目金额为必填项" }]}>
                <InputNumber style={{ width: "100%" }} min={0} precision={2} prefix="¥" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="commission_rate" label="佣金比例"
                rules={[{ required: true, message: "佣金比例为必填项" }]}>
                <InputNumber
                  style={{ width: "100%" }}
                  min={rateMin} max={rateMax} step={0.01} precision={2}
                  formatter={(v) => `${(v ?? 0) * 100}%`}
                  parser={(v) => Number((v ?? "").replace("%", "")) / 100}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="deliver_date" label="交期"
                rules={[{ required: true, message: "交期为必填项" }]}>
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="order_date" label="接单日期"
                extra="结算有效期从这一天算起（60 天）">
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item name="requirement" label="需求说明">
                <Input.TextArea rows={3} placeholder="把客户需求写清楚，交付验收时按这个对" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
