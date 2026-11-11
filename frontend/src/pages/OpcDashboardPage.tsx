import { useCallback, useEffect, useState } from "react"
import {
  Button, Card, Col, Empty, Row, Select, Space, Statistic, Table, Tag,
  Tooltip, Typography, message, theme,
} from "antd"
import { ArrowRightOutlined, ThunderboltOutlined } from "@ant-design/icons"
import { useNavigate } from "react-router-dom"
import { opcApi, errMsg } from "../api/opc"
import type { OpcMatchBoard, OpcOrder } from "../types/opc"

const { Title, Text } = Typography

/**
 * 撮合看板 —— 一人公司的「今天该干什么」入口。
 *
 * 四块：待派单 / 在制 / 待验收 / 待结算。
 * 待派单那块带 AI 推荐（没配 key 时自动降级为本地关键词相关度，候选池不空）。
 */
export default function OpcDashboardPage() {
  const [board, setBoard] = useState<OpcMatchBoard | null>(null)
  const [dash, setDash] = useState<Awaited<ReturnType<typeof opcApi.dashboard>> | null>(null)
  const [, setLoading] = useState(false)
  const [assigning, setAssigning] = useState<string>("")
  const [recommend, setRecommend] = useState<{
    orderId: string
    candidates: { designer_id: string; name: string; score: number; reason?: string }[]
    reason: string
    source: string
  } | null>(null)
  const nav = useNavigate()
  const { token } = theme.useToken()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [b, d] = await Promise.all([opcApi.matchBoard(), opcApi.dashboard()])
      setBoard(b)
      setDash(d)
    } catch (e) {
      message.error(errMsg(e, "看板加载失败"))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const doAssign = async (orderId: string, designerId: string) => {
    setAssigning(orderId)
    try {
      await opcApi.assign(orderId, designerId)
      message.success("派单成功")
      await load()
    } catch (e) {
      message.error(errMsg(e, "派单失败"))
    } finally {
      setAssigning("")
    }
  }

  const doRecommend = async (orderId: string) => {
    try {
      const r = await opcApi.recommend(orderId)
      setRecommend({
        orderId,
        candidates: r.candidates,
        reason: r.reason,
        source: r.source,
      })
    } catch (e) {
      message.error(errMsg(e, "推荐失败"))
    }
  }

  const orderCols = [
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
    { title: "标题", dataIndex: "title", ellipsis: true },
    { title: "店铺", dataIndex: "store_name", width: 150, ellipsis: true },
    { title: "设计师", dataIndex: "designer_name", width: 100,
      render: (v: string) => v || <Text type="secondary">未指派</Text> },
    { title: "金额", dataIndex: "order_commission", width: 110,
      align: "right" as const,
      render: (v: string) => `¥${v}` },
    { title: "状态", dataIndex: "state_label", width: 110,
      render: (v: string) => <Tag color="blue">{v}</Tag> },
  ]

  const renderDesignerOptions = () =>
    (board?.designers ?? []).map((d) => ({
      value: d.id,
      label: `${d.name}（${d.design_tags || "未标注"}）`,
    }))

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>撮合看板</Title>
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="订单总数" value={dash?.total_orders ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 14 }}>
                金额 ¥{dash?.total_amount ?? "0"}</Text>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="在制金额" value={dash?.active_amount ?? "0"}
              prefix="¥" valueStyle={{ color: token.colorPrimary }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="待结算" value={dash?.pending_settle_amount ?? "0"}
              prefix="¥" valueStyle={{ color: token.colorWarning }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="设计师 / 店铺"
              value={`${dash?.designer_count ?? 0} / ${dash?.store_count ?? 0}`} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={14}>
          <Card
            size="small"
            title="待派单"
            extra={<Text type="secondary">{board?.pending.length ?? 0} 单</Text>}
          >
            {board && board.pending.length > 0 ? (
              <>
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={board.pending}
                  columns={[
                    ...orderCols,
                    {
                      title: "操作",
                      width: 190,
                      render: (_: unknown, r: OpcOrder) => (
                        <Space size={4}>
                          <Select
                            size="small"
                            style={{ width: 110 }}
                            placeholder="选设计师"
                            loading={assigning === r.id}
                            options={renderDesignerOptions()}
                            onChange={(v: string) => void doAssign(r.id, v)}
                          />
                          <Tooltip title="推荐候选人">
                            <Button size="small" icon={<ThunderboltOutlined />}
                              onClick={() => void doRecommend(r.id)} />
                          </Tooltip>
                        </Space>
                      ),
                    },
                  ]}
                />
                {recommend && recommend.orderId === board.pending[0]?.id && (
                  <Card size="small" style={{ marginTop: 12 }}
                    title="候选人推荐"
                    extra={<Tag color={recommend.source === "llm" ? "purple" : "default"}>
                      {recommend.source === "llm" ? "大模型" : "本地规则"}
                    </Tag>}>
                    <Text type="secondary">{recommend.reason}</Text>
                    <Table
                      rowKey="designer_id"
                      size="small"
                      pagination={false}
                      style={{ marginTop: 8 }}
                      dataSource={recommend.candidates}
                      columns={[
                        { title: "设计师", dataIndex: "name", width: 110 },
                        { title: "相关度", dataIndex: "score", width: 90,
                          align: "right" as const,
                          render: (v: number) => `${Math.round(v * 100)}%` },
                        { title: "理由", dataIndex: "reason",
                          render: (v?: string) => v || <Text type="secondary">—</Text> },
                      ]}
                    />
                  </Card>
                )}
              </>
            ) : (
              <Empty description="没有待派单的订单" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        <Col span={10}>
          <Card size="small" title="订单漏斗"
            extra={<Text type="secondary">按状态统计</Text>}>
            <Table
              rowKey="state"
              size="small"
              pagination={false}
              dataSource={dash?.funnel ?? []}
              columns={[
                { title: "状态", dataIndex: "label", width: 110 },
                { title: "单数", dataIndex: "count", width: 70, align: "right" as const },
                { title: "金额", dataIndex: "amount", align: "right" as const,
                  render: (v: string) => `¥${v}` },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={8}>
          <Card size="small" title="在制订单"
            extra={<Text type="secondary">{board?.active.length ?? 0} 单</Text>}>
            <OrderList items={board?.active ?? []} nav={nav} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="待验收"
            extra={<Text type="secondary">{board?.pending_review.length ?? 0} 单</Text>}>
            <OrderList items={board?.pending_review ?? []} nav={nav} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="待结算"
            extra={<Text type="secondary">{board?.pending_settle.length ?? 0} 单</Text>}>
            <OrderList items={board?.pending_settle ?? []} nav={nav} />
          </Card>
        </Col>
      </Row>

      {dash && dash.designer_ranking.length > 0 && (
        <Card size="small" title="设计师接单排行" style={{ marginTop: 16 }}>
          <Table
            rowKey="name"
            size="small"
            pagination={false}
            dataSource={dash.designer_ranking}
            columns={[
              { title: "设计师", dataIndex: "name" },
              { title: "接单数", dataIndex: "count", width: 90, align: "right" as const },
              { title: "金额", dataIndex: "amount", align: "right" as const,
                render: (v: string) => `¥${v}` },
            ]}
          />
        </Card>
      )}
    </div>
  )
}

function OrderList({ items, nav }: { items: OpcOrder[]; nav: (p: string) => void }) {
  if (items.length === 0) {
    return <Empty description="暂无" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  return (
    <div>
      {items.slice(0, 8).map((o) => (
        <div key={o.id} style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "6px 0", borderBottom: "1px solid rgba(0,0,0,0.06)",
        }}>
          <span>
            <Button type="link" size="small" onClick={() => nav(`/opc/orders/${o.id}`)}
              style={{ padding: 0 }}>
              {o.order_sn}
            </Button>
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              {o.designer_name || o.store_name || o.title}
            </Text>
          </span>
          <Space size={4}>
            <Text style={{ fontSize: 12 }}>¥{o.order_commission}</Text>
            <ArrowRightOutlined style={{ fontSize: 10, opacity: 0.4 }} />
          </Space>
        </div>
      ))}
      {items.length > 8 && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          另有 {items.length - 8} 单…
        </Text>
      )}
    </div>
  )
}
