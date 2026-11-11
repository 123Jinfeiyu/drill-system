import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Descriptions, Row, Segmented, Space, Statistic,
  Table, Tag, Typography, message,
} from "antd"
import {
  ArrowDownOutlined, CloudDownloadOutlined, LinkOutlined,
  ReloadOutlined, WarningOutlined,
} from "@ant-design/icons"
import { settleApi, errMsg } from "../api/settle"
import type {
  SlBridgeDesignerItem, SlBridgeImportResult, SlBridgeOrderItem, SlBridgeStatus,
} from "../types/settle"

const { Title, Text, Paragraph } = Typography

/**
 * 与总系统（上游）互通。
 *
 * 这一页是「两系统互通」的操作入口，做三件事：
 * 1. 看互通状态（上游配没配、连不连得上）
 * 2. 预览上游数据（先看清楚能导什么，再决定导不导）
 * 3. 执行导入（幂等 —— 重复点不会产生第二条）
 *
 * **只读、单向、不回写。** 上游是生产系统，本地结算系统只是它的下游视图。
 * 导入过来的数据进了本地台账，之后的流程管理、审核、结算全在本地走。
 *
 * 刻意做成「先预览再导入」两步 —— 一键直接导的话，
 * 派单员看到的是一堆没头绪的表格，不会知道哪条能导、哪条不能。
 */
