import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Descriptions, Divider, Form, Input, List, Modal, Row,
  Select, Space, Steps, Tag, Timeline, Typography, message,
} from "antd"
import {
  ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined, FileDoneOutlined,
} from "@ant-design/icons"
import { useNavigate, useParams } from "react-router-dom"
import { settleApi, errMsg, issuesText } from "../api/settle"
import { LOG_KIND_LABEL, STATE_COLOR, money, percent } from "../utils/settle"
import type { SlDesigner, SlMeta, SlOrderDetail } from "../types/settle"

const { Title, Text, Paragraph } = Typography

/** 主线节点在 Steps 里显示的顺序。 */
const STEPS = ["pending_design", "drafting", "finalizing", "pending_audit", "settleable", "settled"]

/**
 * 订单流程管理（模块四）。
 *
 * 课件模块四有两个「节点」，界面上就是这一页的两个动作区：
 * - **节点一（初稿完成 → 终稿制作中）**：必须先填**订单编号**
 * - **节点二（终稿完成 → 待审核）**：必须上传**两类截图**
 *   （终稿通过聊天记录截图 + 交付文件截图）
 *
 * 这两道门禁在**后端**（settle_ledger.check_transition）里，
 * 前端只负责把「缺什么」提前显示出来，并把后端拒绝的原因原样透出。
 */
