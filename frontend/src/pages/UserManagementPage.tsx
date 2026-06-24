import React, { useState, useEffect, useCallback } from 'react'
import { Table, Button, Modal, Input, Select, Tag, Space, message, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useAuth } from '../contexts/AuthContext'

const API_BASE = '/api/v1/users'

interface UserItem {
  id: number
  username: string
  role: 'super_admin' | 'admin' | 'user'
  is_active: boolean
  date_joined: string | null
  last_login: string | null
}

const roleLabel: Record<string, string> = { super_admin: '超级管理员', admin: '普通管理员', user: '普通用户' }
const roleColor: Record<string, string> = { super_admin: 'red', admin: 'blue', user: 'default' }

export default function UserManagementPage() {
  const { role: currentRole } = useAuth()
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<string>('user')
  const [submitting, setSubmitting] = useState(false)
  const [pwdModalOpen, setPwdModalOpen] = useState(false)
  const [pwdTargetId, setPwdTargetId] = useState<number | null>(null)
  const [pwdValue, setPwdValue] = useState('')

  const fetchUsers = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(API_BASE, { credentials: 'same-origin' })
      if (r.status === 200) {
        const data = await r.json()
        setUsers(data.users || [])
      } else if (r.status === 403) {
        setUsers([])
      }
    } catch {
      setUsers([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const canManage = currentRole === 'super_admin' || currentRole === 'admin'

  // Show forbidden page for regular users
  if (currentRole === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <div style={{ textAlign: 'center', color: '#8b949e' }}>
          <h2 style={{ color: '#6c757d' }}>无操作权限</h2>
          <p>你的账号角色为普通用户，无法访问此页面。</p>
        </div>
      </div>
    )
  }

  const handleCreate = async () => {
    if (!newUsername.trim() || !newPassword) {
      message.warning('请填写用户名和密码')
      return
    }
    setSubmitting(true)
    try {
      const r = await fetch(`${API_BASE}/create`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ username: newUsername.trim(), password: newPassword, role: newRole }),
      })
      const data = await r.json()
      if (r.ok) {
        message.success('用户创建成功')
        setModalOpen(false)
        setNewUsername('')
        setNewPassword('')
        setNewRole('user')
        fetchUsers()
      } else {
        message.error(data.message || '创建失败')
      }
    } catch {
      message.error('网络错误')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      const r = await fetch(`${API_BASE}/${id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': getCsrfToken() },
      })
      const data = await r.json()
      if (r.ok) {
        message.success('用户已删除')
        fetchUsers()
      } else {
        message.error(data.message || '删除失败')
      }
    } catch {
      message.error('网络错误')
    }
  }

  const handleRoleChange = async (id: number, role: string) => {
    try {
      const r = await fetch(`${API_BASE}/${id}/role`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ role }),
      })
      const data = await r.json()
      if (r.ok) {
        message.success('角色已更新')
        fetchUsers()
      } else {
        message.error(data.message || '操作失败')
      }
    } catch {
      message.error('网络错误')
    }
  }

  const handlePasswordReset = async () => {
    if (!pwdValue || !pwdTargetId) return
    try {
      const r = await fetch(`${API_BASE}/${pwdTargetId}/password`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ password: pwdValue }),
      })
      const data = await r.json()
      if (r.ok) {
        message.success('密码已重置')
        setPwdModalOpen(false)
        setPwdValue('')
        setPwdTargetId(null)
      } else {
        message.error(data.message || '重置失败')
      }
    } catch {
      message.error('网络错误')
    }
  }

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    {
      title: '角色', dataIndex: 'role', key: 'role',
      render: (role: string) => <Tag color={roleColor[role] || 'default'}>{roleLabel[role] || role}</Tag>,
    },
    {
      title: '最后登录', dataIndex: 'last_login', key: 'last_login',
      render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '从未登录',
    },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: UserItem) => {
        const isSuperAdmin = currentRole === 'super_admin'
        const isAdmin = currentRole === 'admin'
        const targetIsUser = record.role === 'user'

        return (
          <Space>
            {isSuperAdmin && (
              <Select
                size="small"
                value={record.role}
                style={{ width: 100 }}
                onChange={(v) => handleRoleChange(record.id, v)}
                options={[
                  { label: '超级管理员', value: 'super_admin' },
                  { label: '普通管理员', value: 'admin' },
                  { label: '普通用户', value: 'user' },
                ]}
              />
            )}
            {(isSuperAdmin || (isAdmin && targetIsUser)) && (
              <Button
                size="small"
                onClick={() => { setPwdTargetId(record.id); setPwdValue(''); setPwdModalOpen(true) }}
              >
                重置密码
              </Button>
            )}
            {(isSuperAdmin || (isAdmin && targetIsUser)) && (
              <Popconfirm title="确定删除此用户？" onConfirm={() => handleDelete(record.id)}>
                <Button size="small" danger>删除</Button>
              </Popconfirm>
            )}
          </Space>
        )
      },
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用户管理</h2>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
            新增用户
          </Button>
        )}
      </div>

      <Table
        rowKey="id"
        dataSource={users}
        columns={columns}
        loading={loading}
        pagination={false}
      />

      <Modal
        title="新增用户"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => { setModalOpen(false); setNewUsername(''); setNewPassword(''); setNewRole('user') }}
        confirmLoading={submitting}
        okText="创建"
        cancelText="取消"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Input
            placeholder="用户名"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
          />
          <Input.Password
            placeholder="密码"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          {currentRole === 'super_admin' ? (
            <Select
              value={newRole}
              onChange={setNewRole}
              options={[
                { label: '普通管理员', value: 'admin' },
                { label: '普通用户', value: 'user' },
              ]}
            />
          ) : (
            <Select value="user" disabled options={[{ label: '普通用户', value: 'user' }]} />
          )}
        </div>
      </Modal>

      <Modal
        title="重置密码"
        open={pwdModalOpen}
        onOk={handlePasswordReset}
        onCancel={() => { setPwdModalOpen(false); setPwdValue(''); setPwdTargetId(null) }}
        okText="确认"
        cancelText="取消"
      >
        <Input.Password
          placeholder="新密码"
          value={pwdValue}
          onChange={(e) => setPwdValue(e.target.value)}
        />
      </Modal>
    </div>
  )
}

function getCsrfToken(): string {
  return document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))?.split('=')[1] || ''
}
