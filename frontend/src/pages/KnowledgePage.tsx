import { useEffect, useMemo, useState } from "react"
import {
  App as AntdApp,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd"
import type { ColumnsType } from "antd/es/table"
import { useNavigate } from "react-router-dom"
import {
  createKnowledge,
  deleteKnowledge,
  importKnowledgeUrl,
  importKnowledgeUrls,
  listKnowledge,
  searchKnowledge,
  updateKnowledge,
} from "../api/knowledge"
import { errMsg } from "../api/client"
import { useAuth } from "../context/AuthContext"
import type { KnowledgeItem } from "../types/api"

interface CreateFormValues {
  title: string
  content: string
  tags?: string[]
  source_url?: string
}

interface ImportFormValues {
  url: string
  title?: string
  tags?: string[]
}

export default function KnowledgePage() {
  const { user } = useAuth()
  const nav = useNavigate()
  const { message } = AntdApp.useApp()

  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [loading, setLoading] = useState(true)
  const [createSubmitting, setCreateSubmitting] = useState(false)
  const [importSubmitting, setImportSubmitting] = useState(false)
  const [batchText, setBatchText] = useState("")
  const [batchSubmitting, setBatchSubmitting] = useState(false)

  // 【P4-5 修复】编辑弹窗状态
  const [editing, setEditing] = useState<KnowledgeItem | null>(null)
  const [editSubmitting, setEditSubmitting] = useState(false)

  const [createForm] = Form.useForm<CreateFormValues>()
  const [importForm] = Form.useForm<ImportFormValues>()
  const [editForm] = Form.useForm<CreateFormValues>()

  useEffect(() => {
    listKnowledge()
      .then((data) => setItems(data))
      .catch((e) => message.error(errMsg(e, "加载知识条目失败")))
      .finally(() => setLoading(false))
  }, [message])

  const columns = useMemo<ColumnsType<KnowledgeItem>>(
    () => [
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        ellipsis: true,
      },
      {
        title: "标签",
        dataIndex: "tags",
        key: "tags",
        render: (tags: string[]) =>
          tags && tags.length > 0 ? (
            <Space size={[4, 4]} wrap>
              {tags.map((t, i) => (
                <Tag key={`${t}-${i}`} color="blue">
                  {t}
                </Tag>
              ))}
            </Space>
          ) : (
            "-"
          ),
      },
      {
        title: "来源",
        dataIndex: "source_url",
        key: "source_url",
        ellipsis: true,
        render: (url: string) =>
          url ? (
            <a href={url} target="_blank" rel="noreferrer">
              {url}
            </a>
          ) : (
            "-"
          ),
      },
      {
        title: "创建时间",
        dataIndex: "created_at",
        key: "created_at",
        width: 180,
        render: (v: string) => new Date(v).toLocaleString("zh-CN"),
      },
      {
        title: "操作",
        key: "op",
        width: 130,
        render: (_: unknown, r: KnowledgeItem) => (
          <Space size={4}>
            <Button size="small" type="link" onClick={() => openEdit(r)}>
              编辑
            </Button>
            <Popconfirm
              title="确认删除该知识条目？"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDelete(r.id)}
            >
              <Button size="small" type="link" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items],
  )

  const handleDelete = async (id: string) => {
    try {
      await deleteKnowledge(id)
      message.success("已删除")
      setItems((prev) => prev.filter((it) => it.id !== id))
    } catch (e) {
      message.error(errMsg(e, "删除失败"))
    }
  }

  // 【P4-5 修复】站内搜索：关键词非空走 /knowledge/search，清空则恢复全量列表
  const handleSearch = async (q: string) => {
    const kw = q.trim()
    setLoading(true)
    try {
      const data = kw ? await searchKnowledge(kw, 50) : await listKnowledge()
      setItems(data)
    } catch (e) {
      message.error(errMsg(e, "搜索失败"))
    } finally {
      setLoading(false)
    }
  }

  // 【P4-5 修复】打开编辑弹窗
  const openEdit = (item: KnowledgeItem) => {
    setEditing(item)
    editForm.setFieldsValue({
      title: item.title,
      content: item.content,
      tags: item.tags,
      source_url: item.source_url,
    })
  }

  // 【P4-5 修复】提交编辑（后端 PUT /knowledge/{id}）
  const handleUpdate = async (values: CreateFormValues) => {
    if (!editing) return
    setEditSubmitting(true)
    try {
      const updated = await updateKnowledge(editing.id, {
        title: values.title,
        content: values.content,
        tags: values.tags ?? [],
        source_url: values.source_url ?? "",
      })
      message.success("已更新")
      setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
      setEditing(null)
    } catch (e) {
      message.error(errMsg(e, "更新失败"))
    } finally {
      setEditSubmitting(false)
    }
  }

  const handleCreate = async (values: CreateFormValues) => {
    setCreateSubmitting(true)
    try {
      const created = await createKnowledge({
        title: values.title,
        content: values.content,
        tags: values.tags ?? [],
        source_url: values.source_url ?? "",
      })
      message.success("已保存")
      setItems((prev) => [created, ...prev])
      createForm.resetFields()
    } catch (e) {
      message.error(errMsg(e, "保存失败"))
    } finally {
      setCreateSubmitting(false)
    }
  }

  const handleImport = async (values: ImportFormValues) => {
    setImportSubmitting(true)
    try {
      const created = await importKnowledgeUrl({
        url: values.url,
        title: values.title ?? "",
        tags: values.tags ?? [],
      })
      message.success("抓取并导入成功")
      setItems((prev) => [created, ...prev])
      importForm.resetFields()
    } catch (e) {
      message.error(errMsg(e, "抓取失败"))
    } finally {
      setImportSubmitting(false)
    }
  }

  const handleBatchImport = async () => {
    const text = batchText.trim()
    if (!text) {
      message.warning("请先粘贴URL")
      return
    }
    const entries: { url: string; title?: string }[] = []
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim()
      if (!line) continue
      const spaceIdx = line.indexOf(" ")
      if (spaceIdx > 0) {
        const url = line.slice(0, spaceIdx).trim()
        const title = line.slice(spaceIdx + 1).trim()
        entries.push(url ? { url, title: title || undefined } : { url: line })
      } else {
        entries.push({ url: line })
      }
    }
    if (entries.length === 0) {
      message.warning("请先粘贴URL")
      return
    }
    setBatchSubmitting(true)
    try {
      const res = await importKnowledgeUrls({ urls: entries })
      message.success(`批量导入完成: 成功 ${res.succeeded} 个，失败 ${res.failed} 个`)
      if (res.failed > 0) {
        message.warning(`失败URL: ${res.failures.map((f) => f.url).join(", ")}`)
      }
      const fresh = await listKnowledge()
      setItems(fresh)
      setBatchText("")
    } catch (e) {
      message.error(errMsg(e, "批量抓取失败"))
    } finally {
      setBatchSubmitting(false)
    }
  }

  if (user?.role !== "teacher" && user?.role !== "admin") {
    return (
      <Empty description="仅讲师可访问" style={{ marginTop: 80 }}>
        <Button type="primary" onClick={() => nav("/scenarios")}>
          返回剧本库
        </Button>
      </Empty>
    )
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        知识库管理
      </Typography.Title>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card title="新增知识条目">
            <Form
              form={createForm}
              layout="vertical"
              onFinish={(v) => handleCreate(v as CreateFormValues)}
              initialValues={{ tags: [], source_url: "" }}
            >
              <Form.Item
                name="title"
                label="标题"
                rules={[{ required: true, message: "请输入标题" }, { max: 200, message: "不超过 200 字" }]}
              >
                <Input placeholder="如：重复工单判定规则" maxLength={200} />
              </Form.Item>
              <Form.Item
                name="content"
                label="内容"
                rules={[{ required: true, message: "请输入内容" }]}
              >
                <Input.TextArea autoSize={{ minRows: 8 }} placeholder="业务规则、知识说明、参考口径等" />
              </Form.Item>
              <Form.Item name="tags" label="标签">
                <Select mode="tags" placeholder="输入后回车添加，如：重复工单、工单" tokenSeparators={[","]} />
              </Form.Item>
              <Form.Item name="source_url" label="来源 URL（可选）">
                <Input placeholder="https://..." />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button type="primary" htmlType="submit" loading={createSubmitting}>
                  保存
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col span={12}>
          <Card title="从公开URL导入">
            <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
              仅抓取公开页面，需登录的页面请手动粘贴内容。
            </Typography.Paragraph>
            <Form
              form={importForm}
              layout="vertical"
              onFinish={(v) => handleImport(v as ImportFormValues)}
              initialValues={{ tags: [] }}
            >
              <Form.Item
                name="url"
                label="URL"
                rules={[{ required: true, message: "请输入 URL" }]}
              >
                <Input placeholder="https://example.com/article" />
              </Form.Item>
              <Form.Item name="title" label="标题（可选，留空自动取网页 title）">
                <Input placeholder="留空自动取网页标题" maxLength={200} />
              </Form.Item>
              <Form.Item name="tags" label="标签（可选）">
                <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[","]} />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button type="primary" htmlType="submit" loading={importSubmitting}>
                  抓取并导入
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col span={24}>
          <Card title="批量导入URL">
            <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
              每行一个公开 URL（需登录的页面请用左侧表单手动粘贴内容）。可选：在 URL 后用空格加标题，如
              <code> https://xxx/page 提前还款规则</code>。
            </Typography.Paragraph>
            <Input.TextArea
              value={batchText}
              onChange={(e) => setBatchText(e.target.value)}
              autoSize={{ minRows: 6 }}
              placeholder={"https://example.com/page1 标题一\nhttps://example.com/page2\nhttps://example.com/page3 标题三"}
            />
            <div style={{ marginTop: 12 }}>
              <Button type="primary" loading={batchSubmitting} onClick={handleBatchImport}>
                批量抓取并导入
              </Button>
            </div>
          </Card>
        </Col>
      </Row>

      <Card
        title="知识条目列表"
        extra={
          /* 【P4-5 修复】站内搜索入口 */
          <Input.Search
            placeholder="搜索标题 / 内容 / 标签"
            allowClear
            style={{ width: 300 }}
            onSearch={handleSearch}
          />
        }
      >
        <Table
          rowKey="id"
          dataSource={items}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: "暂无知识条目，请在左侧新增或从 URL 导入" }}
        />
      </Card>

      {/* 【P4-5 修复】编辑知识条目弹窗（原先只有新增/删除，改错字只能删了重建） */}
      <Modal
        open={!!editing}
        title="编辑知识条目"
        okText="保存"
        cancelText="取消"
        confirmLoading={editSubmitting}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(v) => handleUpdate(v as CreateFormValues)}
        >
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: "请输入标题" }, { max: 200, message: "不超过 200 字" }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true, message: "请输入内容" }]}>
            <Input.TextArea autoSize={{ minRows: 8 }} />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[","]} />
          </Form.Item>
          <Form.Item name="source_url" label="来源 URL（可选）">
            <Input placeholder="https://..." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
