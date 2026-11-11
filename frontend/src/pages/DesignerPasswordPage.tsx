import { useState } from "react"
import { Alert, Button, Card, Form, Input, Typography, message } from "antd"
import { designerApi, errMsg } from "../api/settle"

const { Title, Paragraph } = Typography

/**
 * 设计师端「修改密码」。
 *
 * 派单员在总后台录的是**临时密码**，设计师首次登录必须改 ——
 * 这是课件里写明的安全要求，所以这个页面在待改密状态下会被优先引导过来。
 */
export default function DesignerPasswordPage() {
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()

  const submit = async () => {
    try {
      const v = await form.validateFields()
      setBusy(true)
      await designerApi.changePassword(v.old_password, v.new_password)
      message.success("密码已修改，下次登录请用新密码")
      form.resetFields()
    } catch (e) {
      message.error(errMsg(e, "修改失败"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 520, margin: "0 auto" }}>
      <Title level={4} style={{ marginTop: 0 }}>修改密码</Title>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="派单员给你的是初始密码"
        description="首次登录后请立刻改成自己的密码。初始密码所有人可能都一样，存在被别人登录查收益的风险。"
      />

      <Card size="small">
        <Form form={form} layout="vertical" onFinish={() => void submit()}>
          <Form.Item name="old_password" label="原密码"
            rules={[{ required: true, message: "请输入原密码" }]}>
            <Input.Password placeholder="派单员给你的初始密码" />
          </Form.Item>
          <Form.Item name="new_password" label="新密码"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 6, message: "新密码不能少于 6 位" },
            ]}>
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码"
            dependencies={["new_password"]}
            rules={[
              { required: true, message: "请再输入一次新密码" },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  !value || getFieldValue("new_password") === value
                    ? Promise.resolve()
                    : Promise.reject(new Error("两次输入的密码不一致")),
              }),
            ]}>
            <Input.Password placeholder="再输一次新密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>
            保存新密码
          </Button>
        </Form>

        <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 16, marginBottom: 0 }}>
          忘记密码了？联系派单员在总后台重置。
        </Paragraph>
      </Card>
    </div>
  )
}
