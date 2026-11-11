import { useCallback, useEffect, useState } from "react"
import {
  Button, Card, Col, Form, Input, InputNumber, Modal, Row, Select, Space,
  Table, Tag, Typography, message,
} from "antd"
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons"
import { opcApi, errMsg } from "../api/opc"
import type { OpcDesigner } from "../types/opc"

const { Title, Text } = Typography

/** 设计师档案页。 */
export default function OpcDesignersPage() {
  const [rows, setRows] = useState<OpcDesigner[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<OpcDesigner | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await opcApi.listDesigners())
    } catch (e) {
      message.error(errMsg(e, "设计师加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openForm = (d?: OpcDesigner) => {
    setEditing(d ?? null)
    form.resetFields()
    if (d) {
      form.setFieldsValue({
        name: d.name, phone: d.phone, alipay_account: d.alipay_account,
        alipay_name: d.alipay_name, production_level: d.production_level,
        design_tags: d.design_tags, war_zone: d.war_zone, hr_id: d.hr_id,
        quality_control_id: d.quality_control_id,
        commission_rate: Number(d.commission_rate || 0),
        status: d.status, note: d.note,
      })
    } else {
      form.setFieldsValue({ status: "active", commission_rate: 0.7 })
    }
    setOpen(true)
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await opcApi.editDesigner(editing.id, v)
        message.success("已保存")
      } else {
        await opcApi.createDesigner(v)
        message.success("已添加")
      }
      setOpen(false)
      await load()
    } catch (e) {
      message.error(errMsg(e, "保存失败"))
    }
  }

  const remove = (d: OpcDesigner) => {
    Modal.confirm({
      title: `删除设计师 ${d.name}？`,
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await opcApi.deleteDesigner(d.id)
          message.success("已删除")
          await load()
        } catch (e) {
          message.error(errMsg(e, "删除失败"))
        }
      },
    })
  }

  const columns = [
    { title: "姓名", dataIndex: "name", width: 100 },
    { title: "擅长", dataIndex: "design_tags", ellipsis: true,
      render: (v: string) => v || <Text type="secondary">未标注</Text> },
    { title: "水平", dataIndex: "production_level", width: 80,
      render: (v: string) => v || "—" },
    { title: "战区", dataIndex: "war_zone", width: 100,
      render: (v: string) => v || "—" },
    { title: "手机", dataIndex: "phone", width: 120,
      render: (v: string) => v || "—" },
    { title: "支付宝", dataIndex: "alipay_account", width: 180, ellipsis: true,
      render: (v: string) => v || <Text type="secondary">未填</Text> },
    { title: "接单", dataIndex: "order_count", width: 70, align: "right" as const },
    { title: "在制", dataIndex: "active_count", width: 70, align: "right" as const },
    { title: "状态", dataIndex: "status", width: 80,
      render: (v: string) => (
        <Tag color={v === "active" ? "green" : "default"}>
          {v === "active" ? "可接单" : "停用"}
        </Tag>
      ) },
    { title: "操作", width: 100,
      render: (_: unknown, r: OpcDesigner) => (
        <Space size={2}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openForm(r)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => remove(r)} />
        </Space>
      ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>设计师</Title>
      <Card size="small">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="auto">
            <Text type="secondary">
              「擅长」字段是撮合推荐的关键 —— 推荐按需求关键词与它算相关度，写得越具体越准。
            </Text>
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm()}>
              添加设计师
            </Button>
          </Col>
        </Row>
        <Table rowKey="id" size="small" loading={loading} dataSource={rows}
          columns={columns} pagination={false} />
      </Card>

      <Modal title={editing ? `编辑 ${editing.name}` : "添加设计师"}
        open={open} onCancel={() => setOpen(false)} onOk={() => void submit()} okText="保存">
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="name" label="姓名" rules={[{ required: true, message: "姓名必填" }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="phone" label="手机">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="design_tags" label="擅长（逗号分隔）">
                <Input placeholder="女装 连衣裙 电商主图" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="production_level" label="制作水平">
                <Select options={[
                  { value: "初级", label: "初级" },
                  { value: "中级", label: "中级" },
                  { value: "资深", label: "资深" },
                ]} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="status" label="状态">
                <Select options={[
                  { value: "active", label: "可接单" },
                  { value: "inactive", label: "停用" },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="alipay_account" label="支付宝账户">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="alipay_name" label="支付宝实名">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="war_zone" label="所属战区">
                <Input />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="hr_id" label="所属 HR">
                <Input />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="quality_control_id" label="所属品控">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="commission_rate" label="默认佣金比例">
            <InputNumber style={{ width: "100%" }} min={0} max={1} step={0.01} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
