import { useCallback, useEffect, useState } from "react"
import {
  Alert, Card, Col, Empty, Row, Statistic, Table, Tag, Typography, message,
} from "antd"
import { designerApi, errMsg } from "../api/settle"
import { STATE_COLOR, money, percent } from "../utils/settle"
import type { SlOrder } from "../types/settle"

const { Title, Text, Paragraph } = Typography

/**
 * 设计师端「我的订单」。
 *
 * 课件要求设计师能实时查看名下订单进度。这一页刻意**不显示客服内部备注** ——
 * 后端 `me/orders` 已经把 note 去掉了，前端也不该再想办法显示。
 */
export default function DesignerOrdersPage() {
  const [rows, setRows] = useState<SlOrder[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await designerApi.orders())
    } catch (e) {
      message.error(errMsg(e, "订单加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const active = rows.filter((r) =>
    ["drafting", "finalizing", "pending_audit", "rejected", "settleable"].includes(r.state),
  )
  const totalCommission = rows.reduce((acc, r) => acc + Number(r.designer_commission || 0), 0)

  /** 给设计师看的下一步提示 —— 只是提醒，真正的门禁在后端。 */
  const nextHint = (o: SlOrder): string => {
    switch (o.state) {
      case "drafting":
        return "初稿制作中 —— 完成后记得补订单编号"
      case "finalizing":
        return "终稿制作中 —— 交付时需准备两类截图"
      case "pending_audit":
        return "已交付，等待验收"
      case "rejected":
        return `已驳回：${o.audit_remark || "请按备注改稿"}`
      case "settleable":
        return "验收通过 —— 别忘了在 8-9 号去点「一键结算」"
      case "settling":
        return "已发起结算，等待 15 号打款"
      case "settled":
        return "已结算"
      default:
        return ""
    }
  }

  const columns = [
    {
      title: "订单编号",
      dataIndex: "order_no",
      width: 150,
      render: (v: string) =>
        v || <Text type="secondary">未填写（初稿后补）</Text>,
    },
    { title: "类型", dataIndex: "order_type_label", width: 90 },
    { title: "服务类型", dataIndex: "service_type", width: 110,
      render: (v: string) => v || "—" },
    { title: "项目金额", dataIndex: "order_amount", width: 110, align: "right" as const,
      render: (v: string) => `¥${money(v)}` },
    { title: "佣金比例", dataIndex: "commission_rate", width: 90, align: "right" as const,
      render: (v: string) => percent(v) },
    { title: "我的佣金", dataIndex: "designer_commission", width: 110,
      align: "right" as const,
      render: (v: string) => <Text strong>¥{money(v)}</Text> },
    { title: "接单日期", dataIndex: "order_date", width: 110,
      render: (v: string) => v || "—" },
    { title: "交期", dataIndex: "deliver_date", width: 110,
      render: (v: string) => v || "—" },
    { title: "状态", dataIndex: "state", width: 110,
      render: (v: string, r: SlOrder) => (
        <Tag color={STATE_COLOR[v]}>{r.state_label}</Tag>
      ) },
    { title: "下一步", dataIndex: "id",
      render: (_: unknown, r: SlOrder) => {
        const hint = nextHint(r)
        return hint ? <Text style={{ fontSize: 12 }}>{hint}</Text> : "—"
      } },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>我的订单</Title>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="全部订单" value={rows.length} suffix="单" />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="进行中" value={active.length} suffix="单"
              valueStyle={{ color: "#1677ff" }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="累计佣金" value={money(totalCommission)} prefix="¥"
              valueStyle={{ color: "#52c41a" }} />
          </Card>
        </Col>
      </Row>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="结算有效期 60 天"
        description="从接单日期算起两个月内必须完成结算，逾期这笔佣金会失效。每月 8-9 号是结算窗口，15 号统一打款。"
      />

      <Card size="small">
        {rows.length === 0 ? (
          <Empty description="还没有接到订单" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            rowKey="id"
            size="small"
            loading={loading}
            dataSource={rows}
            columns={columns}
            scroll={{ x: 1200 }}
            pagination={false}
            expandable={{
              expandedRowRender: (r: SlOrder) => (
                <Paragraph style={{ marginBottom: 0 }}>
                  <Text strong>需求：</Text>
                  {r.requirement || "—"}
                </Paragraph>
              ),
            }}
          />
        )}
      </Card>
    </div>
  )
}