export default function SettleBridgePage() {
  const [status, setStatus] = useState<SlBridgeStatus | null>(null)
  const [kind, setKind] = useState<"designers" | "orders">("designers")
  const [preview, setPreview] = useState<
    SlBridgeDesignerItem[] | SlBridgeOrderItem[] | null
  >(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [onlyValid, setOnlyValid] = useState(true)
  const [result, setResult] = useState<SlBridgeImportResult | null>(null)

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await settleApi.bridgeStatus())
    } catch (e) {
      message.error(errMsg(e, "互通状态加载失败"))
    }
  }, [])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  // 切换数据类型时清掉旧的预览 —— 设计师的列和订单的列完全不一样，
  // 混着显示会让人以为看错表了
  const switchKind = (v: "designers" | "orders") => {
    setKind(v)
    setPreview(null)
    setResult(null)
  }

  // 只负责拉数据，不碰结果区 —— 导入完要刷新预览，
  // 如果这里顺手把 result 清了，刚导入出来的结果就凭空消失了
  const fetchPreview = useCallback(async () => {
    const d = await settleApi.bridgePreview(kind, 50)
    setPreview(d.items)
    setTotal(d.total)
    if (d.items.length === 0) {
      message.info("上游没有可预览的数据")
    }
  }, [kind])

  const doPreview = async () => {
    setLoading(true)
    setResult(null)
    try {
      await fetchPreview()
    } catch (e) {
      message.error(errMsg(e, "预览失败"))
    } finally {
      setLoading(false)
    }
  }

  const doImport = async () => {
    setImporting(true)
    try {
      const r = await settleApi.bridgeImport({
        kind,
        limit: 50,
        only_valid: onlyValid,
      })
      setResult(r)
      if (r.created_count > 0) {
        message.success(`导入完成：新增 ${r.created_count} 条，跳过 ${r.skipped_count} 条`)
      } else {
        message.info(`没有新增记录（跳过 ${r.skipped_count} 条）`)
      }
      // 导完刷新预览，但**不能清掉 result** —— 那是刚导入出来的结果
      await fetchPreview()
    } catch (e) {
      message.error(errMsg(e, "导入失败"))
    } finally {
      setImporting(false)
    }
  }

  // status 还没加载完时是 null —— 这时候不算「未配置」，
  // 只是「还不知道」，按钮先禁着，等状态回来再决定
  const notConfigured = status !== null && !status.configured
  const notReady = status === null

  return (
    <div>
      <Space align="center" style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>总系统互通</Title>
        <Tag color="cyan" icon={<LinkOutlined />}>只读 · 单向导入 · 不回写</Tag>
      </Space>

      {/* ---------------- 状态卡 ---------------- */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions
          size="small"
          column={{ xs: 1, sm: 2, md: 4 }}
          title={
            <Space>
              <span>互通状态</span>
              <Button
                size="small" type="text" icon={<ReloadOutlined />}
                onClick={() => void loadStatus()}
              >
                重测
              </Button>
            </Space>
          }
        >
          <Descriptions.Item label="上游凭据">
            {status?.configured
              ? <Tag color="green">已配置</Tag>
              : <Tag color="red">未配置</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="连通性">
            {status?.reachable === undefined
              ? <Text type="secondary">—</Text>
              : status.reachable
                ? <Tag color="green">可连接</Tag>
                : <Tag color="orange">连不上</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="上游设计师">
            {status?.designer_total ?? "—"}
          </Descriptions.Item>
          <Descriptions.Item label="互通方向">
            <Tag>上游 → 本地</Tag>
          </Descriptions.Item>
        </Descriptions>

        {notConfigured && (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="尚未配置上游账号"
            description={
              <div>
                <Paragraph style={{ marginBottom: 4 }}>
                  上游账号密码只从环境变量读，不落数据库、不进日志、不返回前端。
                </Paragraph>
                <Paragraph style={{ marginBottom: 0 }}>
                  请设置环境变量 <Text code>TRCIPG_USERNAME</Text> 与{" "}
                  <Text code>TRCIPG_PASSWORD</Text> 后重启后端服务。
                </Paragraph>
              </div>
            }
          />
        )}
        {status?.reachable === false && status?.error && (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            message="上游暂时连不上"
            description={status.error}
          />
        )}
      </Card>

      {/* ---------------- 操作区 ---------------- */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Segmented
            value={kind}
            onChange={(v) => switchKind(v as "designers" | "orders")}
            options={[
              { label: "设计师档案", value: "designers" },
              { label: "订单", value: "orders" },
            ]}
          />
          <Space wrap>
            <Button
              icon={<ArrowDownOutlined />}
              onClick={() => void doPreview()}
              loading={loading}
              disabled={notConfigured || notReady}
            >
              预览上游数据
            </Button>
            <Button
              type="primary"
              icon={<CloudDownloadOutlined />}
              onClick={() => void doImport()}
              loading={importing}
              disabled={notConfigured || notReady || !preview || preview.length === 0}
            >
              导入到本地
            </Button>
            <Text type="secondary">
              {onlyValid
                ? "只导入没有问题的记录"
                : "有问题的记录也会导入，并在结果里标出问题"}
            </Text>
            <Button
              type="link"
              size="small"
              onClick={() => setOnlyValid((v) => !v)}
            >
              切换为{onlyValid ? "全部导入" : "仅导入合格记录"}
            </Button>
          </Space>
          {preview && (
            <Text type="secondary">
              上游共 {total} 条，本次预览 {preview.length} 条。
              导入按上游 ID 去重，重复导入不会产生第二条记录。
            </Text>
          )}
        </Space>
      </Card>

      {/* ---------------- 导入结果 ---------------- */}
      {result && (
        <Card size="small" title="本次导入结果" style={{ marginBottom: 16 }}>
          <Row gutter={16} style={{ marginBottom: 12 }}>
            <Col span={6}>
              <Statistic title="新增" value={result.created_count} valueStyle={{ color: "#52c41a" }} />
            </Col>
            <Col span={6}>
              <Statistic title="跳过" value={result.skipped_count} valueStyle={{ color: "#faad14" }} />
            </Col>
          </Row>
          {result.skipped.length > 0 && (
            <>
              <Text strong>跳过明细（每条都给了原因）：</Text>
              <Table
                size="small"
                rowKey="upstream_id"
                pagination={false}
                style={{ marginTop: 8 }}
                dataSource={result.skipped}
                columns={[
                  { title: "上游 ID", dataIndex: "upstream_id", width: 100 },
                  {
                    title: "对象",
                    width: 160,
                    render: (_: unknown, r: { name?: string; order_no?: string }) =>
                      r.name || r.order_no || "—",
                  },
                  { title: "跳过原因", dataIndex: "reason" },
                ]}
              />
            </>
          )}
        </Card>
      )}

      {/* ---------------- 预览表 ---------------- */}
      {kind === "designers" && preview && (
        <Card size="small" title={`设计师预览（${preview.length} 条）`}>
          <Table
            size="small"
            rowKey="upstream_id"
            loading={loading}
            dataSource={preview as SlBridgeDesignerItem[]}
            scroll={{ x: 900 }}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            columns={[
              { title: "上游 ID", dataIndex: "upstream_id", width: 90 },
              { title: "姓名", dataIndex: "name", width: 100 },
              { title: "花名", dataIndex: "nickname", width: 90 },
              { title: "手机号", dataIndex: "phone", width: 130 },
              { title: "收款账号", dataIndex: "alipay_account", width: 180 },
              { title: "档次", dataIndex: "production_level", width: 100 },
              {
                title: "可否导入",
                width: 80,
                render: (_: unknown, r: SlBridgeDesignerItem) =>
                  r.importable
                    ? <Tag color="green">可导</Tag>
                    : <Tag color="orange">有问题</Tag>,
              },
              {
                title: "问题",
                render: (_: unknown, r: SlBridgeDesignerItem) =>
                  r.issues.length === 0
                    ? <Text type="secondary">—</Text>
                    : (
                      <ul style={{ margin: 0, paddingLeft: 16 }}>
                        {r.issues.map((i) => <li key={i}>{i}</li>)}
                      </ul>
                    ),
              },
            ]}
          />
          <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            导入时「所属战区」与「所属 HR」一律留空 —— 课件明确要求这两栏不填内容，
            上游有值也不会带过来。
          </Paragraph>
        </Card>
      )}

      {kind === "orders" && preview && (
        <Card size="small" title={`订单预览（${preview.length} 条）`}>
          <Table
            size="small"
            rowKey="upstream_id"
            loading={loading}
            dataSource={preview as SlBridgeOrderItem[]}
            scroll={{ x: 1000 }}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            columns={[
              { title: "上游 ID", dataIndex: "upstream_id", width: 90 },
              { title: "订单编号", dataIndex: "order_no", width: 150 },
              { title: "设计师", dataIndex: "designer_name", width: 100 },
              { title: "项目金额", dataIndex: "order_amount", width: 110, align: "right" },
              { title: "设计师佣金", dataIndex: "commission", width: 110, align: "right" },
              {
                title: "反推比例",
                dataIndex: "commission_rate",
                width: 90,
                align: "right",
                render: (v: string) => (
                  <span>{Number(v) > 0 ? `${(Number(v) * 100).toFixed(2)}%` : "—"}</span>
                ),
              },
              {
                title: "上游状态",
                width: 130,
                render: (_: unknown, r: SlBridgeOrderItem) => (
                  <Space direction="vertical" size={0}>
                    <Tag>{r.upstream_status_label}</Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      → {r.local_state_label}
                    </Text>
                  </Space>
                ),
              },
              {
                title: "可否导入",
                width: 80,
                render: (_: unknown, r: SlBridgeOrderItem) =>
                  r.importable
                    ? <Tag color="green">可导</Tag>
                    : <Tag color="orange">有问题</Tag>,
              },
              {
                title: "问题",
                render: (_: unknown, r: SlBridgeOrderItem) =>
                  r.issues.length === 0
                    ? <Text type="secondary">—</Text>
                    : (
                      <ul style={{ margin: 0, paddingLeft: 16 }}>
                        {r.issues.map((i) => <li key={i}>{i}</li>)}
                      </ul>
                    ),
              },
            ]}
          />
          <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            佣金比例是从金额反推出来的（上游只给金额不给比例）。
            反推值越界说明这笔单是旧规则下产生的，导入时会标出来，请人工核对后再结算。
          </Paragraph>
        </Card>
      )}
    </div>
  )
}
