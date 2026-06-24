import React, { Suspense, lazy, createContext, useContext, useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, Spin, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { SidebarLayout } from './components/SidebarLayout'
import { AuthProvider } from './contexts/AuthContext'

const Loading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
    <Spin size="large" />
  </div>
)

const PluginListPage = lazy(() => import('./pages/PluginListPage'))
const PluginDetailPage = lazy(() => import('./pages/PluginDetailPage'))
const DictListPage = lazy(() => import('./pages/DictListPage'))
const DictGroupListPage = lazy(() => import('./pages/DictGroupListPage'))
const ProxyListPage = lazy(() => import('./pages/ProxyListPage'))
const EngineListPage = lazy(() => import('./pages/EngineListPage'))
const FingerprintListPage = lazy(() => import('./pages/FingerprintListPage'))
const TaskResultStandalone = lazy(() => import('./pages/TaskResultStandalone'))
const GlobalAssetSearchPage = lazy(() => import('./pages/GlobalAssetSearchPage'))
const IpPortDetailPage = lazy(() => import('./pages/IpPortDetailPage'))
const AutoScanTaskListPage = lazy(() => import('./pages/AutoScanTaskListPage'))
const BatchTaskListPage = lazy(() => import('./pages/BatchTaskListPage'))
const DirscanTaskListPage = lazy(() => import('./pages/DirscanTaskListPage'))
const AutoExpResultListPage = lazy(() => import('./pages/AutoExpResultListPage'))
const ExpResultListPage = lazy(() => import('./pages/ExpResultListPage'))
const ExportTaskListPage = lazy(() => import('./pages/ExportTaskListPage'))
const CeyeConfigPage = lazy(() => import('./pages/CeyeConfigPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ExpDebugPage = lazy(() => import('./pages/ExpDebugPage'))
const VulnExploitPage = lazy(() => import('./pages/VulnExploitPage'))
const FingerprintDebugPage = lazy(() => import('./pages/FingerprintDebugPage'))
const TargetFileListPage = lazy(() => import('./pages/TargetFileListPage'))
const AiModelConfigPage = lazy(() => import('./pages/AiModelConfigPage'))
const PocGenTaskListPage = lazy(() => import('./pages/PocGenTaskListPage'))
const PocGenTaskExecutePage = lazy(() => import('./pages/PocGenTaskExecutePage'))
const DirscanResultsPage = lazy(() => import('./pages/DirscanResultsPage'))
const FscanxTaskListPage = lazy(() => import('./pages/FscanxTaskListPage'))
const FscanxTaskDetailPage = lazy(() => import('./pages/FscanxTaskDetailPage'))
const HostedFileListPage = lazy(() => import('./pages/HostedFileListPage'))
const UserManagementPage = lazy(() => import('./pages/UserManagementPage'))
const ZoneListPage = lazy(() => import('./pages/ZoneListPage'))

const API_BASE = '/api/v1'

type ThemeMode = 'light' | 'dark'

interface ThemeContextValue {
  mode: ThemeMode
  toggle: () => void
}

export const ThemeContext = createContext<ThemeContextValue>({ mode: 'light', toggle: () => {} })

export function useThemeContext() {
  return useContext(ThemeContext)
}

function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const stored = localStorage.getItem('theme')
    if (stored === 'dark' || stored === 'light') return stored
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode)
    localStorage.setItem('theme', mode)
  }, [mode])

  const toggle = useCallback(() => {
    setMode((prev) => (prev === 'light' ? 'dark' : 'light'))
  }, [])

  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      {children}
    </ThemeContext.Provider>
  )
}

const sharedToken = {
  borderRadius: 10,
  borderRadiusLG: 14,
  borderRadiusSM: 8,
  borderRadiusXS: 6,
  fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  fontSize: 14,
  lineHeight: 1.55,
  fontWeightStrong: 600,
}

