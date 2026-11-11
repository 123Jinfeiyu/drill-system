import { useCallback, useEffect, useState } from "react"
import {
  Card, Col, Empty, Row, Statistic, Table, Tag, Typography, message,
} from "antd"
import { designerApi, errMsg } from "../api/settle"
import { SETTLE_STATUS_COLOR, SETTLE_STATUS_LABEL, money } from "../utils/settle"
import type { SlSettlement } from "../types/settle"

const { Title, Text } = Typography

/**
 * 设计师端「收益明细」。
 *
 * 课件要求设计师能查自己的每一笔结算与打款记录。
 * 金额一律用后端给的原值展示，**前端不做任何换算** ——
 * 结算金额差一分钱都是账务问题，不该在展示层被四舍五入掉。
 */
export default function DesignerIncomePage() {
  const [rows, setRows] = useState<SlSettlement[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await designerApi.settlements())
    } catch (e) {
      message.error(errMsg(e, "收益明细加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const pending = rows.filter((r) => r.status === "pending")
  const paid = rows.filter((r) => r.status === "paid")
  const sum = (list: SlSettlement[]) =>
    money(list.reduce((acc, r) => acc + Number(r.commission || 0), 0))

  const columns = [
    { title: "结算期", dataIndex: "period", width: 100 },
    { title: "佣金金额", dataIndex: "commission", width: 130, align: "right" as const,
      render: (v: string) => <Text strong>¥{money(v)}</Text> },
    { title: "状态", dataIndex: "status", width: 100,
      render: (v: string) => (
        <Tag color={SETTLE_STATUS_COLOR[v] ?? "default"}>
          {SETTLE_STATUS_LABEL[v] ?? v}
        </Tag>
      ) },
    { title: "收款账号", dataIndex: "alipay_account", width: 180, ellipsis: true },
    { title: "打款日期", dataIndex: "pay_date", width: 120,
      render: (v: string) => v || "—" },
    { title: "流水号", dataIndex: "flow_no", width: 160,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: "发起时间", dataIndex: "created_at", width: 170,
      render: (v: string) => v?.replace("T", " ").slice(0, 16) || "—" },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>收益明细</Title>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="待打款" value={pending.length} suffix="笔"
              valueStyle={{ color: "#faad14" }} />
            <Text type="secondary">合计 ¥{sum(pending)}</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="已打款" value={paid.length} suffix="笔"
              valueStyle={{ color: "#52c41a" }} />
            <Text type="secondary">合计 ¥{sum(paid)}</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="累计收益"
              value={money(rows.reduce((a, r) => a + Number(r.commission || 0), 0))}
              prefix="¥" />
            <Text type="secondary">共 {rows.length} 笔</Text>
          </Card>
        </Col>
      </Row>

      <Card size="small">
        {rows.length === 0 ? (
          <Empty description="还没有结算记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            rowKey="id"
            size="small"
            loading={loading}
            dataSource={rows}
            columns={columns}
            scroll={{ x: 1100 }}
            pagination={false}
          />
        )}
      </Card>
    </div>
  )
}
