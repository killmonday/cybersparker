import React, { useState } from 'react'
import { Layout, Menu, Button, theme } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  DesktopOutlined,
  SearchOutlined,
  AppstoreOutlined,
  TableOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  SettingOutlined,
  ApartmentOutlined,
  DownloadOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  LogoutOutlined,
  CodeOutlined,
  SunOutlined,
  MoonOutlined,
  CloudServerOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'
import { useThemeContext } from '../App'

const { Header, Sider, Content } = Layout

type MenuItem = Required<MenuProps>['items'][number]

const REACT_SHELL = '/react-shell'

const linkStyle: React.CSSProperties = { textDecoration: 'none', color: 'inherit', display: 'block' }

function a(label: string, path: string) {
  return <a href={`${REACT_SHELL}${path}`} style={linkStyle}>{label}</a>
}

const menuItems: MenuItem[] = [
  { key: '/dashboard', icon: <DesktopOutlined />, label: a('仪表盘', '/dashboard') },
  { key: '/assets/search', icon: <SearchOutlined />, label: <a href={`${REACT_SHELL}/assets/search`} target="_blank" rel="noopener noreferrer">资产检索</a> },
  { key: 'task-mgmt', icon: <AppstoreOutlined />, label: '任务管理',
    children: [
      { key: '/batch-tasks', label: a('批量任务', '/batch-tasks') },
      { key: '/identify-tasks', label: a('自动扫描', '/identify-tasks') },
      { key: '/poc-gen-tasks', label: a('AI生成PoC', '/poc-gen-tasks') },
      { key: '/fscanx-tasks', label: a('fscanx导入', '/fscanx-tasks') },
      { key: '/export-tasks', label: a('导出任务', '/export-tasks') },
      { key: '/zones', label: a('扫描区域', '/zones') },
    ],
  },
  { key: 'dirscan-mgmt', icon: <ApartmentOutlined />, label: '目录扫描',
    children: [
      { key: '/dict-groups', label: a('字典组', '/dict-groups') },
      { key: '/dicts', label: a('字典管理', '/dicts') },
      { key: '/dirscan-tasks', label: a('扫描任务', '/dirscan-tasks') },
    ],
  },
  { key: 'result-mgmt', icon: <BarChartOutlined />, label: '结果管理',
    children: [
      { key: '/exp-results', label: a('漏洞利用结果', '/exp-results') },
      { key: '/auto-exp-results', label: a('自动扫描漏洞结果', '/auto-exp-results') },
    ],
  },
  { key: 'fingerprint-mgmt', icon: <TableOutlined />, label: '指纹管理',
    children: [
      { key: '/fingerprints', label: a('指纹列表', '/fingerprints') },
      { key: '/fingerprint-debug', label: a('指纹调试', '/fingerprint-debug') },
    ],
  },
  { key: 'plugin-mgmt', icon: <DatabaseOutlined />, label: '插件管理',
    children: [
      { key: '/plugins', label: a('插件列表', '/plugins') },
      { key: '/exp-debug', label: a('插件调试', '/exp-debug') },
    ],
  },
  { key: '/hosted-files', icon: <CloudServerOutlined />, label: a('文件托管', '/hosted-files') },
  { key: '/users', icon: <SettingOutlined />, label: a('用户管理', '/users') },
  { key: 'system-config', icon: <SettingOutlined />, label: '系统配置',
    children: [
      { key: '/proxies', label: a('代理设置', '/proxies') },
      { key: '/engines', label: a('测绘引擎', '/engines') },
      { key: '/ceye-config', label: a('DNSLog 配置', '/ceye-config') },
      { key: '/target-files', label: a('任务上传文件管理', '/target-files') },
      { key: '/ai-model-configs', label: a('AI模型配置', '/ai-model-configs') },
    ],
  },
]

