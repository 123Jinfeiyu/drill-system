import { useState } from "react"
import { Card, Form, Input, Button, Typography, Segmented, App as AntdApp } from "antd"
import { useNavigate, Navigate } from "react-router-dom"
import { useAuth } from "../context/AuthContext"
import { useTheme } from "../context/ThemeContext"
import { authApi } from "../api"
import { errMsg } from "../api/client"

type Mode = "login" | "register"

interface LoginValues {
  username: string
  password: string
}

interface RegisterValues {
  username: string
  password: string
  confirm: string
  display_name?: string
}

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth()
  const { bg } = useTheme()
  const nav = useNavigate()
  const { message } = AntdApp.useApp()
  const [mode, setMode] = useState<Mode>("login")
  const [loading, setLoading] = useState(false)
  const [loginForm] = Form.useForm<LoginValues>()
  const [registerForm] = Form.useForm<RegisterValues>()

  if (isAuthenticated) return <Navigate to="/scenarios" replace />

  const onLogin = async (values: LoginValues) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success("登录成功")
      nav("/scenarios", { replace: true })
    } catch (e) {
      message.error(errMsg(e, "登录失败"))
    } finally {
      setLoading(false)
    }
  }

  // 【P4-2 修复】登录页原先没有注册入口，新学员只能靠种子脚本/管理员建号。
  // 注册成功直接自动登录（复用后端 /api/auth/register，角色固定为 student）。
  const onRegister = async (values: RegisterValues) => {
    setLoading(true)
    try {
      await authApi.register({
        username: values.username.trim(),
        password: values.password,
        display_name: values.display_name?.trim() || undefined,
      })
      await login(values.username.trim(), values.password)
      message.success("注册成功，已自动登录")
      nav("/scenarios", { replace: true })
    } catch (e) {
      message.error(errMsg(e, "注册失败"))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        position: "relative",
        zIndex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        // 设了背景时让底层 BackgroundLayer 露出来；没设才用默认渐变
        background: bg ? "transparent" : "linear-gradient(135deg, #1677ff 0%, #69b1ff 100%)",
      }}
    >
      <Card style={{ width: 380, boxShadow: "0 8px 24px rgba(0,0,0,0.15)" }}>
        {/* 卡片背景由 themeConfig 的 colorBgContainer 统一控制：设背景时自动半透明 */}
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 8 }}>
          AI 客服演练系统
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center", marginBottom: 16 }}>
          团队培训 · 智能评分 · 多维复盘
        </Typography.Paragraph>

        <Segmented
          block
          value={mode}
          onChange={(v) => setMode(v as Mode)}
          options={[
            { label: "登录", value: "login" },
            { label: "注册", value: "register" },
          ]}
          style={{ marginBottom: 20 }}
        />

        {mode === "login" ? (
          <Form form={loginForm} layout="vertical" onFinish={onLogin} autoComplete="off">
            <Form.Item
              label="账号"
              name="username"
              rules={[{ required: true, message: "请输入账号" }]}
            >
              <Input placeholder="用户名" size="large" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password placeholder="密码" size="large" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block size="large" loading={loading}>
              登录
            </Button>
          </Form>
        ) : (
          <Form form={registerForm} layout="vertical" onFinish={onRegister} autoComplete="off">
            <Form.Item
              label="账号"
              name="username"
              rules={[
                { required: true, message: "请输入账号" },
                { min: 3, max: 64, message: "账号长度需为 3~64 位" },
              ]}
            >
              <Input placeholder="用户名（3~64 位）" size="large" maxLength={64} />
            </Form.Item>
            <Form.Item label="昵称（可选）" name="display_name">
              <Input placeholder="展示名称，留空则同账号" size="large" maxLength={64} />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[
                { required: true, message: "请输入密码" },
                { min: 8, max: 72, message: "密码长度需为 8~72 位" },
                {
                  validator: (_, value: string) =>
                    !value || (/[A-Za-z]/.test(value) && /\d/.test(value))
                      ? Promise.resolve()
                      : Promise.reject(new Error("密码必须同时包含字母和数字")),
                },
              ]}
            >
              <Input.Password placeholder="至少 8 位，含字母和数字" size="large" maxLength={72} />
            </Form.Item>
            <Form.Item
              label="确认密码"
              name="confirm"
              dependencies={["password"]}
              rules={[
                { required: true, message: "请再次输入密码" },
                ({ getFieldValue }) => ({
                  validator: (_, value) =>
                    !value || getFieldValue("password") === value
                      ? Promise.resolve()
                      : Promise.reject(new Error("两次输入的密码不一致")),
                }),
              ]}
            >
              <Input.Password placeholder="再次输入密码" size="large" maxLength={72} />
            </Form.Item>
            <Button type="primary" htmlType="submit" block size="large" loading={loading}>
              注册并登录
            </Button>
          </Form>
        )}

        <Typography.Paragraph
          type="secondary"
          style={{ fontSize: 12, textAlign: "center", marginTop: 16, marginBottom: 0 }}
        >
          测试账号 学员 student01 / Test@2025
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