function ThemedApp() {
  const { mode } = useThemeContext()
  const isDark = mode === 'dark'

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          ...sharedToken,
          colorPrimary: '#a0aae0',
          colorInfo: '#6c5ce7',
          colorSuccess: '#00a86b',
          colorWarning: '#e67e22',
          colorError: '#e74c3c',
          colorLink: '#3366ff',
          colorLinkHover: '#2541d4',
          colorBorder: isDark ? '#30363d' : '#e9ecef',
          colorBorderSecondary: isDark ? '#21262d' : '#e9ecef',
          colorText: isDark ? '#e6edf3' : '#212529',
          colorTextSecondary: isDark ? '#8b949e' : '#6c757d',
          colorBgContainer: isDark ? '#161b22' : '#ffffff',
          colorBgLayout: isDark ? '#0d1117' : '#f1f3f5',
          controlHeight: 36,
          controlHeightLG: 40,
          controlHeightSM: 30,
          paddingContentHorizontal: 20,
          paddingContentVertical: 16,
        },
        components: {
          Layout: {
            siderBg: isDark ? '#161b22' : '#ffffff',
            headerBg: isDark ? '#161b22' : '#ffffff',
            bodyBg: isDark ? '#0d1117' : '#f1f3f5',
            triggerBg: isDark ? '#21262d' : '#f8f9fa',
            triggerColor: isDark ? '#8b949e' : '#6c757d',
          },
          Menu: {
            itemBg: 'transparent',
            subMenuItemBg: 'transparent',
            darkItemBg: 'transparent',
            itemBorderRadius: 8,
            itemMarginInline: 8,
            itemSelectedBg: isDark ? '#151d3d' : '#eef1ff',
            itemSelectedColor: '#a0aae0',
          },
          Table: {
            headerBg: isDark ? '#21262d' : '#f8f9fa',
            headerColor: isDark ? '#8b949e' : '#6c757d',
            rowHoverBg: isDark ? '#1a2035' : '#f5f7ff',
            borderColor: isDark ? '#30363d' : '#e9ecef',
          },
          Button: {
            primaryShadow: '0 1px 3px rgba(160, 170, 224, 0.2)',
            fontWeight: 600,
          },
          Card: {
            borderRadiusLG: 14,
          },
          Input: {
            activeShadow: '0 0 0 3px rgba(160, 170, 224, 0.15)',
          },
          Select: {
            optionSelectedBg: isDark ? '#151d3d' : '#eef1ff',
          },
        },
      }}
    >
      <BrowserRouter basename="/react-shell">
        <AuthProvider>
          <Routes>
            {/* 资产检索（全局）— 独立页面，不用管理后台侧边栏 */}
            <Route path="assets/search" element={
              <Suspense fallback={<Loading />}>
                <GlobalAssetSearchPage apiUrl={`${API_BASE}/assets/search`} />
              </Suspense>
            } />
            {/* 单任务资产检索 — 同样独立页面，不用管理后台侧边栏 */}
            <Route path="identify-tasks/:uid/results" element={
              <Suspense fallback={<Loading />}>
                <TaskResultStandalone />
              </Suspense>
            } />
            {/* 同 IP 端口详情 — 独立页面，新标签页打开 */}
            <Route path="ip-detail" element={
              <Suspense fallback={<Loading />}>
                <IpPortDetailPage />
              </Suspense>
            } />
            {/* 漏洞利用 — 独立页面，资产检索新标签页打开 */}
            <Route path="vuln-exploit" element={
              <Suspense fallback={<Loading />}>
                <VulnExploitPage />
              </Suspense>
            } />
            {/* 目录扫描结果 — 独立页面，新标签页打开 */}
            <Route path="dirscan-results" element={
              <Suspense fallback={<Loading />}>
                <DirscanResultsPage />
              </Suspense>
            } />
            {/* 其余页面 — 管理后台侧边栏布局 */}
            <Route path="*" element={
              <SidebarLayout>
                <Suspense fallback={<Loading />}>
                <Routes>
                  <Route path="plugins/:id" element={<PluginDetailPage />} />
                  <Route path="plugins" element={<PluginListPage apiUrl={`${API_BASE}/plugins`} />} />
                  <Route path="dicts" element={<DictListPage apiUrl={`${API_BASE}/dicts`} />} />
                  <Route path="dict-groups" element={<DictGroupListPage apiUrl={`${API_BASE}/dict-groups`} />} />
                  <Route path="proxies" element={<ProxyListPage apiUrl={`${API_BASE}/proxies`} />} />
                  <Route path="engines" element={<EngineListPage apiUrl={`${API_BASE}/cyberspace-engines`} />} />
                  <Route path="fingerprints" element={<FingerprintListPage apiUrl={`${API_BASE}/fingerprints`} />} />
                  <Route path="identify-tasks" element={<AutoScanTaskListPage apiUrl={`${API_BASE}/identify-tasks`} />} />
                  <Route path="batch-tasks" element={<BatchTaskListPage apiUrl={`${API_BASE}/batch-tasks`} />} />
                  <Route path="dirscan-tasks" element={<DirscanTaskListPage apiUrl={`${API_BASE}/dirscan-tasks`} />} />
                  <Route path="auto-exp-results" element={<AutoExpResultListPage apiUrl={`${API_BASE}/auto-exp-results`} />} />
                  <Route path="exp-results" element={<ExpResultListPage apiUrl={`${API_BASE}/exp-results`} />} />
                  <Route path="export-tasks" element={<ExportTaskListPage apiUrl={`${API_BASE}/export-tasks`} />} />
                  <Route path="ceye-config" element={<CeyeConfigPage apiUrl={`${API_BASE}/ceye-config`} />} />
                  <Route path="dashboard" element={<DashboardPage apiUrl={`${API_BASE}/dashboard`} />} />
                  <Route path="exp-debug" element={<ExpDebugPage apiUrl={`${API_BASE}/exp-debug/plugins`} />} />
                  <Route path="fingerprint-debug" element={<FingerprintDebugPage apiUrl={`${API_BASE}/fingerprint-debug/fingerprints`} />} />
                  <Route path="target-files" element={<TargetFileListPage />} />
                  <Route path="ai-model-configs" element={<AiModelConfigPage />} />
                  <Route path="fscanx-tasks/:taskId" element={<FscanxTaskDetailPage />} />
                  <Route path="fscanx-tasks" element={<FscanxTaskListPage />} />
                  <Route path="poc-gen-tasks/:id" element={<PocGenTaskExecutePage />} />
                  <Route path="poc-gen-tasks" element={<PocGenTaskListPage />} />
                  <Route path="hosted-files" element={<HostedFileListPage />} />
                  <Route path="users" element={<UserManagementPage />} />
                  <Route path="zones" element={<ZoneListPage />} />
                  <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
              </Suspense>
            </SidebarLayout>
            } />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
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
