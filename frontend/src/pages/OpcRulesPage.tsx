import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Form, Input, InputNumber, Row, Space, Table, Tag,
  Typography, message,
} from "antd"
import { CalculatorOutlined, DeleteOutlined, SaveOutlined } from "@ant-design/icons"
import { opcApi, errMsg } from "../api/opc"
import type { OpcSplitRule } from "../types/opc"

const { Title, Text } = Typography

/**
 * 分账规则页 + 试算器。
 *
 * 比例只从这张表读 —— 代码里不写死任何比例。改比例即时生效。
 */
export default function OpcRulesPage() {
  const [rows, setRows] = useState<OpcSplitRule[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState("1000")
  const [preview, setPreview] = useState<{
    rows: { scope: string; label: string; amount: string; rate: string; percent: string }[]
    issues: string[]
  } | null>(null)
  const [editing, setEditing] = useState<OpcSplitRule | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await opcApi.listRules())
    } catch (e) {
      message.error(errMsg(e, "规则加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const doPreview = useCallback(async (t: string) => {
    try {
      const r = await opcApi.previewSplit(t)
      setPreview(r)
    } catch (e) {
      message.error(errMsg(e, "试算失败"))
    }
  }, [])

  useEffect(() => { void doPreview(total) }, [total, doPreview])

  const startEdit = (r: OpcSplitRule) => {
    setEditing(r)
    form.setFieldsValue({
      scope: r.scope, rate: Number(r.rate || 0),
      basis: r.basis, enabled: r.enabled, remark: r.remark,
    })
  }

  const save = async () => {
    try {
      const v = await form.validateFields()
      await opcApi.saveRule(v)
      message.success("已保存")
      setEditing(null)
      await load()
      await doPreview(total)
    } catch (e) {
      message.error(errMsg(e, "保存失败"))
    }
  }

  const remove = async (r: OpcSplitRule) => {
    try {
      await opcApi.deleteRule(r.id)
      message.success("已删除")
      await load()
      await doPreview(total)
    } catch (e) {
      message.error(errMsg(e, "删除失败"))
    }
  }

  const columns = [
    { title: "口径", dataIndex: "scope_label", width: 130 },
    { title: "比例", dataIndex: "rate", width: 100, align: "right" as const,
      render: (v: string) => `${(Number(v) * 100).toFixed(2)}%` },
    { title: "基数", dataIndex: "basis", width: 100,
      render: (v: string) => (v === "total" ? "订单总额" : v === "basis" ? "奖金基数" : v) },
    { title: "启用", dataIndex: "enabled", width: 80,
      render: (v: boolean) => (
        <Tag color={v ? "green" : "default"}>{v ? "启用" : "停用"}</Tag>
      ) },
    { title: "备注", dataIndex: "remark", ellipsis: true },
    { title: "操作", width: 140,
      render: (_: unknown, r: OpcSplitRule) => (
        <Space size={2}>
          <Button size="small" icon={<SaveOutlined />} onClick={() => startEdit(r)}>改</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => void remove(r)} />
        </Space>
      ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>分账规则</Title>
      <Row gutter={[16, 16]}>
        <Col span={14}>
          <Card size="small" title="分账规则"
            extra={<Text type="secondary">比例只从这里读，代码里不写死</Text>}>
            <Alert type="info" showIcon style={{ marginBottom: 12 }}
              message="分账口径说明"
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  <li><strong>设计师佣金</strong>：结算单里给设计师的金额</li>
                  <li><strong>HR / 品控佣金</strong>：内部角色抽成</li>
                  <li><strong>主管奖金</strong>：按「奖金基数」算，可与总额脱钩</li>
                  <li><strong>中控金额</strong>：公司留存；比例总和不足 100% 时余数也归这里</li>
                </ul>
              } />
            <Table rowKey="id" size="small" loading={loading} dataSource={rows}
              columns={columns} pagination={false} />
          </Card>
        </Col>

        <Col span={10}>
          <Card size="small" title="试算器"
            extra={<CalculatorOutlined />}>
            <Input
              addonBefore="订单金额"
              value={total}
              onChange={(e) => setTotal(e.target.value)}
              style={{ marginBottom: 12 }}
            />
            {preview && preview.rows.length > 0 && (
              <Table
                rowKey="scope"
                size="small"
                pagination={false}
                dataSource={preview.rows}
                columns={[
                  { title: "口径", dataIndex: "label" },
                  { title: "金额", dataIndex: "amount", align: "right" as const,
                    render: (v: string) => `¥${v}` },
                  { title: "占比", dataIndex: "percent", align: "right" as const,
                    render: (v: string) => `${v}%` },
                ]}
              />
            )}
            {preview && preview.issues.length > 0 && (
              <Alert type="warning" showIcon style={{ marginTop: 12 }}
                message="规则有问题" description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.issues.map((i) => <li key={i}>{i}</li>)}
                  </ul>
                } />
            )}
          </Card>

          {editing && (
            <Card size="small" title={`改规则 · ${editing.scope_label}`}
              style={{ marginTop: 16 }}
              extra={<Button size="small" onClick={() => setEditing(null)}>取消</Button>}>
              <Form form={form} layout="vertical">
                <Form.Item name="scope" label="口径">
                  <Input disabled />
                </Form.Item>
                <Form.Item name="rate" label="比例（0-1）" rules={[
                  { required: true, message: "比例必填" },
                  { validator: (_, v) => {
                    if (v === undefined || v === null) return Promise.resolve()
                    if (v < 0 || v > 1) return Promise.reject(new Error("比例必须在 0 到 1 之间"))
                    return Promise.resolve()
                  } },
                ]}>
                  <InputNumber style={{ width: "100%" }} min={0} max={1} step={0.01} />
                </Form.Item>
                <Form.Item name="basis" label="计分基数">
                  <Row>
                    <Col span={12}>
                      <Button size="small" onClick={() => form.setFieldValue("basis", "total")}>
                        按总额
                      </Button>
                    </Col>
                    <Col span={12}>
                      <Button size="small" onClick={() => form.setFieldValue("basis", "basis")}>
                        按奖金基数
                      </Button>
                    </Col>
                  </Row>
                </Form.Item>
                <Form.Item name="enabled" label="启用" valuePropName="checked">
                  <Tag
                    color={form.getFieldValue("enabled") ? "green" : "default"}
                    onClick={() => form.setFieldValue("enabled", !form.getFieldValue("enabled"))}
                    style={{ cursor: "pointer", userSelect: "none" }}
                  >
                    {form.getFieldValue("enabled") ? "启用" : "停用"}（点此切换）
                  </Tag>
                </Form.Item>
                <Form.Item name="remark" label="备注">
                  <Input />
                </Form.Item>
                <Button type="primary" block onClick={() => void save()}>保存</Button>
              </Form>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  )
}
