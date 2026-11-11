import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Button, Card, Col, Drawer, Form, Input, InputNumber, Modal, Row, Select,
  Space, Table, Tag, Typography, message,
} from "antd"
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons"
import { useNavigate } from "react-router-dom"
import { opcApi, errMsg } from "../api/opc"
import type { OpcMeta, OpcOrder } from "../types/opc"

const { Title, Text } = Typography

/** 订单池：全部订单 + 筛选 + 新建。 */
export default function OpcOrdersPage() {
  const [orders, setOrders] = useState<OpcOrder[]>([])
  const [meta, setMeta] = useState<OpcMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [state, setState] = useState("")
  const [keyword, setKeyword] = useState("")
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [specIssues, setSpecIssues] = useState<string[]>([])
  const nav = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await opcApi.listOrders({ state, keyword })
      setOrders(rows)
    } catch (e) {
      message.error(errMsg(e, "订单加载失败"))
    } finally {
      setLoading(false)
    }
  }, [state, keyword])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void opcApi.meta().then(setMeta).catch(() => undefined)
  }, [])

  const stateOptions = useMemo(
    () => (meta?.states ?? []).map((s) => ({ value: s.value, label: s.label })),
    [meta],
  )

  const checkSpec = async () => {
    const text = form.getFieldValue("spec_snapshot") as string | undefined
    if (!text) {
      setSpecIssues(["需求单还没写"])
      return
    }
    try {
      const res = await opcApi.validateSpec(text)
      setSpecIssues(res.issues)
      if (res.ok) message.success("需求单结构合格")
    } catch (e) {
      message.error(errMsg(e, "校验失败"))
    }
  }

  const fillTemplate = () => {
    form.setFieldValue("spec_snapshot", meta?.spec_template ?? "")
    void checkSpec()
  }

  const submit = async () => {
    try {
      const values = await form.validateFields()
      const created = await opcApi.createOrder(values)
      message.success(`订单 ${created.order_sn} 已创建`)
      setOpen(false)
      form.resetFields()
      setSpecIssues([])
      await load()
    } catch (e) {
      message.error(errMsg(e, "创建失败"))
    }
  }

  const remove = (o: OpcOrder) => {
    Modal.confirm({
      title: `删除订单 ${o.order_sn}？`,
      content: "只有还没进入履约的订单才能删。删了不可恢复。",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await opcApi.deleteOrder(o.id)
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
      dataIndex: "order_sn",
      width: 150,
      render: (v: string, r: OpcOrder) => (
        <Button type="link" size="small" onClick={() => nav(`/opc/orders/${r.id}`)}>
          {v}
        </Button>
      ),
    },
    { title: "标题", dataIndex: "title", ellipsis: true,
      render: (v: string, r: OpcOrder) => (
        <Space direction="vertical" size={0}>
          <span>{v || <Text type="secondary">（未填标题）</Text>}</span>
          {r.spec_issues.length > 0 && (
            <Tag color="orange" style={{ fontSize: 11 }}>
              需求单缺 {r.spec_issues.length} 项
            </Tag>
          )}
        </Space>
      ) },
    { title: "店铺", dataIndex: "store_name", width: 150, ellipsis: true },
    { title: "设计师", dataIndex: "designer_name", width: 100,
      render: (v: string) => v || <Text type="secondary">未指派</Text> },
    { title: "档次", dataIndex: "order_grade", width: 80,
      render: (v: string) => v || "—" },
    { title: "金额", dataIndex: "order_commission", width: 110,
      align: "right" as const, render: (v: string) => `¥${v}` },
    { title: "状态", dataIndex: "state_label", width: 110,
      render: (v: string, r: OpcOrder) => (
        <Space direction="vertical" size={0}>
          <Tag color="blue">{v}</Tag>
          {r.acceptance === "accepted" && <Tag color="green" style={{ fontSize: 11 }}>已验收</Tag>}
        </Space>
      ) },
    { title: "操作", width: 130,
      render: (_: unknown, r: OpcOrder) => (
        <Space size={2}>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => nav(`/opc/orders/${r.id}`)} />
          <Button size="small" danger icon={<DeleteOutlined />}
            onClick={() => remove(r)} />
        </Space>
      ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>订单池</Title>
      <Card size="small">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="auto">
            <Space wrap>
              <Select
                allowClear placeholder="全部状态" style={{ width: 160 }}
                value={state || undefined}
                options={stateOptions}
                onChange={(v) => setState(v ?? "")}
              />
              <Input.Search
                allowClear placeholder="搜订单号 / 标题 / 设计师 / 店铺"
                style={{ width: 280 }}
                onSearch={(v) => setKeyword(v)}
              />
            </Space>
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
              新建订单
            </Button>
          </Col>
        </Row>

        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={orders}
          columns={columns}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Drawer
        title="新建订单"
        width={720}
        open={open}
        onClose={() => setOpen(false)}
        extra={
          <Space>
            <Button onClick={() => void checkSpec()}>校验需求单</Button>
            <Button type="primary" onClick={() => void submit()}>创建</Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="order_sn" label="订单编号" rules={[{ required: true, message: "订单编号必填" }]}>
                <Input placeholder="如 OP-20261101-001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="title" label="订单标题">
                <Input placeholder="如 秋季新品主图 5 张" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="order_commission" label="订单金额（元）">
                <InputNumber style={{ width: "100%" }} min={0} precision={2} stringMode
                  placeholder="1000.00" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="order_grade" label="订单档次">
                <Input placeholder="普通 / 优质 / 加急" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="order_type" label="订单类型">
                <Input placeholder="线上 / 线下 / 样稿" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="request_delivery_time" label="要求交付时间">
                <Input placeholder="2026-11-05" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="remark" label="备注">
                <Input placeholder="其它要交代的事" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="spec_snapshot"
            label={
              <Space>
                <span>需求单（六段式）</span>
                <Button size="small" type="link" onClick={fillTemplate}>插入模板</Button>
              </Space>
            }
          >
            <Input.TextArea rows={16} style={{ fontFamily: "Consolas, monospace", fontSize: 13 }}
              placeholder="## 目标&#10;## 范围&#10;## 非目标&#10;## 约束&#10;## 验收标准&#10;## 完成定义" />
          </Form.Item>

          {specIssues.length > 0 && (
            <Card size="small" style={{ borderColor: "#faad14" }}>
              <Text strong style={{ color: "#d48806" }}>需求单还缺：</Text>
              <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                {specIssues.map((i) => <li key={i}><Text style={{ fontSize: 13 }}>{i}</Text></li>)}
              </ul>
            </Card>
          )}
        </Form>
      </Drawer>
    </div>
  )
}
