import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Empty, List, Row, Statistic, Table, Tag, Typography,
  message,
} from "antd"
import { CalendarOutlined, ThunderboltOutlined } from "@ant-design/icons"
import { designerApi, errMsg } from "../api/settle"
import { money } from "../utils/settle"
import type { SlSettleCandidate, SlSettleableData } from "../types/settle"

const { Title, Text, Paragraph } = Typography

/**
 * 设计师端「一键结算」。
 *
 * 课件三条硬规则，这一页全部体现：
 * 1. **入口每月只在 8-9 号开放**，逾期自动关闭 —— 非窗口期按钮禁用
 * 2. **必须设计师主动点击才发起**，系统不自动发起
 * 3. **接单超过 60 天（两个月）失效** —— 过期单列出来并说明原因
 *
 * 发起后进「结算中」，等派单员在 15 号打款。
 */
export default function DesignerSettlePage() {
  const [data, setData] = useState<SlSettleableData | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await designerApi.settleable()
      setData(d)
      // 默认全选可结算的单 —— 设计师的意图通常就是「都结」
      setSelected(d.eligible.map((c) => c.order_id))
    } catch (e) {
      message.error(errMsg(e, "结算数据加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const doSettle = async () => {
    if (selected.length === 0) {
      message.warning("请至少选择一笔订单")
      return
    }
    setBusy(true)
    try {
      const r = await designerApi.settle(selected)
      if (r.created.length > 0) {
        message.success(`已发起 ${r.created.length} 笔结算，合计 ¥${money(
          r.created.reduce((a, s) => a + Number(s.commission || 0), 0),
        )}`)
      }
      if (r.skipped.length > 0) {
        message.warning(`${r.skipped.length} 笔未发起：${r.skipped[0].reason}`)
      }
      await load()
    } catch (e) {
      message.error(errMsg(e, "发起结算失败"))
    } finally {
      setBusy(false)
    }
  }

  const win = data?.window
  const eligible = data?.eligible ?? []
  const blocked = data?.blocked ?? []

  const selectedAmount = eligible
    .filter((c) => selected.includes(c.order_id))
    .reduce((acc, c) => acc + Number(c.commission || 0), 0)

  const cols = [
    { title: "订单编号", dataIndex: "order_no", width: 150,
      render: (v: string) => v || <Text type="secondary">未填写</Text> },
    { title: "佣金金额", dataIndex: "commission", width: 120, align: "right" as const,
      render: (v: string) => <Text strong>¥{money(v)}</Text> },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>一键结算</Title>

      {win && (
        <Alert
          style={{ marginBottom: 16 }}
          type={win.open ? "success" : "warning"}
          showIcon
          icon={<CalendarOutlined />}
          message={win.message}
          description={
            <Text type="secondary">
              结算窗口每月 {win.open_days.join(" / ")} 号开放，逾期入口自动关闭 ·
              统一打款日每月 {win.payout_day} 号（还有 {win.days_until_payout} 天）
              {win.open ? "" : ` · 下次开放：${win.next_open}`}
            </Text>
          }
        />
      )}

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="可结算笔数" value={data?.count ?? 0} suffix="笔" />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="可结算金额" value={money(data?.total_commission)} prefix="¥"
              valueStyle={{ color: "#52c41a" }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="已选择" value={selected.length} suffix="笔" />
            <Text type="secondary">合计 ¥{money(selectedAmount)}</Text>
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        title="待结算订单"
        extra={
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={busy}
            disabled={!win?.open || selected.length === 0}
            onClick={() => void doSettle()}
          >
            一键结算（{selected.length} 笔 · ¥{money(selectedAmount)}）
          </Button>
        }
      >
        {!win?.open && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="当前不在结算窗口，无法发起结算"
            description={`下次开放日期：${win?.next_open ?? "—"}。结算必须由你本人主动点击，系统不会自动发起。`}
          />
        )}

        {eligible.length === 0 ? (
          <Empty description="没有可结算的订单" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            rowKey="order_id"
            size="small"
            loading={loading}
            dataSource={eligible}
            columns={cols}
            pagination={false}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: (keys) => setSelected(keys.map(String)),
            }}
          />
        )}
      </Card>

      {blocked.length > 0 && (
        <Card size="small" title="已发起过结算的订单" style={{ marginTop: 16 }}>
          <List
            size="small"
            dataSource={blocked}
            renderItem={(c: SlSettleCandidate) => (
              <List.Item
                extra={<Tag color="default">已发起</Tag>}
              >
                <span>
                  {c.order_no || c.order_id} · ¥{money(c.commission)}
                  <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    {c.reasons.join("；") || "已发起过结算，不能重复发起"}
                  </Text>
                </span>
              </List.Item>
            )}
          />
        </Card>
      )}

      <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 16 }}>
        结算规则：接单后 60 天内有效；每月 8-9 号在结算端点击「一键结算」发起；
        派单员核对收款账号后于每月 15 号统一打款。
      </Paragraph>
    </div>
  )
}
