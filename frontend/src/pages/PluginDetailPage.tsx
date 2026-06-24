import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Tag } from 'antd'
import { get } from '../api'
import { copyToClipboard } from '../utils'

interface PluginDetail {
  id: number
  title: string
  CVE: string
  type: number
  type_label: string
  plugin_language: number
  plugin_language_label: string
  severity: number | null
  severity_label: string
  use: number
  use_label: string
  time: string
  creat_time: string
  update_time: string
  tags: string[]
  poc_content: string
}

export default function PluginDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<PluginDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    get<{ status: boolean; data: PluginDetail; error?: string }>(`/api/v1/plugins/${id}`)
      .then((p) => {
        if (!p.status) { setError(p.error || '加载失败'); return }
        setData(p.data)
      })
      .catch(() => setError('加载失败'))
      .finally(() => setLoading(false))
  }, [id])

  function handleCopy() {
    if (!data?.poc_content) return
    copyToClipboard(data.poc_content).then((ok) => {
      if (ok) {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }
    })
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

  if (error || !data) {
    return (
      <div className="react-shell-page">
        <div className="react-shell-card">
          <div className="react-error-box">{error || '数据不存在'}</div>
        </div>
      </div>
    )
  }

  const rows: [string, React.ReactNode][] = [
    ['插件名称', data.title],
    ['CVE 编号', data.CVE || '—'],
    ['类型', data.type_label],
    ['插件语言', data.plugin_language_label],
    ['危险等级', data.severity_label || '—'],
    ['暴露时间', data.time || '—'],
    ['创建时间', data.creat_time || '—'],
    ['更新时间', data.update_time || '—'],
    [
      '使用状态',
      data.use === 1
        ? <Tag color="blue">{data.use_label}</Tag>
        : <Tag>{data.use_label}</Tag>,
    ],
    ['标签', data.tags.length ? data.tags.join(', ') : '—'],
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card">
        <div className="react-list-header" style={{ marginBottom: 16 }}>
          <div>
            <h2>{data.title}</h2>
            <p>插件基本信息与 POC 代码。</p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <a className="react-link-button" href="/react-shell/plugins">返回列表</a>
          </div>
        </div>

        <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 24 }}>
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label} style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{
                  width: 120, padding: '10px 14px', textAlign: 'left',
                  fontSize: 'var(--fs-caption)', color: 'var(--text-dim)',
                  background: 'var(--bg-elevated)', fontWeight: 600,
                }}>
                  {label}
                </th>
                <td style={{ padding: '10px 14px', fontSize: 'var(--fs-body)' }}>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 style={{ marginBottom: 8 }}>POC 代码</h3>
        <div style={{
          border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          overflow: 'hidden', marginBottom: 12,
        }}>
          <div style={{
            padding: '6px 14px', background: 'var(--bg-elevated)',
            fontSize: 'var(--fs-caption)', color: 'var(--text-dim)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span>poc_content</span>
            <button
              className="react-inline-button"
              onClick={handleCopy}
              style={{ fontSize: 'var(--fs-caption)' }}
            >
              {copied ? '已复制' : '复制'}
            </button>
          </div>
          <pre style={{
            margin: 0, padding: 16, overflow: 'auto', maxHeight: 500,
            fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-caption)',
            lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            background: 'var(--bg-surface)',
          }}>
            {data.poc_content || '(无内容)'}
          </pre>
        </div>

        <div>
          <a className="react-link-button" href="/react-shell/plugins">返回插件列表</a>
        </div>
      </div>
    </div>
  )
}
