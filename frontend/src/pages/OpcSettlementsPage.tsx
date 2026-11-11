import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Form, Input, Modal, Row, Select, Space, Statistic,
  Table, Tag, Typography, message,
} from "antd"
import { DollarOutlined, ReloadOutlined, WalletOutlined } from "@ant-design/icons"
import { opcApi, errMsg } from "../api/opc"
import type { OpcSettlement, OpcSettlementSummary } from "../types/opc"

const { Title, Text } = Typography

/** 结算页：生成结算单 → 记录打款。 */
export default function OpcSettlementsPage() {
  const [rows, setRows] = useState<OpcSettlement[]>([])
  const [sum, setSum] = useState<OpcSettlementSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState("")
  const [payOpen, setPayOpen] = useState(false)
  const [paying, setPaying] = useState<OpcSettlement | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, s] = await Promise.all([
        opcApi.listSettlements(status), opcApi.settlementSummary(),
      ])
      setRows(r)
      setSum(s)
    } catch (e) {
      message.error(errMsg(e, "结算数据加载失败"))
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => { void load() }, [load])

  const generate = async () => {
    try {
      const res = await opcApi.generateSettlements([])
      if (res.created.length === 0) {
        Modal.info({
          title: "没有可生成的结算单",
          content: res.skipped.length > 0
            ? "以下订单被跳过：\n" + res.skipped.map((s) => `· ${s.order_sn}：${s.reason}`).join("\n")
            : "没有「已交付」状态的订单。",
        })
        return
      }
      message.success(`生成 ${res.created.length} 张结算单`)
      if (res.skipped.length > 0) {
        Modal.warning({
          title: `跳过 ${res.skipped.length} 单`,
          content: res.skipped.map((s) => `· ${s.order_sn}：${s.reason}`).join("\n"),
        })
      }
      await load()
    } catch (e) {
      message.error(errMsg(e, "生成失败"))
    }
  }

  const openPay = (s: OpcSettlement) => {
    setPaying(s)
    form.resetFields()
    form.setFieldsValue({
      actor: "", upstream_settlement_time: "", remark: s.remark,
    })
    setPayOpen(true)
  }

  const submitPay = async () => {
    if (!paying) return
    try {
      const v = await form.validateFields()
      await opcApi.paySettlement(paying.id, v)
      message.success("已标记为已打款")
      setPayOpen(false)
      await load()
    } catch (e) {
      message.error(errMsg(e, "标记失败"))
    }
  }

  const columns = [
    { title: "订单编号", dataIndex: "order_sn", width: 160 },
    { title: "设计师", dataIndex: "designer_name", width: 110 },
    { title: "结算金额", dataIndex: "commission", width: 120, align: "right" as const,
      render: (v: string) => `¥${v}` },
    { title: "结算周期", dataIndex: "settlement_days", width: 100, align: "right" as const,
      render: (v: number) => (v ? `${v} 天` : "—") },
    { title: "支付宝", dataIndex: "alipay_account", ellipsis: true,
      render: (v: string) => v || <Text type="secondary">未填</Text> },
    { title: "状态", dataIndex: "status", width: 100,
      render: (v: string) => (
        <Tag color={v === "paid" ? "green" : "orange"}>
          {v === "paid" ? "已打款" : "待打款"}
        </Tag>
      ) },
    { title: "打款时间", dataIndex: "upstream_settlement_time", width: 120,
      render: (v: string, r: OpcSettlement) => v || (
        r.paid_at ? new Date(r.paid_at).toLocaleDateString("zh-CN") : "—") },
    { title: "操作", width: 110,
      render: (_: unknown, r: OpcSettlement) => (
        r.status === "paid"
          ? <Text type="secondary" style={{ fontSize: 12 }}>已完成</Text>
          : <Button size="small" type="primary" onClick={() => openPay(r)}>标记打款</Button>
      ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>结算</Title>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="待结算笔数" value={sum?.pending_count ?? 0}
              prefix={<WalletOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="待结算金额" value={sum?.pending_amount ?? "0"} prefix="¥"
              valueStyle={{ color: "#d48806" }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已打款笔数" value={sum?.paid_count ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已打款金额" value={sum?.paid_amount ?? "0"} prefix="¥"
              valueStyle={{ color: "#389e0d" }} />
          </Card>
        </Col>
      </Row>

      <Card size="small" style={{ marginTop: 16 }}
        title="结算单"
        extra={
          <Space>
            <Select allowClear placeholder="全部状态" style={{ width: 120 }}
              value={status || undefined}
              options={[
                { value: "pending", label: "待打款" },
                { value: "paid", label: "已打款" },
              ]}
              onChange={(v?: string) => setStatus(v ?? "")} />
            <Button icon={<ReloadOutlined />} onClick={() => void load()} />
            <Button type="primary" icon={<DollarOutlined />} onClick={() => void generate()}>
              一键生成结算单
            </Button>
          </Space>
        }>
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="系统只做记录与对账"
          description="实际打款走支付宝手工操作，这里负责记「已打款 + 时间 + 备注」，方便月底对账。" />
        <Table rowKey="id" size="small" loading={loading} dataSource={rows}
          columns={columns} pagination={false} />
      </Card>

      {sum && sum.by_designer.length > 0 && (
        <Card size="small" title="按设计师汇总（待结算）" style={{ marginTop: 16 }}>
          <Table
            rowKey="designer_name"
            size="small"
            pagination={false}
            dataSource={sum.by_designer}
            columns={[
              { title: "设计师", dataIndex: "designer_name" },
              { title: "笔数", dataIndex: "count", width: 90, align: "right" as const },
              { title: "金额", dataIndex: "amount", align: "right" as const,
                render: (v: string) => `¥${v}` },
            ]}
          />
        </Card>
      )}

      <Modal title={paying ? `标记打款 · ${paying.order_sn}` : "标记打款"}
        open={payOpen} onCancel={() => setPayOpen(false)}
        onOk={() => void submitPay()} okText="确认已打款">
        {paying && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message="确认你已经在支付宝实际转账了" />
        )}
        <Form form={form} layout="vertical">
          <Form.Item name="actor" label="操作人" rules={[{ required: true, message: "操作人必填" }]}>
            <Input placeholder="如 张老板" />
          </Form.Item>
          <Form.Item name="upstream_settlement_time" label="上游结算时间">
            <Input placeholder="2026-11-30" />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} placeholder="流水号、说明等" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
