import { useCallback, useEffect, useState } from "react"
import {
  Alert, Button, Card, Col, Form, Input, Modal, Row, Select, Space, Table, Tag,
  Typography, message,
} from "antd"
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons"
import { settleApi, errMsg, issuesText } from "../api/settle"
import type { SlDesigner, SlMeta } from "../types/settle"

const { Title, Text } = Typography

/**
 * 设计师管理（模块二：录入设计师信息）。
 *
 * 课件特别强调两点，这一页都照做：
 * 1. **「所属战区」和「所属HR」必须留空** —— 所以这两个框直接
 *    disabled + placeholder 写明原因，而不是让人填了再报错。
 *    后端也会硬拦，双保险。
 * 2. **密码设为临时密码，通知设计师首次登录修改** —— 派单员设完密码，
 *    列表里会标「待改密」，前端会把它显示出来，派单员好去催。
 */
export default function SettleDesignersPage() {
  const [rows, setRows] = useState<SlDesigner[]>([])
  const [meta, setMeta] = useState<SlMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<SlDesigner | null>(null)
  const [keyword, setKeyword] = useState("")
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [list, m] = await Promise.all([
        settleApi.listDesigners(keyword ? { keyword } : undefined),
        settleApi.meta(),
      ])
      setRows(list)
      setMeta(m)
    } catch (e) {
      message.error(errMsg(e, "设计师加载失败"))
    } finally {
      setLoading(false)
    }
  }, [keyword])

  useEffect(() => {
    void load()
  }, [load])

  const openForm = (d?: SlDesigner) => {
    setEditing(d ?? null)
    form.resetFields()
    if (d) {
      form.setFieldsValue({
        name: d.name,
        nickname: d.nickname,
        phone: d.phone,
        alipay_account: d.alipay_account,
        alipay_name: d.alipay_name,
        gender: d.gender,
        recruitment_source: d.recruitment_source,
        production_level: d.production_level,
        note: d.note,
      })
    } else {
      form.setFieldsValue({ gender: 1 })
    }
    setOpen(true)
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await settleApi.updateDesigner(editing.id, v)
        message.success("已保存")
      } else {
        await settleApi.createDesigner(v)
        message.success("已录入，设计师可用手机号登录结算端")
      }
      setOpen(false)
      await load()
    } catch (e) {
      // 后端按字段给的问题，逐条列出来，不丢成一个「保存失败」
      const text = issuesText(e)
      message.error(text || errMsg(e, "保存失败"))
    }
  }

  const remove = (d: SlDesigner) => {
    Modal.confirm({
      title: `删除设计师 ${d.name}？`,
      content: "该设计师名下的订单不会被删除，但会失去登录结算端的资格。",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await settleApi.deleteDesigner(d.id)
          message.success("已删除")
          await load()
        } catch (e) {
          message.error(errMsg(e, "删除失败"))
        }
      },
    })
  }

  const columns = [
    { title: "姓名", dataIndex: "name", width: 90 },
    { title: "花名", dataIndex: "nickname", width: 90 },
    { title: "手机号（登录账号）", dataIndex: "phone", width: 140,
      render: (v: string) => v || <Text type="secondary">未填</Text> },
    { title: "支付宝账户", dataIndex: "alipay_account", width: 170, ellipsis: true,
      render: (v: string) => v || <Text type="secondary">未填</Text> },
    { title: "实名", dataIndex: "alipay_name", width: 90,
      render: (v: string) => v || "—" },
    { title: "性别", dataIndex: "gender_label", width: 60 },
    { title: "招聘来源", dataIndex: "recruitment_source", width: 100,
      render: (v: string) => v || "—" },
    { title: "制作水平", dataIndex: "production_level", width: 100,
      render: (v: string) => v || "—" },
    { title: "战区 / HR", width: 110,
      render: () => <Tag color="default">按课件留空</Tag> },
    { title: "订单数", dataIndex: "order_count", width: 70, align: "right" as const,
      render: (v: number) => v ?? 0 },
    { title: "密码状态", dataIndex: "must_change_password", width: 100,
      render: (v: boolean) =>
        v ? <Tag color="orange">待首次改密</Tag> : <Tag color="green">已改密</Tag> },
    { title: "状态", dataIndex: "status", width: 80,
      render: (v: string) => (
        <Tag color={v === "active" ? "green" : "default"}>
          {v === "active" ? "在职" : "停用"}
        </Tag>
      ) },
    { title: "操作", width: 100, fixed: "right" as const,
      render: (_: unknown, r: SlDesigner) => (
        <Space size={2}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openForm(r)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => remove(r)} />
        </Space>
      ) },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>设计师管理</Title>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="「所属战区」与「所属HR」按课件要求保持为空"
        description="这两个字段系统不启用，录入时不要填任何内容 —— 填了会被直接拒绝。派单员只负责开通账号与填收款信息。"
      />

      <Card size="small">
        <Row gutter={[12, 12]} align="middle" style={{ marginBottom: 12 }}>
          <Col flex="auto">
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜姓名 / 花名 / 手机号"
              style={{ maxWidth: 280 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm()}>
              录入设计师
            </Button>
          </Col>
        </Row>
        <Table rowKey="id" size="small" loading={loading} dataSource={rows}
          columns={columns} scroll={{ x: 1300 }} pagination={false} />
      </Card>

      <Modal
        title={editing ? `编辑 ${editing.name}` : "录入设计师"}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        okText="保存"
        width={720}
      >
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="name" label="姓名"
                rules={[{ required: true, message: "姓名为必填项" }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="nickname" label="花名"
                rules={[{ required: true, message: "花名为必填项" }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="phone" label="手机号（结算端登录账号）"
                rules={[{ required: true, message: "手机号为必填项" }]}>
                <Input maxLength={11} placeholder="11 位手机号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="password" label={editing ? "重置密码（留空不改）" : "登录密码"}
                rules={editing ? [] : [
                  { required: true, message: "登录密码为必填项" },
                  { min: 6, message: "密码不能少于 6 位" },
                ]}>
                <Input.Password placeholder={editing ? "不修改请留空" : "建议设为临时密码"} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="alipay_account" label="支付宝账户"
                rules={[{ required: true, message: "支付宝账户为必填项" }]}
                extra="务必与设计师核对 —— 打款只认这里">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="alipay_name" label="支付宝实名"
                extra="留空则默认取姓名">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="gender" label="性别">
                <Select options={(meta?.genders ?? []).map((g) => ({
                  value: g.value, label: g.label,
                }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="recruitment_source" label="招聘来源"
                rules={[{ required: true, message: "招聘来源为必填项" }]}>
                <Select
                  showSearch
                  options={(meta?.recruitment_sources ?? []).map((s) => ({ value: s, label: s }))}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="production_level" label="制作水平"
                rules={[{ required: true, message: "制作水平为必填项" }]}>
                <Select
                  options={(meta?.production_levels ?? []).map((s) => ({ value: s, label: s }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="war_zone" label="所属战区">
                <Input disabled placeholder="按课件要求留空，切勿填写" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="hr_id" label="所属 HR">
                <Input disabled placeholder="按课件要求留空，切勿填写" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
