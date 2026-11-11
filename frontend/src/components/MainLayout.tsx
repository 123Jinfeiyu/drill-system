import { useMemo, useState, type ReactNode } from "react"
import { Layout, Menu, Button, Space, Typography, Avatar, Tag, Dropdown, Segmented, theme } from "antd"
import { BgColorsOutlined, MoonOutlined, PictureOutlined, SunOutlined } from "@ant-design/icons"
import { useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "../context/AuthContext"
import { useTheme } from "../context/ThemeContext"
import { withAlpha, type ThemeMode } from "../context/theme-context"
import BackgroundSettings from "./BackgroundSettings"
import type { Role } from "../types/api"

const { Header, Content } = Layout

const ROLE_LABEL: Record<Role, string> = {
  student: "学员",
  teacher: "讲师",
  admin: "管理员",
}

const ROLE_COLOR: Record<Role, string> = {
  student: "blue",
  teacher: "purple",
  admin: "red",
}

export default function MainLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const { mode, skinId, skins, bg, setMode, setSkin } = useTheme()
  const { token } = theme.useToken()
  const nav = useNavigate()
  const loc = useLocation()
  const [bgOpen, setBgOpen] = useState(false)

  const items = useMemo(() => {
    const base: { key: string; label: string }[] = [
      // 实战话术排最前：其余模块都是练或管，只有它是在接真实来电时用的
      { key: "/live", label: "实战话术" },
      { key: "/live/calls", label: "模拟来电" },
      { key: "/scenarios", label: "剧本库" },
      { key: "/practice", label: "Q&A 演练场" },
      { key: "/practice/history", label: "演练统计" },
      { key: "/sessions", label: "演练记录" },
      { key: "/fde", label: "FDE 工作台" },
    ]
    if (user?.role === "teacher" || user?.role === "admin") {
      base.splice(2, 0, { key: "/scenarios/import", label: "导入剧本" })
      base.splice(3, 0, { key: "/knowledge", label: "知识库" })
    }
    return base
  }, [user])

  /**
   * OPC 一人公司系统的导航单独放一组。
   *
   * 用二级菜单而不是平铺 6 项 —— 顶部是水平菜单，平铺会把演练系统原有的入口
   * 挤到换行，窄屏直接看不全。收进「OPC 撮合」一个下拉里，两边都清爽。
   */
  const opcItems = useMemo(
    () => [
      { key: "/opc", label: "撮合看板" },
      { key: "/opc/orders", label: "订单池" },
      { key: "/opc/designers", label: "设计师" },
      { key: "/opc/stores", label: "店铺" },
      { key: "/opc/settlements", label: "结算" },
      { key: "/opc/rules", label: "分账规则" },
    ],
    [],
  )

  /**
   * 设计师结算系统的导航同样收进一个下拉。
   *
   * 顶部已经平铺了演练系统 + OPC 撮合两组，再平铺 5 个结算入口
   * 必然换行。收进「结算系统」里，跟 OPC 撮合一个层级。
   */
  const settleItems = useMemo(
    () => [
      { key: "/settle", label: "业务看板" },
      { key: "/settle/designers", label: "设计师管理" },
      { key: "/settle/orders", label: "订单登记" },
      { key: "/settle/settlements", label: "结算管理" },
      { key: "/settle/bridge", label: "总系统互通" },
      { key: "/designer/login", label: "设计师端入口" },
    ],
    [],
  )

  const activeKey =
    loc.pathname.startsWith("/settle")
      ? loc.pathname === "/settle"
        ? "/settle"
        : loc.pathname
      : loc.pathname.startsWith("/opc")
      ? loc.pathname === "/opc"
        ? "/opc"
        : loc.pathname
      : loc.pathname === "/"
        ? "/scenarios"
        : loc.pathname.startsWith("/sessions")
          ? "/sessions"
          : loc.pathname === "/practice/history"
            ? "/practice/history"
            : loc.pathname.startsWith("/practice")
              ? "/practice"
              : loc.pathname

  const skinMenuItems = useMemo(
    () =>
      skins.map((s) => ({
        key: s.id,
        label: (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: s.colorPrimary,
                display: "inline-block",
                boxShadow: "inset 0 0 0 1px rgba(0, 0, 0, 0.2)",
              }}
            />
            {s.name}
          </span>
        ),
      })),
    [skins],
  )

  return (
    <Layout
      style={{
        minHeight: "100vh",
        // 有背景时整体让位给底层背景层（BackgroundLayer fixed zIndex 0）
        position: "relative",
        zIndex: 1,
        background: bg ? "transparent" : undefined,
      }}
    >
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          background: bg ? withAlpha(token.colorBgContainer, 0.72) : token.colorBgContainer,
          backdropFilter: bg ? "blur(12px) saturate(1.4)" : undefined,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Space size="large" align="center">
          <Typography.Title level={4} style={{ margin: 0, color: token.colorPrimary }}>
            AI 客服演练
          </Typography.Title>
          <Menu
            mode="horizontal"
            selectedKeys={[activeKey]}
            items={[
              ...items,
              {
                key: "opc-group",
                label: "OPC 撮合",
                children: opcItems,
              },
              {
                key: "settle-group",
                label: "结算系统",
                children: settleItems,
              },
            ]}
            style={{ borderBottom: "none", minWidth: 240 }}
            onClick={({ key }) => nav(key)}
          />
        </Space>
        <Space size="middle">
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as ThemeMode)}
            options={[
              { value: "light", label: "亮", icon: <SunOutlined /> },
              { value: "dark", label: "暗", icon: <MoonOutlined /> },
            ]}
          />
          <Dropdown
            menu={{ items: skinMenuItems, selectedKeys: [skinId], onClick: ({ key }) => setSkin(key) }}
            trigger={["click"]}
          >
            <Button icon={<BgColorsOutlined />}>皮肤</Button>
          </Dropdown>
          <Button icon={<PictureOutlined />} onClick={() => setBgOpen(true)}>
            背景
          </Button>
          {user && (
            <>
              <Avatar style={{ backgroundColor: "#87d068" }}>
                {user.display_name?.[0] || user.username[0].toUpperCase()}
              </Avatar>
              <span>{user.display_name || user.username}</span>
              <Tag color={ROLE_COLOR[user.role]}>{ROLE_LABEL[user.role]}</Tag>
              <Button type="link" onClick={logout}>
                退出
              </Button>
            </>
          )}
        </Space>
      </Header>
      <Content style={{ padding: 24, background: bg ? "transparent" : token.colorBgLayout }}>
        {children}
      </Content>
      <BackgroundSettings open={bgOpen} onClose={() => setBgOpen(false)} />
    </Layout>
  )
}
