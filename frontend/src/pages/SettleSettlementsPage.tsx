import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Form, Input, Modal, Row, Select, Space, Statistic, Table,
  Tag, Typography, message,
} from "antd"
import { CheckCircleOutlined } from "@ant-design/icons"
import { settleApi, errMsg } from "../api/settle"
import { SETTLE_STATUS_COLOR, SETTLE_STATUS_LABEL, money } from "../utils/settle"
import type { SlSettlement } from "../types/settle"

const { Title, Text } = Typography

/**
 * 结算管理（派单员侧）。
 *
 * **这里没有「发起结算」按钮** —— 课件要求结算必须由设计师主动点「一键结算」，
 * 派单员越权发起会绕过窗口限制。所以这一页只做两件事：
 * 1. 看结算单（谁、多少钱、什么时候结算的）
 * 2. 钱转出去之后**标记已打款 + 填流水号**（流水号是对账凭证，必填）
 */
export default function SettleSettlementsPage() {
  const [rows, setRows] = useState<SlSettlement[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState("")
  const [period, setPeriod] = useState("")
  const [paying, setPaying] = useState<SlSettlement | null>(null)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const q: Record<string, string> = {}
      if (status) q.status = status
      if (period) q.period = period
      setRows(await settleApi.listSettlements(q))
    } catch (e) {
      message.error(errMsg(e, "结算单加载失败"))
    } finally {
      setLoading(false)
    }
  }, [status, period])

  useEffect(() => {
    void load()
  }, [load])

  const openPay = (s: SlSettlement) => {
    setPaying(s)
    form.resetFields()
  }

  const doPay = async () => {
    if (!paying) return
    try {
      const v = await form.validateFields()
      setBusy(true)
      await settleApi.paySettlement(paying.id, {
        flow_no: String(v.flow_no ?? "").trim(),
        pay_date: v.pay_date ? String(v.pay_date) : undefined,
      })
      message.success("已标记打款")
      setPaying(null)
      await load()
    } catch (e) {
      message.error(errMsg(e, "标记失败"))
    } finally {
      setBusy(false)
    }
  }

  const pending = rows.filter((r) => r.status === "pending")
  const paid = rows.filter((r) => r.status === "paid")
  const sum = (list: SlSettlement[]) =>
    money(list.reduce((acc, r) => acc + Number(r.commission || 0), 0))

  // 结算期从结算单的 period 字段去重
  const periods = Array.from(new Set(rows.map((r) => r.period).filter(Boolean))).sort().reverse()

  const columns = [
    { title: "结算期", dataIndex: "period", width: 100 },
    { title: "设计师", dataIndex: "designer_name", width: 100 },
    { title: "佣金金额", dataIndex: "commission", width: 120, align: "right" as const,
      render: (v: string) => <Text strong>¥{money(v)}</Text> },
    { title: "收款账号", dataIndex: "alipay_account", width: 170, ellipsis: true },
    { title: "实名", dataIndex: "alipay_name", width: 100 },
    { title: "状态", dataIndex: "status", width: 90,
      render: (v: string) => (
        <Tag color={SETTLE_STATUS_COLOR[v] ?? "default"}>
          {SETTLE_STATUS_LABEL[v] ?? v}
        </Tag>
      ) },
    { title: "打款日期", dataIndex: "pay_date", width: 110,
      render: (v: string) => v || "—" },
    { title: "流水号", dataIndex: "flow_no", width: 150,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: "发起时间", dataIndex: "created_at", width: 160,
      render: (v: string) => v?.replace("T", " ").slice(0, 16) || "—" },
    { title: "操作", width: 110, fixed: "right" as const,
      render: (_: unknown, r: SlSettlement) =>
        r.status === "pending" ? (
          <Button size="small" type="primary" icon={<CheckCircleOutlined />}
            onClick={() => openPay(r)}>
            标记打款
          </Button>
        ) : (
          <Text type="secondary">—</Text>
        ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>结算管理</Title>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="结算由设计师主动发起，这里只负责「标记已打款」"
        description="课件要求设计师在每月 8-9 号结算窗口内自行点击「一键结算」，派单员不能代为发起。统一打款日为每月 15 号。"
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="待打款" value={pending.length}
              valueStyle={{ color: "#faad14" }} suffix="笔" />
            <Text type="secondary">合计 ¥{sum(pending)}</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="已打款" value={paid.length}
              valueStyle={{ color: "#52c41a" }} suffix="笔" />
            <Text type="secondary">合计 ¥{sum(paid)}</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="本表合计" value={rows.length} suffix="笔" />
            <Text type="secondary">¥{sum(rows)}</Text>
          </Card>
        </Col>
      </Row>

      <Card size="small">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="auto">
            <Space wrap>
              <Select
                allowClear
                style={{ width: 140 }}
                placeholder="全部状态"
                value={status || undefined}
                onChange={(v?: string) => setStatus(v ?? "")}
                options={[
                  { value: "pending", label: "待打款" },
                  { value: "paid", label: "已打款" },
                  { value: "invalid", label: "已失效" },
                ]}
              />
              <Select
                allowClear
                style={{ width: 140 }}
                placeholder="全部结算期"
                value={period || undefined}
                onChange={(v?: string) => setPeriod(v ?? "")}
                options={periods.map((p) => ({ value: p, label: p }))}
              />
            </Space>
          </Col>
        </Row>
        <Table rowKey="id" size="small" loading={loading} dataSource={rows}
          columns={columns} scroll={{ x: 1400 }} pagination={false} />
      </Card>

      <Modal title="标记已打款" open={!!paying} onCancel={() => setPaying(null)}
        onOk={() => void doPay()} okText="确认打款" confirmLoading={busy}>
        {paying && (
          <>
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={`${paying.designer_name} · ¥${money(paying.commission)}`}
              description={`收款账号 ${paying.alipay_account || "未填"}（${paying.alipay_name || "—"}）。转账前请再核对一次账号与金额。`}
            />
            <Form form={form} layout="vertical">
              <Form.Item name="flow_no" label="打款流水号"
                rules={[{ required: true, message: "流水号必填 —— 这是对账凭证" }]}>
                <Input placeholder="支付宝 / 银行转账流水号" />
              </Form.Item>
              <Form.Item name="pay_date" label="打款日期">
                <Input placeholder="留空则取今天" />
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>
    </div>
  )
}
