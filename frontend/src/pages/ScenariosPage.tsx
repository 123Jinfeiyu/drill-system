import { useEffect, useState } from "react"
import {
  App as AntdApp,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd"
import { useNavigate } from "react-router-dom"
import { scenariosApi, sessionsApi } from "../api"
import { errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import type { Scenario } from "../types/api"

const DIFFICULTY_LABEL: Record<number, string> = { 1: "入门", 2: "简单", 3: "中等", 4: "较难", 5: "困难" }
const DIFFICULTY_COLOR = ["", "green", "blue", "gold", "orange", "red"]

const DIFFICULTY_OPTIONS = [1, 2, 3, 4, 5].map((d) => ({
  value: d,
  label: `${d} - ${DIFFICULTY_LABEL[d]}`,
}))

interface ScenarioFormValues {
  code: string
  title: string
  difficulty: number
  max_turns: number
  customer_persona: string
  opening: string
  knowledge_points?: string[]
  reference_answer?: string
}

export default function ScenariosPage() {
  const { user } = useAuth()
  const nav = useNavigate()
  const { message } = AntdApp.useApp()

  const isManager = user?.role === "teacher" || user?.role === "admin"

  const [list, setList] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState<string | null>(null)

  // 新增 / 编辑
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Scenario | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<ScenarioFormValues>()

  const reload = () => {
    setLoading(true)
    scenariosApi
      .listScenarios()
      .then(setList)
      .catch((e) => message.error(errMsg(e, "加载剧本失败")))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startDrill = async (scenario: Scenario) => {
    setStarting(scenario.id)
    try {
      const session = await sessionsApi.createSession({ scenario_id: scenario.id })
      message.success("已创建演练会话")
      nav(`/drill/${session.id}`)
    } catch (e) {
      message.error(errMsg(e, "创建会话失败"))
    } finally {
      setStarting(null)
    }
  }

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ difficulty: 3, max_turns: 6, knowledge_points: [], reference_answer: "" })
    setModalOpen(true)
  }

  const openEdit = (s: Scenario) => {
    setEditing(s)
    form.setFieldsValue({
      code: s.code,
      title: s.title,
      difficulty: s.difficulty,
      max_turns: s.max_turns,
      customer_persona: s.customer_persona,
      opening: s.opening,
      knowledge_points: s.knowledge_points ?? [],
      reference_answer: s.reference_answer ?? "",
    })
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    form.resetFields()
  }

  const handleSave = async (values: ScenarioFormValues) => {
    setSaving(true)
    try {
      const payload = {
        code: values.code.trim(),
        title: values.title.trim(),
        difficulty: values.difficulty,
        max_turns: values.max_turns,
        customer_persona: values.customer_persona,
        opening: values.opening,
        knowledge_points: values.knowledge_points ?? [],
        reference_answer: values.reference_answer ?? "",
      }
      if (editing) {
        const updated = await scenariosApi.updateScenario(editing.id, payload)
        message.success("剧本已保存")
        setList((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
      } else {
        const created = await scenariosApi.createScenario(payload)
        message.success("剧本已新增")
        setList((prev) => [created, ...prev])
      }
      setModalOpen(false)
      form.resetFields()
    } catch (e) {
      message.error(errMsg(e, editing ? "保存失败" : "新增失败"))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (scenario: Scenario) => {
    try {
      await scenariosApi.deleteScenario(scenario.id)
      message.success("剧本已删除")
      setList((prev) => prev.filter((it) => it.id !== scenario.id))
    } catch (e) {
      message.error(errMsg(e, "删除失败"))
    }
  }

  const managerActionRow = (s: Scenario) => (
    <Space.Compact block>
      <Button block onClick={() => openEdit(s)}>
        编辑
      </Button>
      <Popconfirm
        title="确认删除该剧本？"
        description="演练历史与评分会保留，被使用的剧本无法删除。"
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        onConfirm={() => handleDelete(s)}
      >
        <Button block danger>
          删除
        </Button>
      </Popconfirm>
    </Space.Compact>
  )

  const renderCardActions = (s: Scenario) => {
    if (isManager) {
      return managerActionRow(s)
    }
    return (
      <Button
        type="primary"
        block
        loading={starting === s.id}
        disabled={user?.role !== "student"}
        onClick={() => startDrill(s)}
      >
        {user?.role === "student" ? "开始演练" : "仅学员可演练"}
      </Button>
    )
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          剧本库
          <Typography.Text type="secondary" style={{ fontSize: 14, marginLeft: 8 }}>
            共 {list.length} 个剧本
          </Typography.Text>
        </Typography.Title>
        {isManager && (
          <Space>
            <Button type="primary" onClick={openCreate}>
              新增剧本
            </Button>
            <Button onClick={() => nav("/scenarios/import")}>批量导入</Button>
          </Space>
        )}
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 80 }}>
          <Spin size="large" />
        </div>
      ) : !list.length ? (
        <Empty
          description="暂无剧本"
          style={{ marginTop: 80 }}
        >
          {isManager && (
            <Space>
              <Button type="primary" onClick={openCreate}>
                新增剧本
              </Button>
              <Button onClick={() => nav("/scenarios/import")}>批量导入</Button>
            </Space>
          )}
        </Empty>
      ) : (
        <Row gutter={[16, 16]}>
          {list.map((s) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={s.id}>
              <Card
                title={
                  <Tooltip title={s.title}>
                    <Typography.Text ellipsis style={{ maxWidth: 200 }}>
                      {s.title}
                    </Typography.Text>
                  </Tooltip>
                }
                extra={<Tag>{s.code}</Tag>}
                styles={{ body: { display: "flex", flexDirection: "column", gap: 12, minHeight: 200 } }}
              >
                <Space wrap>
                  <Tag color={DIFFICULTY_COLOR[s.difficulty]}>
                    难度 {DIFFICULTY_LABEL[s.difficulty] ?? s.difficulty}
                  </Tag>
                  <Tag color="cyan">最多 {s.max_turns} 轮</Tag>
                  <Tag color="purple">{s.knowledge_points.length} 个知识点</Tag>
                </Space>
                <Typography.Paragraph
                  type="secondary"
                  ellipsis={{ rows: 3 }}
                  style={{ fontSize: 13, marginBottom: 0, flex: 1 }}
                >
                  {s.customer_persona}
                </Typography.Paragraph>
                {renderCardActions(s)}
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title={editing ? "编辑剧本" : "新增剧本"}
        open={modalOpen}
        onCancel={closeModal}
        width={780}
        footer={[
          <Button key="cancel" onClick={closeModal}>
            取消
          </Button>,
          <Button key="ok" type="primary" loading={saving} onClick={() => form.submit()}>
            {editing ? "保存" : "新增"}
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" onFinish={handleSave} style={{ marginTop: 8 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="code"
                label="剧本代码（code）"
                rules={[{ required: true, message: "请输入剧本代码" }, { max: 64, message: "不超过 64 字符" }]}
              >
                <Input placeholder="如：fenqi-fee-dispute" maxLength={64} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="title"
                label="剧本标题"
                rules={[{ required: true, message: "请输入剧本标题" }, { max: 128, message: "不超过 128 字" }]}
              >
                <Input placeholder="如：分期手续费争议" maxLength={128} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="difficulty" label="难度" rules={[{ required: true }]}>
                <Select options={DIFFICULTY_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="max_turns" label="最大轮数" rules={[{ required: true }]}>
                <InputNumber min={1} max={20} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="customer_persona"
            label="客户人设（AI 扮演，含安全约束）"
            rules={[{ required: true, message: "请输入客户人设" }]}
          >
            <Input.TextArea autoSize={{ minRows: 4 }} placeholder="你是谁、年龄职业、诉求、情绪与配合度等" />
          </Form.Item>
          <Form.Item name="opening" label="开场白" rules={[{ required: true, message: "请输入开场白" }]}>
            <Input.TextArea autoSize={{ minRows: 2 }} placeholder="客户开场第一句话" />
          </Form.Item>
          <Form.Item name="knowledge_points" label="考察知识点（回车添加）">
            <Select mode="tags" placeholder="如：手续费产生规则、退款条件" tokenSeparators={[",", "；", ";"]} />
          </Form.Item>
          <Form.Item name="reference_answer" label="参考答案（评分参考）">
            <Input.TextArea autoSize={{ minRows: 3 }} placeholder="分步骤的规范应答口径" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