function matchMenuKeys(pathname: string): { selected: string[]; open: string[] } {
  for (const item of menuItems) {
    if (!item) continue
    if ('children' in item && item.children) {
      for (const child of item.children) {
        if (!child) continue
        const childKey = String(child.key)
        if (pathname === childKey || pathname.startsWith(childKey + '/')) {
          return { selected: [childKey], open: [String(item.key)] }
        }
      }
    }
  }
  return { selected: [pathname], open: [] }
}

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': '仪表盘', '/assets/search': '资产检索',
  '/batch-tasks': '批量任务', '/identify-tasks': '自动扫描', '/poc-gen-tasks': 'AI生成PoC',
  '/plugins': '插件列表', '/exp-debug': '插件调试',
  '/fingerprints': '指纹列表', '/fingerprint-debug': '指纹调试',
  '/exp-results': '漏洞利用结果', '/auto-exp-results': '自动扫描漏洞结果',
  '/proxies': '代理设置', '/engines': '测绘引擎',
  '/ceye-config': 'DNSLog 配置',
  '/dict-groups': '字典组', '/dicts': '字典管理', '/dirscan-tasks': '目录扫描',
  '/export-tasks': '导出任务', '/target-files': '任务上传文件管理', '/ai-model-configs': 'AI模型配置',
  '/fscanx-tasks': 'fscanx导入', '/hosted-files': '文件托管', '/users': '用户管理',
  '/zones': '扫描区域',
}

function getPageTitle(pathname: string): string {
  const { selected } = matchMenuKeys(pathname)
  return PAGE_TITLES[selected[0] || ''] || ''
}

export const SidebarLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { token: t } = theme.useToken()
  const { mode, toggle: toggleTheme } = useThemeContext()

  const currentPath = location.pathname
  const { selected: selectedKeys, open: defaultOpenKeys } = matchMenuKeys(currentPath)
  const pageTitle = getPageTitle(currentPath)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={220}
        style={{
          overflow: 'auto', height: '100vh',
          position: 'fixed', left: 0, top: 0, bottom: 0, zIndex: 10,
          background: t.colorBgContainer,
          borderRight: `1px solid ${t.colorBorderSecondary}`,
        }}
      >
        <div style={{
          height: 56, display: 'flex', alignItems: 'center', gap: 8,
          padding: collapsed ? '0 16px' : '0 18px',
          borderBottom: `1px solid ${t.colorBorderSecondary}`,
          overflow: 'hidden',
        }}>
          <CodeOutlined style={{ fontSize: 20, color: t.colorPrimary, flexShrink: 0 }} />
          {!collapsed && (
            <span style={{ fontSize: 15, fontWeight: 700, color: t.colorText, whiteSpace: 'nowrap' }}>
              漏洞利用平台
            </span>
          )}
        </div>

        <Menu
          mode="inline"
          selectedKeys={selectedKeys}
          defaultOpenKeys={defaultOpenKeys}
          items={menuItems}
          onClick={(info) => {
            if (!info.key.startsWith('/')) return
            if (info.key === '/assets/search') return
            info.domEvent.preventDefault()
            navigate(info.key)
          }}
          style={{ borderInlineEnd: 'none', marginTop: 4, paddingBottom: 48 }}
        />
      </Sider>

      <Layout style={{
        marginLeft: collapsed ? 80 : 220,
        transition: 'all var(--transition-normal)',
        background: t.colorBgContainer,
      }}>
        <Header style={{
          padding: '0 24px', height: 48,
          background: t.colorBgContainer,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: `1px solid ${t.colorBorderSecondary}`,
          position: 'sticky', top: 0, zIndex: 9,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Button
              type="text" size="small"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
            />
            <span style={{ fontWeight: 600, fontSize: 14, color: t.colorText }}>
              {pageTitle}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button
              type="text" size="small"
              icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
              onClick={toggleTheme}
              title={mode === 'dark' ? '切换亮色' : '切换暗色'}
            />
            <Button
              type="text" size="small"
              icon={<LogoutOutlined />}
              onClick={() => {
                const token = document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))?.split('=')[1] || ''
                fetch('/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': token } })
                  .finally(() => { window.location.href = '/login' })
              }}
            >
              退出
            </Button>
          </div>
        </Header>

        <Content style={{ padding: 0, minHeight: 'calc(100vh - 48px)' }}>
          {children}
        </Content>
      </Layout>
    </Layout>
  )
}
