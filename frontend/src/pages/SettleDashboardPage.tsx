import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Empty, Row, Statistic, Table, Typography, message,
} from "antd"
import { ClockCircleOutlined, PhoneOutlined } from "@ant-design/icons"
import { useNavigate } from "react-router-dom"
import { settleApi, errMsg } from "../api/settle"
import { money } from "../utils/settle"
import type { SlDashboard, SlReminder } from "../types/settle"

const { Title, Text } = Typography

/**
 * 派单员业务看板。
 *
 * 课件业务看板要干三件事：**实时追踪每一笔业绩**、**实时对账**、
 * **高效结算**。所以这一页刻意按「今天该干什么」排：
 * 1. 顶部四张卡：本月业绩 / 待审核 / 可结算 / 结算窗口倒计时
 * 2. 中间左：订单漏斗（一眼看到卡在哪一环）
 * 3. 中间右：待提醒设计师（课件要求 7 号前提醒，这里直接能抄名单）
 * 4. 底部：结算汇总（待打款 / 已打款）
 */
export default function SettleDashboardPage() {
  const [dash, setDash] = useState<SlDashboard | null>(null)
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setDash(await settleApi.dashboard())
    } catch (e) {
      message.error(errMsg(e, "看板加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const win = dash?.window
  const summary = dash?.settlement_summary

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>结算业务看板</Title>

      {win && (
        <Alert
          style={{ marginBottom: 16 }}
          type={win.open ? "success" : "info"}
          showIcon
          icon={<ClockCircleOutlined />}
          message={win.message}
          description={
            <Text type="secondary">
              结算窗口每月 {win.open_days.join(" / ")} 号开放 ·
              统一打款日每月 {win.payout_day} 号 ·
              距打款日还有 {win.days_until_payout} 天
            </Text>
          }
        />
      )}

      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title={`本月业绩（${dash?.period ?? ""}）`}
              value={dash?.month_order_count ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 14 }}>单</Text>}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              项目金额 ¥{money(dash?.month_amount)} ·
              设计师佣金 ¥{money(dash?.month_commission)}
            </Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="待审核"
              value={dash?.pending_audit_count ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 14 }}>单</Text>}
              valueStyle={{ color: "#faad14" }}
            />
            <Button
              type="link" size="small" style={{ padding: 0 }}
              onClick={() => nav("/settle/orders?state=pending_audit")}
            >
              去处理 →
            </Button>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="可结算"
              value={dash?.settleable_count ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 14 }}>单</Text>}
              valueStyle={{ color: "#52c41a" }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              金额 ¥{money(dash?.settleable_amount)}
            </Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="设计师"
              value={dash?.designer_count ?? 0}
              suffix={
                <Text type="secondary" style={{ fontSize: 14 }}>
                  在职 {dash?.active_designer_count ?? 0}
                </Text>
              }
            />
            {dash && dash.draft_missing_count > 0 && (
              <Text type="warning" style={{ fontSize: 12 }}>
                {dash.draft_missing_count} 单在制未填订单编号
              </Text>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={14}>
          <Card size="small" title="订单漏斗"
            extra={<Text type="secondary">按状态统计，卡在哪一环一眼看到</Text>}>
            <Table
              rowKey="state"
              size="small"
              loading={loading}
              pagination={false}
              dataSource={dash?.funnel ?? []}
              onRow={(r) => ({ onClick: () => nav(`/settle/orders?state=${r.state}`) })}
              columns={[
                { title: "状态", dataIndex: "label", width: 120 },
                { title: "单数", dataIndex: "count", width: 80, align: "right" as const },
                { title: "项目金额", dataIndex: "amount", align: "right" as const,
                  render: (v: string) => `¥${money(v)}` },
              ]}
            />
          </Card>
        </Col>

        <Col span={10}>
          <Card
            size="small"
            title="待提醒设计师"
            extra={<Text type="secondary">{dash?.remind_designers.length ?? 0} 人</Text>}
          >
            <Text type="secondary" style={{ fontSize: 12 }}>
              课件要求每月 7 号前提醒设计师在 8-9 号窗口完成结算，逾期佣金会延迟或失效。
            </Text>
            {dash && dash.remind_designers.length > 0 ? (
              <Table
                rowKey="designer_id"
                size="small"
                pagination={false}
                style={{ marginTop: 8 }}
                dataSource={dash.remind_designers}
                columns={[
                  { title: "设计师", dataIndex: "designer_name", width: 90 },
                  { title: "可结算", dataIndex: "order_count", width: 70,
                    align: "right" as const },
                  { title: "金额", dataIndex: "commission", align: "right" as const,
                    render: (v: string) => `¥${money(v)}` },
                  {
                    title: "联系",
                    width: 110,
                    render: (_: unknown, r: SlReminder) =>
                      r.phone ? (
                        <a href={`tel:${r.phone}`}>
                          <PhoneOutlined /> {r.phone}
                        </a>
                      ) : (
                        <Text type="secondary">未录入</Text>
                      ),
                  },
                ]}
              />
            ) : (
              <Empty description="没有待提醒的设计师" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      {summary && (
        <Card size="small" title="结算汇总" style={{ marginTop: 16 }}>
          <Row gutter={[16, 16]}>
            <Col span={6}>
              <Statistic title="待打款笔数" value={summary.pending_count} />
              <Text type="secondary">¥{money(summary.pending_amount)}</Text>
            </Col>
            <Col span={6}>
              <Statistic title="已打款笔数" value={summary.paid_count}
                valueStyle={{ color: "#52c41a" }} />
              <Text type="secondary">¥{money(summary.paid_amount)}</Text>
            </Col>
            <Col span={12}>
              {summary.by_designer.length > 0 && (
                <Table
                  rowKey="designer_name"
                  size="small"
                  pagination={false}
                  dataSource={summary.by_designer}
                  columns={[
                    { title: "设计师", dataIndex: "designer_name" },
                    { title: "笔数", dataIndex: "count", width: 80, align: "right" as const },
                    { title: "金额", dataIndex: "amount", align: "right" as const,
                      render: (v: string) => `¥${money(v)}` },
                  ]}
                />
              )}
            </Col>
          </Row>
        </Card>
      )}
    </div>
  )
}
