import { useCallback, useEffect, useState, type ReactNode } from "react"
import { Layout, Menu, Button, Space, Typography, Avatar, Tag, theme } from "antd"
import { LogoutOutlined } from "@ant-design/icons"
import { useLocation, useNavigate } from "react-router-dom"
import { designerApi, clearDesignerToken, getDesignerToken } from "../api/settle"
import type { SlProfile } from "../types/settle"

const { Header, Content } = Layout
const { Title } = Typography

/**
 * 设计师端布局。
 *
 * 刻意**不套**平台的 MainLayout —— 那套的导航是给派单员看的，
 * 而且依赖平台登录态。设计师端是独立身份、独立令牌，
 * 顶栏只有三个入口：我的订单 / 一键结算 / 收益明细。
 */
export default function DesignerLayout({ children }: { children: ReactNode }) {
  const nav = useNavigate()
  const loc = useLocation()
  const { token } = theme.useToken()
  const [profile, setProfile] = useState<SlProfile | null>(null)

  const load = useCallback(async () => {
    if (!getDesignerToken()) {
      nav("/designer/login", { replace: true })
      return
    }
    try {
      setProfile(await designerApi.profile())
    } catch (e) {
      // 只有「令牌无效」才踢回登录页。
      // 网络抖动、服务重启这类临时故障不该把设计师的登录态清掉 ——
      // 一清就要重新输密码，而结算窗口每月只有两天，错过就等下个月。
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 401 || status === 403) {
        clearDesignerToken()
        nav("/designer/login", { replace: true })
      }
    }
  }, [nav])

  useEffect(() => {
    void load()
  }, [load])

  // 后端 401 时把登录态清掉并回登录页
  useEffect(() => {
    const handler = () => {
      clearDesignerToken()
      nav("/designer/login", { replace: true })
    }
    window.addEventListener("designer:logout", handler)
    return () => window.removeEventListener("designer:logout", handler)
  }, [nav])

  const items = [
    { key: "/designer/orders", label: "我的订单" },
    { key: "/designer/settle", label: "一键结算" },
    { key: "/designer/income", label: "收益明细" },
    { key: "/designer/password", label: "修改密码" },
  ]

  const activeKey =
    loc.pathname === "/designer" ? "/designer/orders" : loc.pathname

  return (
    <Layout style={{ minHeight: "100vh", background: token.colorBgLayout }}>
      <Header
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 24px", background: token.colorBgContainer,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Space size="large" align="center">
          <Title level={4} style={{ margin: 0, color: token.colorPrimary }}>
            设计师结算端
          </Title>
          <Menu
            mode="horizontal"
            selectedKeys={[activeKey]}
            items={items}
            style={{ borderBottom: "none", minWidth: 300 }}
            onClick={({ key }) => nav(key)}
          />
        </Space>
        <Space size="middle">
          {profile && (
            <>
              <Avatar style={{ backgroundColor: "#87d068" }}>
                {(profile.nickname || profile.name)[0]}
              </Avatar>
              <span>{profile.nickname || profile.name}</span>
              {profile.must_change_password && (
                <Tag color="orange">待改初始密码</Tag>
              )}
              <Button
                type="link"
                icon={<LogoutOutlined />}
                onClick={() => {
                  clearDesignerToken()
                  nav("/designer/login", { replace: true })
                }}
              >
                退出
              </Button>
            </>
          )}
        </Space>
      </Header>
      <Content style={{ padding: 24, maxWidth: 1200, width: "100%", margin: "0 auto" }}>
        {children}
      </Content>
    </Layout>
  )
}
