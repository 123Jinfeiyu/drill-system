import { useCallback, useEffect, useState } from "react"
import {
  Button, Card, Col, Form, Input, InputNumber, Modal, Row, Space, Table,
  Typography, message,
} from "antd"
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons"
import { opcApi, errMsg } from "../api/opc"
import type { OpcStore } from "../types/opc"

const { Title, Text } = Typography

/** 店铺档案页。 */
export default function OpcStoresPage() {
  const [rows, setRows] = useState<OpcStore[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<OpcStore | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await opcApi.listStores())
    } catch (e) {
      message.error(errMsg(e, "店铺加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openForm = (s?: OpcStore) => {
    setEditing(s ?? null)
    form.resetFields()
    if (s) {
      form.setFieldsValue({
        name: s.name, url: s.url, customer_name: s.customer_name,
        manager: s.manager, settlement_days: s.settlement_days, remark: s.remark,
      })
    } else {
      form.setFieldsValue({ settlement_days: 30 })
    }
    setOpen(true)
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await opcApi.editStore(editing.id, v)
        message.success("已保存")
      } else {
        await opcApi.createStore(v)
        message.success("已添加")
      }
      setOpen(false)
      await load()
    } catch (e) {
      message.error(errMsg(e, "保存失败"))
    }
  }

  const remove = (s: OpcStore) => {
    Modal.confirm({
      title: `删除店铺 ${s.name}？`,
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await opcApi.deleteStore(s.id)
          message.success("已删除")
          await load()
        } catch (e) {
          message.error(errMsg(e, "删除失败"))
        }
      },
    })
  }

  const columns = [
    { title: "店铺名称", dataIndex: "name", width: 200 },
    { title: "客户", dataIndex: "customer_name", width: 140,
      render: (v: string) => v || "—" },
    { title: "负责人", dataIndex: "manager", width: 100,
      render: (v: string) => v || "—" },
    { title: "结算周期", dataIndex: "settlement_days", width: 100,
      align: "right" as const,
      render: (v: number) => (v ? `${v} 天` : "—") },
    { title: "订单数", dataIndex: "order_count", width: 80, align: "right" as const },
    { title: "备注", dataIndex: "remark", ellipsis: true },
    { title: "操作", width: 100,
      render: (_: unknown, r: OpcStore) => (
        <Space size={2}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openForm(r)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => remove(r)} />
        </Space>
      ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>店铺</Title>
      <Card size="small">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="auto">
            <Text type="secondary">
              结算周期会带到生成的结算单上 —— 结算端那边靠它算「什么时候该给钱」。
            </Text>
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm()}>
              添加店铺
            </Button>
          </Col>
        </Row>
        <Table rowKey="id" size="small" loading={loading} dataSource={rows}
          columns={columns} pagination={false} />
      </Card>

      <Modal title={editing ? `编辑 ${editing.name}` : "添加店铺"}
        open={open} onCancel={() => setOpen(false)} onOk={() => void submit()} okText="保存">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="店铺名称" rules={[{ required: true, message: "店铺名称必填" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="url" label="店铺链接">
            <Input placeholder="https://..." />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="customer_name" label="客户/事业部">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="manager" label="负责人">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="settlement_days" label="结算周期（天）">
            <InputNumber style={{ width: "100%" }} min={0} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
