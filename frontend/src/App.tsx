import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { ConfigProvider, App as AntdApp, Spin } from "antd"
import zhCN from "antd/locale/zh_CN"
import { AuthProvider, useAuth } from "./context/AuthContext"
import { ThemeProvider, useTheme } from "./context/ThemeContext"
import MainLayout from "./components/MainLayout"
import BackgroundLayer from "./components/BackgroundLayer"
import LoginPage from "./pages/LoginPage"
import ScenariosPage from "./pages/ScenariosPage"
import ScenarioImportPage from "./pages/ScenarioImportPage"
import DrillWorkbenchPage from "./pages/DrillWorkbenchPage"
import SessionsPage from "./pages/SessionsPage"
import KnowledgePage from "./pages/KnowledgePage"
import PracticePage from "./pages/PracticePage"
import PracticeWorkbenchPage from "./pages/PracticeWorkbenchPage"
import PracticeHistoryPage from "./pages/PracticeHistoryPage"
import FdeWorkbenchPage from "./pages/FdeWorkbenchPage"
import LiveAssistPage from "./pages/LiveAssistPage"
import LiveCallSimPage from "./pages/LiveCallSimPage"
import OpcDashboardPage from "./pages/OpcDashboardPage"
import OpcOrdersPage from "./pages/OpcOrdersPage"
import OpcOrderDetailPage from "./pages/OpcOrderDetailPage"
import OpcDesignersPage from "./pages/OpcDesignersPage"
import OpcStoresPage from "./pages/OpcStoresPage"
import OpcSettlementsPage from "./pages/OpcSettlementsPage"
import OpcRulesPage from "./pages/OpcRulesPage"
import SettleDashboardPage from "./pages/SettleDashboardPage"
import SettleDesignersPage from "./pages/SettleDesignersPage"
import SettleOrdersPage from "./pages/SettleOrdersPage"
import SettleOrderDetailPage from "./pages/SettleOrderDetailPage"
import SettleSettlementsPage from "./pages/SettleSettlementsPage"
import SettleBridgePage from "./pages/SettleBridgePage"
import DesignerLoginPage from "./pages/DesignerLoginPage"
import DesignerOrdersPage from "./pages/DesignerOrdersPage"
import DesignerSettlePage from "./pages/DesignerSettlePage"
import DesignerIncomePage from "./pages/DesignerIncomePage"
import DesignerPasswordPage from "./pages/DesignerPasswordPage"
import DesignerLayout from "./components/DesignerLayout"

function AppRoutes() {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  /**
   * 设计师结算端走**独立认证**（手机号 + 密码，自己签令牌）。
   *
   * 它不受平台的登录门禁管 —— 设计师本来就没有平台账号。
   * 所以这里先分流，设计师端那几页完全绕开 isAuthenticated 判断。
   */
  if (window.location.pathname.startsWith("/designer")) {
    return (
      <Routes>
        <Route path="/designer/login" element={<DesignerLoginPage />} />
        <Route
          path="/designer/*"
          element={
            <DesignerLayout>
              <Routes>
                <Route path="orders" element={<DesignerOrdersPage />} />
                <Route path="settle" element={<DesignerSettlePage />} />
                <Route path="income" element={<DesignerIncomePage />} />
                <Route path="password" element={<DesignerPasswordPage />} />
                <Route path="*" element={<DesignerOrdersPage />} />
              </Routes>
            </DesignerLayout>
          }
        />
      </Routes>
    )
  }

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <MainLayout>
      <Routes>
        <Route path="/" element={<Navigate to="/scenarios" replace />} />
        <Route path="/live" element={<LiveAssistPage />} />
        <Route path="/live/calls" element={<LiveCallSimPage />} />
        <Route path="/scenarios" element={<ScenariosPage />} />
        <Route path="/scenarios/import" element={<ScenarioImportPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/practice" element={<PracticePage />} />
        <Route path="/practice/history" element={<PracticeHistoryPage />} />
        <Route path="/practice/:sessionId" element={<PracticeWorkbenchPage />} />
        <Route path="/drill/:sessionId" element={<DrillWorkbenchPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/fde" element={<FdeWorkbenchPage />} />
        <Route path="/opc" element={<OpcDashboardPage />} />
        <Route path="/opc/orders" element={<OpcOrdersPage />} />
        <Route path="/opc/orders/:id" element={<OpcOrderDetailPage />} />
        <Route path="/opc/designers" element={<OpcDesignersPage />} />
        <Route path="/opc/stores" element={<OpcStoresPage />} />
        <Route path="/opc/settlements" element={<OpcSettlementsPage />} />
        <Route path="/opc/rules" element={<OpcRulesPage />} />
        <Route path="/settle" element={<SettleDashboardPage />} />
        <Route path="/settle/designers" element={<SettleDesignersPage />} />
        <Route path="/settle/orders" element={<SettleOrdersPage />} />
        <Route path="/settle/orders/:id" element={<SettleOrderDetailPage />} />
        <Route path="/settle/settlements" element={<SettleSettlementsPage />} />
        <Route path="/settle/bridge" element={<SettleBridgePage />} />
        <Route path="*" element={<Navigate to="/scenarios" replace />} />
      </Routes>
    </MainLayout>
  )
}

function ThemedApp() {
  const { themeConfig } = useTheme()
  return (
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <AntdApp>
        <BackgroundLayer />
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  )
}
