import { useEffect, useMemo, useState } from "react"
import {
  App as AntdApp,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd"
import { EditOutlined, PlusOutlined } from "@ant-design/icons"
import * as liveApi from "../api/live"
import { errMsg } from "../api/client"
import type { LiveScene, LiveScriptItem } from "../types/api"

const AUDIO_TAG: Record<string, { color: string; label: string }> = {
  file: { color: "green", label: "专业录音" },
  record: { color: "cyan", label: "现场录音" },
  tts: { color: "gold", label: "合成" },
}

interface FormValues {
  code?: string
  label: string
  text: string
  auto_play: boolean
}

/**
 * 快捷码话术管理抽屉：按场景查看 / 新增 / 编辑（含改快捷码）/ 删除。
 * CRUD 后端对登录用户开放（实战口径），删除有 Popconfirm 二次确认。
 */
export default function LiveScriptManager({
  open,
  onClose,
  scenes,
  defaultSceneId,
  onChanged,
}: {
  open: boolean
  onClose: () => void
  scenes: LiveScene[]
  defaultSceneId: string
  onChanged: (data: Awaited<ReturnType<typeof liveApi.fetchBootstrap>>) => void
}) {
  const { message } = AntdApp.useApp()
  const [sceneId, setSceneId] = useState(defaultSceneId || scenes[0]?.id || "")
  const [addForm] = Form.useForm<FormValues>()
  const [editForm] = Form.useForm<FormValues>()
  const [editing, setEditing] = useState<LiveScriptItem | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open && (!sceneId || !scenes.some((s) => s.id === sceneId))) {
      setSceneId(defaultSceneId || scenes[0]?.id || "")
    }
  }, [open, scenes, sceneId, defaultSceneId])

  const current = useMemo(() => scenes.find((s) => s.id === sceneId), [scenes, sceneId])
  const scripts = current?.scripts ?? []

  const refresh = async () => {
    onChanged(await liveApi.fetchBootstrap())
  }

  const onAdd = async (values: FormValues) => {
    if (!current) return
    setBusy(true)
    try {
      const created = await liveApi.createLiveScript(current.id, {
        code: values.code?.trim() || undefined,
        label: values.label?.trim() ?? "",
        text: values.text.trim(),
        auto_play: values.auto_play,
      })
      message.success(`已新增 ${created.code}`)
      addForm.resetFields()
      await refresh()
    } catch (err) {
      message.error(errMsg(err, "新增失败"))
    } finally {
      setBusy(false)
    }
  }

  const openEdit = (item: LiveScriptItem) => {
    setEditing(item)
    editForm.setFieldsValue({ code: item.code, label: item.label, text: item.text, auto_play: item.auto_play })
  }

  const onSaveEdit = async (values: FormValues) => {
    if (!editing) return
    setBusy(true)
    try {
      const updated = await liveApi.updateLiveScript(editing.id, {
        code: values.code?.trim(),
        label: values.label?.trim() ?? "",
        text: values.text.trim(),
        auto_play: values.auto_play,
      })
      message.success(`已保存 ${updated.code}`)
      setEditing(null)
      await refresh()
    } catch (err) {
      message.error(errMsg(err, "保存失败"))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (item: LiveScriptItem) => {
    setBusy(true)
    try {
      await liveApi.deleteLiveScript(item.id)
      message.success(`已删除 ${item.code}（连同它的现场录音）`)
      await refresh()
    } catch (err) {
      message.error(errMsg(err, "删除失败"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer
      title="快捷码话术管理"
      placement="right"
      width={760}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Segmented
          value={sceneId}
          onChange={(v) => setSceneId(v as string)}
          options={scenes.map((s) => ({ value: s.id, label: s.name }))}
          style={{ maxWidth: "100%", overflowX: "auto" }}
        />

        {current ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            场景「{current.name}」共 {scripts.length} 条。快捷码就是录音文件名，改码后对应的 mp3 也要跟着改名。
          </Typography.Text>
        ) : null}

        <Form
          form={addForm}
          layout="inline"
          onFinish={onAdd}
          initialValues={{ auto_play: false }}
          style={{ rowGap: 8, flexWrap: "wrap" }}
        >
          <Form.Item name="code" tooltip="留空自动生成（c001 起排）">
            <Input placeholder="快捷码，留空自动" style={{ width: 150 }} maxLength={48} />
          </Form.Item>
          <Form.Item name="label">
            <Input placeholder="短标题（可选）" style={{ width: 160 }} maxLength={200} />
          </Form.Item>
          <Form.Item name="text" rules={[{ required: true, message: "话术正文必填" }]}>
            <Input placeholder="话术正文" style={{ width: 260 }} />
          </Form.Item>
          <Form.Item name="auto_play" valuePropName="checked" tooltip="打开场景时自动播这条">
            <Switch checkedChildren="开场" unCheckedChildren="手动" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<PlusOutlined />} htmlType="submit" loading={busy} disabled={!current}>
              新增
            </Button>
          </Form.Item>
        </Form>

        <Table<LiveScriptItem>
          rowKey="id"
          size="small"
          dataSource={scripts}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            {
              title: "快捷码",
              dataIndex: "code",
              width: 110,
              render: (code: string, item) => (
                <Space size={4}>
                  <Tag style={{ fontFamily: "ui-monospace, monospace", margin: 0 }}>{code}</Tag>
                  {item.auto_play ? <Tag color="blue" style={{ margin: 0 }}>开场</Tag> : null}
                </Space>
              ),
            },
            { title: "标题", dataIndex: "label", width: 140, ellipsis: true },
            { title: "正文", dataIndex: "text", ellipsis: true },
            {
              title: "音频",
              dataIndex: "audio_status",
              width: 92,
              render: (s: string) => <Tag color={AUDIO_TAG[s]?.color ?? "default"} style={{ margin: 0 }}>{AUDIO_TAG[s]?.label ?? s}</Tag>,
            },
            { title: "用过", dataIndex: "use_count", width: 60, align: "right" },
            {
              title: "操作",
              key: "actions",
              width: 120,
              render: (_, item) => (
                <Space size={4}>
                  <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(item)} />
                  <Popconfirm
                    title={`删除 ${item.code}？`}
                    description="连同它的现场录音一起删，不可恢复。"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => void onDelete(item)}
                  >
                    <Button size="small" type="text" danger loading={busy && !editing}>
                      删
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Space>

      <Modal
        title={`编辑 ${editing?.code ?? ""}`}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={busy}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" onFinish={onSaveEdit}>
          <Form.Item
            name="code"
            label="快捷码"
            extra="改码后录音文件名约定随之变化；与他人占用冲突会提示"
            rules={[{ required: true, message: "快捷码不能为空" }]}
          >
            <Input maxLength={48} />
          </Form.Item>
          <Form.Item name="label" label="短标题（可选）">
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="text" label="话术正文" rules={[{ required: true, message: "正文必填" }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
          <Form.Item name="auto_play" label="打开场景时自动播报这条" valuePropName="checked">
            <Switch checkedChildren="是" unCheckedChildren="否" />
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  )
}
