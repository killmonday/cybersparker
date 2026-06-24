import React, { useState, useEffect, useCallback } from 'react'
import { Table, Input, Button, Modal, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ExpResultItem, ExpResultListResponse } from '../types/result'
import { get, post, postForm, postFormBlob , timeNoSec} from '../api'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
}

interface PluginOption {
  CVE: string
  title: string
}

const ROWS_PER_PAGE = 13

const ExpResultListPage: React.FC<Props> = ({ apiUrl }) => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [fId, setFId] = useState(search.get('id') ?? '')
  const [fTaskId, setFTaskId] = useState(search.get('task_id') ?? '')
  const [fTarget, setFTarget] = useState(search.get('target') ?? '')
  const [fPlugin, setFPlugin] = useState(search.get('plugin') ?? '')
  const [fResult, setFResult] = useState(search.get('result') ?? '')
  const [fCreatime, setFCreatime] = useState(search.get('creatime') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [data, setData] = useState<ExpResultListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  // Verify modal
  const [verifyModal, setVerifyModal] = useState<{ open: boolean; target: string; pluginName: string }>({ open: false, target: '', pluginName: '' })
  const [plugins, setPlugins] = useState<PluginOption[]>([])
  const [verifyPlugin, setVerifyPlugin] = useState('')
  const [verifyPluginId, setVerifyPluginId] = useState<number|string>('')
  const [verifyModel, setVerifyModel] = useState('verify')
  const [verifyCmd, setVerifyCmd] = useState('')
  const [verifyModels, setVerifyModels] = useState<{value: string|number, label: string}[]>([])
  const [verifyResult, setVerifyResult] = useState('')
  const [verifyRunning, setVerifyRunning] = useState(false)

  const loadList = useCallback(() => {
    const params = new URLSearchParams()
    if (q) {
      params.set('q', q)
    } else {
      if (fId) params.set('id', fId)
      if (fTaskId) params.set('task_id', fTaskId)
      if (fTarget) params.set('target', fTarget)
      if (fPlugin) params.set('plugin', fPlugin)
      if (fResult) params.set('result', fResult)
      if (fCreatime) params.set('creatime', fCreatime)
    }
    params.set('page', String(page))
    params.set('rows_per_page', String(ROWS_PER_PAGE))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    setLoading(true); setSelected(new Set())
    get<ExpResultListResponse>(`${apiUrl}?${params.toString()}`)
      .then(data => setData(data))
      .finally(() => setLoading(false))
  }, [apiUrl, page, q, fId, fTaskId, fTarget, fPlugin, fResult, fCreatime])

  useEffect(() => { loadList() }, [loadList])

  function toggleSelect(id: number) {
    setSelected(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }

  function toggleAll() {
    if (!data) return
    const ids = data.items.map(i => i.id)
    setSelected(ids.every(id => selected.has(id)) ? new Set() : new Set(ids))
  }

  async function deleteOne(id: number) {
    if (!confirm('确认删除？')) return
    setSubmitting(true)
    await post('/api/v1/exp-results/batch-delete', { uids: [id] })
    setSubmitting(false)
    loadList()
  }

  async function batchDelete() {
    if (selected.size === 0) { alert('请先选择'); return }
    if (!confirm(`确认删除 ${selected.size} 条？`)) return
    setSubmitting(true)
    await post('/api/v1/exp-results/batch-delete', { uids: Array.from(selected) })
    setSubmitting(false)
    loadList()
  }

  async function clearResults() {
    const tid = parseInt(fTaskId, 10)
    if (!tid) { alert('仅支持按任务清空，请通过 task_id 筛选后操作'); return }
    if (!confirm(`确认清空任务 ${tid} 的全部漏洞利用结果？此操作不可恢复。`)) return
    setSubmitting(true)
    await post('/api/v1/exp-results/clear', { task_id: tid })
    setSubmitting(false)
    loadList()
  }

  async function downloadCsv() {
    const fd = new FormData()
    if (selected.size > 0) {
      Array.from(selected).forEach(id => fd.append('id_list[]', String(id)))
    } else {
      if (fId) fd.append('id', fId)
      if (fTarget) fd.append('target', fTarget)
      if (fPlugin) fd.append('select_plugin', fPlugin)
      if (fResult) fd.append('result', fResult)
      if (fCreatime) fd.append('creatime', fCreatime)
    }
    const r = await postFormBlob('/api/v1/exp-results/download', fd)
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'exp_result.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  async function openVerify(target: string, pluginName: string) {
    setVerifyModal({ open: true, target, pluginName })
    setVerifyPlugin(pluginName)
    setVerifyModel('verify')
    setVerifyCmd('')
    setVerifyResult('')
    setVerifyModels([{value: 'verify', label: '验证'}])

    const p = await get<any>('/api/v1/exp-results/plugins')
    if (p.status) setPlugins(p.data)

    if (pluginName) {
      const p2 = await get<any>(`/api/v1/exp-results/plugin-info?plugin_name=${encodeURIComponent(pluginName)}`)
      if (p2.status && p2.function_list) {
        setVerifyModels(p2.function_list)
        setVerifyModel(String(p2.function_list[0]?.value ?? 'verify'))
        setVerifyPluginId(p2.plugin_id ?? '')
      }
    }
  }

  async function onVerifyPluginChange(name: string) {
    setVerifyPlugin(name)
    setVerifyPluginId('')
    if (name) {
      const p = await get<any>(`/api/v1/exp-results/plugin-info?plugin_name=${encodeURIComponent(name)}`)
      if (p.status && p.function_list) {
        setVerifyModels(p.function_list)
        setVerifyModel(String(p.function_list[0]?.value ?? 'verify'))
        setVerifyPluginId(p.plugin_id ?? '')
      }
    }
  }

  async function runVerify() {
    setVerifyRunning(true); setVerifyResult('')
    const fd = new FormData()
    fd.append('target', verifyModal.target)
    fd.append('plugin', verifyPlugin)
    fd.append('plugin_id', String(verifyPluginId))
    fd.append('model', verifyModel)
    fd.append('cmd', verifyCmd)
    try {
      const p = await postForm<any>('/api/v1/exp-results/verify', fd)
      setVerifyResult(typeof p.data === 'string' ? p.data : JSON.stringify(p.data, null, 2))
    } catch (e: any) {
      setVerifyResult(e?.tip || e?.message || String(e))
    }
    setVerifyRunning(false)
  }

  function doSearch() { setPage(1); loadList() }

  const columns: ColumnsType<ExpResultItem> = [
    ...(canWrite ? [{
      title: <input type="checkbox" onChange={toggleAll} checked={data ? data.items.length > 0 && data.items.every(i => selected.has(i.id)) : false} /> as any,
      key: 'select', width: 40,
      render: (_: any, record: ExpResultItem) => (
        <input type="checkbox" checked={selected.has(record.id)} onChange={() => toggleSelect(record.id)} />
      ),
    }] : []),
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: 'Task', dataIndex: 'task_id', key: 'task_id', width: 70 },
    { title: '任务类型', dataIndex: 'task_type', key: 'task_type', width: 90,
      render: (v: number) => ({1: '单次任务', 2: '批量任务'}[v] || v),
    },
    {
      title: '插件', dataIndex: 'plugin_name', key: 'plugin_name', width: 180, ellipsis: true,
      render: (v: string) => <span title={v}>{v.length > 30 ? v.slice(0, 30) + '...' : v}</span>,
    },
    { title: '目标', dataIndex: 'target', key: 'target', width: 200, ellipsis: true },
    {
      title: '结果', dataIndex: 'result', key: 'result', width: 200, ellipsis: true,
      render: (v: string, record: ExpResultItem) => {
        if (!v) return '-'
        const full = record.result_full || v
        const truncated = v.length > 60 ? v.slice(0, 60) + '...' : v
        return (
          <a onClick={() => {
            const w = window.open('', '_blank')
            if (w) { w.document.title = '结果详情'; const s = w.document.createElement('style'); s.textContent = 'body{font-family:monospace;font-size:13px;padding:20px;white-space:pre-wrap;word-break:break-all;line-height:1.5;max-width:1200px;margin:0 auto;background:#fafaf9;color:#1c1917}'; w.document.head.appendChild(s); w.document.body.textContent = full }
          }} style={{ cursor: 'pointer' }}>
            {truncated}
          </a>
        )
      },
    },
    { title: '时间', dataIndex: 'creatime', key: 'creatime', width: 130, render: (v: string | null) => timeNoSec(v), ellipsis: true },
    ...(canWrite ? [{
      title: '操作', key: 'actions', width: 120,
      render: (_: any, record: ExpResultItem) => (
        <Space size={4}>
          <a onClick={() => openVerify(record.target, record.plugin_name)} style={{ cursor: 'pointer', fontSize: 12 }}>验证</a>
          <a onClick={() => deleteOne(record.id)} style={{ cursor: 'pointer', color: 'var(--danger)', fontSize: 12 }}>删除</a>
        </Space>
      ),
    }] : []),
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>漏洞利用结果</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <Input
            value={q}
            onChange={e => { setQ(e.target.value); if (e.target.value) { setFId(''); setFTarget(''); setFPlugin(''); setFResult(''); setFCreatime('') } }}
            placeholder="全局搜索（插件/目标/结果）"
            style={{ width: 220 }}
            onPressEnter={doSearch}
          />
          <Input value={fId} onChange={e => setFId(e.target.value)} placeholder="ID" style={{ width: 70 }} disabled={!!q} onPressEnter={doSearch} />
          <Input value={fTarget} onChange={e => setFTarget(e.target.value)} placeholder="目标" style={{ width: 150 }} disabled={!!q} onPressEnter={doSearch} />
          <Input value={fPlugin} onChange={e => setFPlugin(e.target.value)} placeholder="插件" style={{ width: 200 }} disabled={!!q} onPressEnter={doSearch} />
          <Input value={fResult} onChange={e => setFResult(e.target.value)} placeholder="结果" style={{ width: 120 }} disabled={!!q} onPressEnter={doSearch} />
          <Input value={fCreatime} onChange={e => setFCreatime(e.target.value)} placeholder="日期" style={{ width: 150 }} disabled={!!q} onPressEnter={doSearch} />
          <Button type="primary" onClick={doSearch}>搜索</Button>
        </div>

        {canWrite && <div style={{ marginBottom: 12 }}>
          <Space>
            <Button onClick={batchDelete} disabled={submitting || selected.size === 0}>
              批量删除{selected.size > 0 ? ` (${selected.size})` : ''}
            </Button>
            <Button onClick={downloadCsv} disabled={submitting}>下载 CSV</Button>
            {fTaskId && <Button danger onClick={clearResults} disabled={submitting}>清空结果</Button>}
          </Space>
        </div>}

        {loading ? (
          <div className="react-shell-panel"><span>加载中...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<ExpResultItem>
                columns={columns}
                dataSource={data?.items || []}
                rowKey="id"
                loading={loading}
                pagination={false}
                size="small"
              />
            </div>

            <div className="react-pagination-bar">
              <span>第 {data?.page ?? 1} / {data?.total_pages ?? 1} 页，共 {data?.total ?? 0} 条</span>
              <Space>
                <input
                  type="number"
                  min={1}
                  max={data?.total_pages ?? 1}
                  placeholder="页"
                  style={{ width: 50, height: 30, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
                  onKeyDown={e => {
                    if (e.key !== 'Enter') return
                    const n = parseInt((e.target as HTMLInputElement).value, 10)
                    if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n)
                  }}
                />
                <Button onClick={() => {
                  const inp = document.querySelector('.react-pagination-bar input[type="number"]') as HTMLInputElement
                  if (inp) { const n = parseInt(inp.value, 10); if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n) }
                }}>跳转</Button>
                <Button disabled={(data?.page ?? 1) <= 1} onClick={() => setPage(c => Math.max(1, c - 1))}>上一页</Button>
                <Button disabled={!data || data.page >= data.total_pages} onClick={() => setPage(c => c + 1)}>下一页</Button>
              </Space>
            </div>
          </>
        )}
      </div>

      {/* Verify Modal */}
      <Modal
        title="漏洞验证"
        open={verifyModal.open}
        onCancel={() => setVerifyModal({ open: false, target: '', pluginName: '' })}
        footer={null}
        width={560}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <label>目标
            <Input value={verifyModal.target} readOnly />
          </label>
          <label>插件
            <select value={verifyPlugin} onChange={e => onVerifyPluginChange(e.target.value)} style={{ width: '100%', padding: '6px 11px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 14 }}>
              {plugins.map(p => <option key={`${p.CVE}-${p.title}`} value={`[${p.CVE}]${p.title}`}>{`[${p.CVE}]${p.title}`}</option>)}
            </select>
          </label>
          <label>操作类型
            <select value={verifyModel} onChange={e => setVerifyModel(e.target.value)} style={{ width: '100%', padding: '6px 11px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 14 }}>
              {verifyModels.map(m => <option key={String(m.value)} value={String(m.value)}>{m.label}</option>)}
            </select>
          </label>
          <label>命令参数
            <Input value={verifyCmd} onChange={e => setVerifyCmd(e.target.value)} placeholder="可选" />
          </label>
        </div>
        <div style={{ marginTop: 12 }}>
          <Button type="primary" onClick={runVerify} loading={verifyRunning}>执行验证</Button>
        </div>
        {verifyResult ? (
          <div style={{ marginTop: 12, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12, background: 'var(--bg-elevated)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
            {verifyResult}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

export default ExpResultListPage
