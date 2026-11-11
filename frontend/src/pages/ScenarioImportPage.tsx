import { useMemo, useState } from "react"
import {
  App as AntdApp,
  Button,
  Card,
  Empty,
  Input,
  Space,
  Table,
  Typography,
} from "antd"
import type { ColumnsType } from "antd/es/table"
import { useNavigate } from "react-router-dom"
import { batchCreateScenarios } from "../api/scenarios"
import { errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import type { ScenarioCreate } from "../types/api"

const TEMPLATE: ScenarioCreate[] = [
  {
    code: "fenqi-fee-dispute",
    title: "分期手续费争议",
    customer_persona:
      "你是李女士，28岁，白领。本月聚币分期账单里多了一笔50元手续费，你不记得开通过任何增值服务，情绪有些激动，怀疑被乱收费。你要求客服给出明确解释并退款，但若解释合理也愿意接受。",
    opening: "你好，我这个月账单里突然多了一笔50块的手续费，我根本没开过什么服务，这钱是怎么扣的？",
    knowledge_points: [
      "手续费产生规则：开通极速审核/延期还款等增值服务时收取",
      "查询入口：App-我的-账单-明细-点击该笔手续费",
      "退款条件：若确为系统误扣或未告知开通，可申请全额退款",
      "需核实用户是否主动操作、操作时间、是否有短信/推送告知",
    ],
    reference_answer:
      "1.安抚并询问手续费产生的具体时间；2.引导用户进入账单明细查看该笔手续费的关联服务；3.若为增值服务手续费，说明开通时间与告知记录；4.若确属误扣，提交退款工单并告知时效；5.全程不否认用户感受，先查后判。",
    difficulty: 3,
    max_turns: 6,
  },
  {
    code: "credit-recovery-consult",
    title: "额度恢复咨询",
    customer_persona:
      "你是王先生，40岁，个体户。刚还完上一笔聚币分期，想确认可用额度什么时候恢复，急着用钱进货。你有点着急，反复问'到底几点能恢复'，如果客服说不清楚会不满。",
    opening: "我还完款了，额度多久能恢复？我现在急着用，到底几点能到账？",
    knowledge_points: [
      "额度恢复规则：还款成功后T+1日内恢复，具体以银行清算为准",
      "查询入口：App-我的-额度-还款记录",
      "加急说明：额度恢复为系统自动，无人工加急通道",
      "话术：不承诺具体时点，引导用户留意App通知",
    ],
    reference_answer:
      "1.安抚焦急情绪，确认还款已成功；2.说明T+1恢复规则与银行清算依赖；3.引导查看额度页还款记录；4.明确无人工加急通道，避免虚假承诺；5.建议关注App额度恢复推送。",
    difficulty: 2,
    max_turns: 5,
  },
]

export default function ScenarioImportPage() {
  const { user } = useAuth()
  const nav = useNavigate()
  const { message } = AntdApp.useApp()

  const [text, setText] = useState<string>(() => JSON.stringify(TEMPLATE, null, 2))
  const [parsed, setParsed] = useState<ScenarioCreate[] | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const columns = useMemo<ColumnsType<ScenarioCreate>>(
    () => [
      { title: "code", dataIndex: "code", key: "code" },
      { title: "title", dataIndex: "title", key: "title", ellipsis: true },
      { title: "difficulty", dataIndex: "difficulty", key: "difficulty", width: 90 },
      {
        title: "知识点数",
        key: "kp",
        width: 90,
        render: (_, r) => r.knowledge_points?.length ?? 0,
      },
      { title: "max_turns", dataIndex: "max_turns", key: "max_turns", width: 100 },
    ],
    [],
  )

  const canImport = (parsed?.length ?? 0) > 0

  if (user?.role !== "teacher" && user?.role !== "admin") {
    return (
      <Empty description="仅讲师可访问" style={{ marginTop: 80 }}>
        <Button type="primary" onClick={() => nav("/scenarios")}>
          返回剧本库
        </Button>
      </Empty>
    )
  }

  const handleParse = () => {
    try {
      const data = JSON.parse(text)
      if (!Array.isArray(data)) {
        throw new Error("顶层必须为数组")
      }
      setParsed(data as ScenarioCreate[])
      message.success(`解析成功，共 ${data.length} 个剧本`)
    } catch (e) {
      setParsed(null)
      message.error(`JSON 格式错误: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleImport = async () => {
    if (!parsed || parsed.length === 0) return
    setSubmitting(true)
    try {
      const res = await batchCreateScenarios({ scenarios: parsed })
      message.success(`导入完成: 新增 ${res.created} 个，跳过 ${res.skipped} 个`)
      nav("/scenarios")
    } catch (e) {
      message.error(errMsg(e, "导入失败"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card title="批量导入剧本" styles={{ body: { display: "flex", flexDirection: "column", gap: 16 } }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        粘贴 JSON 数组，每个剧本需包含 code/title/customer_persona/opening/knowledge_points(数组)/reference_answer/difficulty/max_turns。code 重复将自动跳过。
      </Typography.Paragraph>

      <Input.TextArea
        value={text}
        onChange={(e) => setText(e.target.value)}
        autoSize={{ minRows: 12 }}
        style={{ fontFamily: "monospace" }}
      />

      <Space>
        <Button onClick={handleParse}>解析预览</Button>
        <Button type="primary" disabled={!canImport} loading={submitting} onClick={handleImport}>
          确认导入
        </Button>
      </Space>

      {parsed && (
        <div>
          <Typography.Text type="secondary">共 {parsed.length} 个剧本</Typography.Text>
          <Table
            size="small"
            rowKey={(r) => r.code}
            columns={columns}
            dataSource={parsed}
            pagination={false}
            style={{ marginTop: 8 }}
          />
        </div>
      )}
    </Card>
  )
}