export default function SettleOrderDetailPage() {
  const { id = "" } = useParams()
  const nav = useNavigate()
  const [detail, setDetail] = useState<SlOrderDetail | null>(null)
  const [designers, setDesigners] = useState<SlDesigner[]>([])
  const [meta, setMeta] = useState<SlMeta | null>(null)
  const [busy, setBusy] = useState(false)
  const [auditOpen, setAuditOpen] = useState(false)
  const [auditRemark, setAuditRemark] = useState("")
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignId, setAssignId] = useState<string>("")
  const [orderNo, setOrderNo] = useState("")
  const [chatShot, setChatShot] = useState("")
  const [fileShot, setFileShot] = useState("")

  const load = useCallback(async () => {
    try {
      const [d, ds, m] = await Promise.all([
        settleApi.getOrder(id),
        settleApi.listDesigners(),
        settleApi.meta(),
      ])
      setDetail(d)
      setDesigners(ds)
      setMeta(m)
      setOrderNo(d.order.order_no)
      setChatShot(d.order.chat_screenshot)
      setFileShot(d.order.file_screenshot)
    } catch (e) {
      message.error(errMsg(e, "订单加载失败"))
    } finally {
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const order = detail?.order

  /** 统一的状态流转调用，失败时把后端逐条原因摆出来。 */
  const doTransition = async (
    toState: string,
    extra: Record<string, unknown> = {},
  ) => {
    setBusy(true)
    try {
      await settleApi.transition(id, toState, extra)
      message.success("已流转")
      await load()
    } catch (e) {
      message.error(issuesText(e) || errMsg(e, "流转失败"))
    } finally {
      setBusy(false)
    }
  }

  const doAudit = async (action: "approve" | "reject") => {
    setBusy(true)
    try {
      await settleApi.audit(id, action, auditRemark)
      message.success(action === "approve" ? "审核通过，订单已可结算" : "已驳回")
      setAuditOpen(false)
      setAuditRemark("")
      await load()
    } catch (e) {
      message.error(issuesText(e) || errMsg(e, "审核失败"))
    } finally {
      setBusy(false)
    }
  }

  const doAssign = async () => {
    if (!assignId) {
      message.warning("请先选择承接的设计师")
      return
    }
    setAssignOpen(false)
    await doTransition("drafting", { designer_id: assignId })
  }

  const stepIndex = order ? STEPS.indexOf(order.state) : -1
  const designerOptions = designers.map((d) => ({
    value: d.id,
    label: `${d.name}（${d.nickname}）`,
    disabled: d.status !== "active",
  }))

  /** 节点二的材料是否齐了 —— 前端提前提示，后端仍是唯一裁判。 */
  const chatMissing = !chatShot.trim()
  const fileMissing = !fileShot.trim()
  const noMissing = !orderNo.trim()

  return (
    <div>
      <Button type="link" icon={<ArrowLeftOutlined />} style={{ padding: 0 }}
        onClick={() => nav("/settle/orders")}>
        ← 返回订单列表
      </Button>

      {order && (
        <>
          <Title level={4} style={{ marginTop: 8, marginBottom: 16 }}>
            订单 {order.order_no || <Text type="secondary">（未填写编号）</Text>}
            <Tag color={STATE_COLOR[order.state]} style={{ marginLeft: 12 }}>
              {order.state_label}
            </Tag>
          </Title>

          {detail.exceptions.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={`检测到 ${detail.exceptions.length} 项异常`}
              description={
                <List
                  size="small"
                  dataSource={detail.exceptions}
                  renderItem={(it) => (
                    <List.Item>
                      <Space direction="vertical" size={0}>
                        <Text strong>{it.message}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          处理方案：{it.action}
                        </Text>
                      </Space>
                    </List.Item>
                  )}
                />
              }
            />
          )}

          <Card size="small" style={{ marginBottom: 16 }}>
            <Steps
              size="small"
              current={stepIndex < 0 ? 0 : stepIndex}
              items={STEPS.map((s) => ({
                title: meta?.states.find((x) => x.value === s)?.label ?? s,
                status:
                  order.state === "rejected" && s === "pending_audit"
                    ? "error"
                    : undefined,
              }))}
            />
            {order.state === "rejected" && (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 12 }}
                message={`审核驳回：${order.audit_remark || "未填写原因"}`}
                description="订单已退回终稿制作中，设计师改稿后可再次提交终稿。"
              />
            )}
          </Card>

          <Row gutter={[16, 16]}>
            <Col span={16}>
              <Card size="small" title="订单信息">
                <Descriptions size="small" column={3} bordered>
                  <Descriptions.Item label="客户 ID">{order.customer_id}</Descriptions.Item>
                  <Descriptions.Item label="战区">{order.war_zone || "—"}</Descriptions.Item>
                  <Descriptions.Item label="客服">{order.customer_service || "—"}</Descriptions.Item>
                  <Descriptions.Item label="设计师">
                    {order.designer_name || <Text type="warning">待派单</Text>}
                  </Descriptions.Item>
                  <Descriptions.Item label="订单类型">{order.order_type_label}</Descriptions.Item>
                  <Descriptions.Item label="服务类型">{order.service_type || "—"}</Descriptions.Item>
                  <Descriptions.Item label="项目金额">¥{money(order.order_amount)}</Descriptions.Item>
                  <Descriptions.Item label="佣金比例">{percent(order.commission_rate)}</Descriptions.Item>
                  <Descriptions.Item label="设计师佣金">
                    <Text strong>¥{money(order.designer_commission)}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="接单日期">{order.order_date || "—"}</Descriptions.Item>
                  <Descriptions.Item label="交期">{order.deliver_date || "—"}</Descriptions.Item>
                  <Descriptions.Item label="审核状态">
                    {order.audit_status === "approved" ? "已通过"
                      : order.audit_status === "rejected" ? "已驳回" : "待审核"}
                  </Descriptions.Item>
                  <Descriptions.Item label="需求" span={3}>
                    <Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}>
                      {order.requirement || "—"}
                    </Paragraph>
                  </Descriptions.Item>
                  {order.note && (
                    <Descriptions.Item label="备注" span={3}>{order.note}</Descriptions.Item>
                  )}
                </Descriptions>
              </Card>

              <Card size="small" title="材料与操作" style={{ marginTop: 16 }}>
                {order.state === "pending_design" && (
                  <>
                    <Alert
                      type="info" showIcon style={{ marginBottom: 12 }}
                      message="派单：指定承接的设计师后开工"
                      description="「设计待定」的整个意义就是还没定人。派单必须选一位在职设计师。"
                    />
                    <Button type="primary" icon={<FileDoneOutlined />}
                      onClick={() => { setAssignId(order.designer_id ?? ""); setAssignOpen(true) }}>
                      派单
                    </Button>
                  </>
                )}

                {order.state === "drafting" && (
                  <>
                    <Alert
                      type="info" showIcon style={{ marginBottom: 12 }}
                      message="节点一：初稿完成 → 终稿制作中"
                      description="进入下一步前必须填写订单编号。编号向客服获取，填完才能继续。"
                    />
                    <Form layout="vertical">
                      <Form.Item label="订单编号" required>
                        <Input
                          value={orderNo}
                          onChange={(e) => setOrderNo(e.target.value)}
                          placeholder="向客服获取的专属订单编号"
                          style={{ maxWidth: 360 }}
                          status={noMissing ? undefined : "success"}
                        />
                      </Form.Item>
                    </Form>
                    <Button
                      type="primary"
                      loading={busy}
                      onClick={() => void doTransition("finalizing", { order_no: orderNo })}
                    >
                      提交终稿阶段
                    </Button>
                  </>
                )}

                {order.state === "finalizing" && (
                  <>
                    <Alert
                      type="info" showIcon style={{ marginBottom: 12 }}
                      message="节点二：终稿完成 → 待审核"
                      description="交付验收必须上传两类截图：终稿通过的聊天记录截图，以及交付文件截图（需含群名、成员、交付画面）。"
                    />
                    <Form layout="vertical">
                      <Row gutter={12}>
                        <Col span={12}>
                          <Form.Item label="终稿通过聊天记录截图" required>
                            <Input
                              value={chatShot}
                              onChange={(e) => setChatShot(e.target.value)}
                              placeholder="截图文件路径 / 云链接"
                              status={chatMissing ? undefined : "success"}
                            />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="交付文件截图" required>
                            <Input
                              value={fileShot}
                              onChange={(e) => setFileShot(e.target.value)}
                              placeholder="截图文件路径 / 云链接"
                              status={fileMissing ? undefined : "success"}
                            />
                          </Form.Item>
                        </Col>
                      </Row>
                    </Form>
                    <Button
                      type="primary"
                      loading={busy}
                      onClick={() => void doTransition("pending_audit", {
                        chat_screenshot: chatShot,
                        file_screenshot: fileShot,
                      })}
                    >
                      提交终稿待验收
                    </Button>
                  </>
                )}

                {order.state === "pending_audit" && (
                  <>
                    <Alert
                      type="warning" showIcon style={{ marginBottom: 12 }}
                      message="待审核：核对两类截图与需求，通过后订单进入可结算"
                    />
                    <Space>
                      <Button type="primary" icon={<CheckCircleOutlined />}
                        onClick={() => setAuditOpen(true)}>
                        审核通过
                      </Button>
                      <Button danger icon={<CloseCircleOutlined />}
                        onClick={() => setAuditOpen(true)}>
                        驳回
                      </Button>
                    </Space>
                  </>
                )}

                {order.state === "settleable" && (
                  <Alert
                    type="success" showIcon
                    message="已可结算：等待设计师在每月 8-9 号窗口内自行发起「一键结算」"
                    description="结算必须由设计师主动触发，派单员不能代为发起。7 号前记得提醒设计师。"
                  />
                )}

                {order.state === "settling" && (
                  <Alert
                    type="info" showIcon
                    message="结算中：设计师已发起结算，等待 15 号统一打款"
                    description="在「结算管理」页标记打款并填流水号。"
                  />
                )}

                {order.state === "settled" && (
                  <Alert type="success" showIcon message="已结算：款项已发放" />
                )}

                {order.state === "rejected" && (
                  <>
                    <Alert
                      type="error" showIcon style={{ marginBottom: 12 }}
                      message={`驳回原因：${order.audit_remark || "未填写"}`}
                    />
                    <Button type="primary" loading={busy}
                      onClick={() => void doTransition("finalizing", {
                        chat_screenshot: chatShot,
                        file_screenshot: fileShot,
                      })}>
                      改稿后重新提交
                    </Button>
                  </>
                )}

                {order.state === "canceled" && <Alert type="info" showIcon message="订单已取消" />}

                <Divider style={{ margin: "16px 0" }} />
                <Space wrap>
                  <Button
                    onClick={() => void doTransition("canceled", { detail: "派单员取消订单" })}
                    disabled={!detail.deletable}
                    danger
                  >
                    取消订单
                  </Button>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {detail.delete_reason}
                  </Text>
                </Space>
              </Card>
            </Col>

            <Col span={8}>
              <Card size="small" title="结算记录">
                {detail.settlements.length === 0 ? (
                  <Text type="secondary">还没有结算记录</Text>
                ) : (
                  <List
                    size="small"
                    dataSource={detail.settlements}
                    renderItem={(s) => (
                      <List.Item>
                        <List.Item.Meta
                          title={`¥${money(s.commission)}`}
                          description={`${s.period} · ${s.status === "paid" ? "已打款" : s.status === "invalid" ? "已失效" : "待打款"}${s.flow_no ? ` · 流水号 ${s.flow_no}` : ""}`}
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Card>

              <Card size="small" title="操作留痕" style={{ marginTop: 16 }}>
                {detail.logs.length === 0 ? (
                  <Text type="secondary">暂无记录</Text>
                ) : (
                  <Timeline
                    items={detail.logs.map((lg) => ({
                      color: lg.kind === "audit" ? "red" : "blue",
                      children: (
                        <>
                          <Text strong style={{ fontSize: 13 }}>
                            {LOG_KIND_LABEL[lg.kind] ?? lg.kind}
                            {lg.actor ? ` · ${lg.actor}` : ""}
                          </Text>
                          <div>
                            <Text style={{ fontSize: 12 }}>{lg.detail}</Text>
                          </div>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {lg.created_at?.replace("T", " ")}
                          </Text>
                        </>
                      ),
                    }))}
                  />
                )}
              </Card>
            </Col>
          </Row>
        </>
      )}

      <Modal title="派单：选择承接设计师" open={assignOpen}
        onCancel={() => setAssignOpen(false)} onOk={() => void doAssign()} okText="派单">
        <Select
          style={{ width: "100%" }}
          placeholder="选择设计师"
          value={assignId || undefined}
          options={designerOptions}
          onChange={(v: string) => setAssignId(v)}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          停用的设计师不可选。派单后订单进入「初稿制作中」。
        </Text>
      </Modal>

      <Modal title="审核" open={auditOpen} onCancel={() => setAuditOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setAuditOpen(false)}>取消</Button>,
          <Button key="reject" danger loading={busy}
            onClick={() => void doAudit("reject")}>驳回</Button>,
          <Button key="approve" type="primary" loading={busy}
            onClick={() => void doAudit("approve")}>通过</Button>,
        ]}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          驳回会退回「终稿制作中」让设计师改稿；通过则订单进入「可结算」。
          驳回时建议写明原因。
        </Text>
        <Input.TextArea
          rows={3}
          style={{ marginTop: 12 }}
          placeholder="审核备注（驳回时建议必填）"
          value={auditRemark}
          onChange={(e) => setAuditRemark(e.target.value)}
        />
      </Modal>
    </div>
  )
}
