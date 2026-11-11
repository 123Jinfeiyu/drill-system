import { useState } from "react"
import { Alert, Button, Card, Form, Input, Typography, message } from "antd"
import { LockOutlined, UserOutlined } from "@ant-design/icons"
import { useNavigate } from "react-router-dom"
import { designerApi, setDesignerToken } from "../api/settle"
import { errMsg } from "../api/client"

const { Title, Text, Paragraph } = Typography

/**
 * 设计师端登录。
 *
 * 课件前置条件：**设计师账号必须由派单员在总后台「团队管理」完成录入后，
 * 才能生成并获取登录权限**。所以这里的失败提示必须区分两种：
 * - 「该手机号未开通」→ 去找派单员录入
 * - 「手机号或密码不正确」→ 自己再输一遍
 *
 * 这两种动作完全不同，混成一句「登录失败」等于让人瞎猜。
 */
export default function DesignerLoginPage() {
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()

  const submit = async () => {
    try {
      const v = await form.validateFields()
      setBusy(true)
      const r = await designerApi.login(v.phone, v.password)
      setDesignerToken(r.token)
      if (r.must_change_password) {
        message.warning("首次登录，请先修改初始密码")
        nav("/designer/password", { replace: true })
      } else {
        message.success(`欢迎回来，${r.nickname || r.name}`)
        nav("/designer/orders", { replace: true })
      }
    } catch (e) {
      message.error(errMsg(e, "登录失败"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center", padding: 24,
    }}>
      <Card style={{ width: 420 }} styles={{ body: { padding: 32 } }}>
        <Title level={4} style={{ marginTop: 0, textAlign: "center" }}>
          设计师结算端
        </Title>
        <Paragraph type="secondary" style={{ textAlign: "center", marginBottom: 24 }}>
          用派单员给你录入的手机号登录
        </Paragraph>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 20 }}
          message="首次登录请用初始密码"
          description="登录后系统会要求你修改密码，以后用新密码登录。"
        />

        <Form form={form} layout="vertical" onFinish={() => void submit()}>
          <Form.Item name="phone" label="手机号"
            rules={[{ required: true, message: "请输入手机号" }]}>
            <Input prefix={<UserOutlined />} placeholder="派单员录入的手机号" maxLength={11} />
          </Form.Item>
          <Form.Item name="password" label="密码"
            rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="初始密码或修改后的密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            登录
          </Button>
        </Form>

        <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 20 }}>
          还没有账号？联系派单员在总后台「团队管理」完成录入后才能登录。
        </Text>
      </Card>
    </div>
  )
}
