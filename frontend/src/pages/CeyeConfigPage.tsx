import React, { useState, useEffect } from 'react'
import { Input, Button, message } from 'antd'
import { get, post } from '../api'
import { useAuth } from '../contexts/AuthContext'

interface CeyeConfigData {
  identifier: string
  api_token: string
}

interface CeyeConfigResponse {
  status: boolean
  data: CeyeConfigData
  error?: string
  errors?: Record<string, string>
}

export default function CeyeConfigPage({ apiUrl }: {
  apiUrl: string
}) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const [token, setToken] = useState('')
  const [identifier, setIdentifier] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    get<CeyeConfigResponse>(apiUrl)
      .then((p) => {
        if (p.status && p.data) {
          setToken(p.data.api_token || '')
          setIdentifier(p.data.identifier || '')
        }
      })
      .finally(() => setLoading(false))
  }, [apiUrl])

  async function save() {
    setSaving(true)
    setMsg('')
    try {
      const p = await post<CeyeConfigResponse>(apiUrl, { api_token: token, identifier })
      setMsg(p.status ? '保存成功' : (p.errors ? JSON.stringify(p.errors) : (p.error ?? '保存失败')))
    } catch {
      setMsg('保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="react-shell-page">
        <div className="react-shell-card">
          <div className="react-shell-panel"><span>加载中...</span></div>
        </div>
      </div>
    )
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>ceye DNSLog 配置</h2>
          </div>
        </div>
        <div className="react-form-grid" style={{ maxWidth: 480 }}>
          <label>API Token<input value={token} onChange={(e) => setToken(e.target.value)} /></label>
          <label>Identifier<input value={identifier} onChange={(e) => setIdentifier(e.target.value)} /></label>
        </div>
        {msg ? (
          <div className={msg === '保存成功' ? 'react-shell-panel' : 'react-error-box'} style={{ marginTop: 12 }}>
            {msg}
          </div>
        ) : null}
        {canWrite && <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button className="react-primary-button" onClick={save} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </button>
        </div>}
      </div>
    </div>
  )
}
