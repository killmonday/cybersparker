import React, { useState, useEffect, useCallback } from 'react'
import { Table, Input, Button, Modal, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { AutoExpResultItem, AutoExpResultListResponse } from '../types/result'
import { get, post, postFormBlob , timeNoSec} from '../api'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
}

const ROWS_PER_PAGE = 13

const AutoExpResultListPage: React.FC<Props> = ({ apiUrl }) => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [fId, setFId] = useState(search.get('id') ?? '')
  const [fTaskId, setFTaskId] = useState(search.get('task_id') ?? '')
  const [fTarget, setFTarget] = useState(search.get('target') ?? '')
  const [fProduct, setFProduct] = useState(search.get('product') ?? '')
  const [fPlugin, setFPlugin] = useState(search.get('plugin') ?? '')
  const [fResult, setFResult] = useState(search.get('result') ?? '')
  const [fCreatime, setFCreatime] = useState(search.get('creatime') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [data, setData] = useState<AutoExpResultListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [submitting, setSubmitting] = useState(false)

  const loadList = useCallback(() => {
    const params = new URLSearchParams()
    if (fId) params.set('id', fId)
    if (fTaskId) params.set('task_id', fTaskId)
    if (fTarget) params.set('target', fTarget)
    if (fProduct) params.set('product', fProduct)
    if (fPlugin) params.set('plugin', fPlugin)
    if (fResult) params.set('result', fResult)
    if (fCreatime) params.set('creatime', fCreatime)
    params.set('page', String(page))
    params.set('rows_per_page', String(ROWS_PER_PAGE))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)

    setLoading(true)
    setSelected(new Set())
    get<AutoExpResultListResponse>(`${apiUrl}?${params.toString()}`)
      .then(r => setData(r))
      .finally(() => setLoading(false))
  }, [apiUrl, page, fId, fTaskId, fTarget, fProduct, fPlugin, fResult, fCreatime])

  useEffect(() => { loadList() }, [loadList])

  function toggleSelect(id: number) {
    setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }

  function toggleAll() {
    if (!data) return
    const allIds = data.items.map(i => i.id)
    if (allIds.every(id => selected.has(id))) setSelected(new Set())
    else setSelected(new Set(allIds))
  }

  async function deleteOne(id: number) {
    if (!confirm('确认删除该记录？')) return
    setSubmitting(true)
    const p = await post<{ status: boolean }>('/api/v1/auto-exp-results/batch-delete', { uids: [id] })
    setSubmitting(false)
    if (!p.status) { alert('删除失败'); return }
    loadList()
  }

  async function batchDelete() {
    if (selected.size === 0) { alert('请先选择'); return }
    if (!confirm(`确认删除 ${selected.size} 条记录？`)) return
    setSubmitting(true)
    const p = await post<{ status: boolean }>('/api/v1/auto-exp-results/batch-delete', { uids: Array.from(selected) })
    setSubmitting(false)
    if (p.status) loadList()
  }

  async function clearResults() {
    const tid = parseInt(fTaskId, 10)
    if (!tid) { alert('仅支持按任务清空，请通过 task_id 筛选后操作'); return }
    if (!confirm(`确认清空任务 ${tid} 的全部自动扫描漏洞结果？此操作不可恢复。`)) return
    setSubmitting(true)
    await post('/api/v1/auto-exp-results/clear', { task_id: tid })
    setSubmitting(false)
    loadList()
  }

  async function downloadCsv() {
    const ids = Array.from(selected)
    if (ids.length > 0) {
      const formData = new FormData()
      ids.forEach(id => formData.append('id_list[]', String(id)))
      const r = await postFormBlob('/api/v1/auto-exp-results/download', formData)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'exp_result.csv'; a.click()
      URL.revokeObjectURL(url)
    } else {
      const formData = new FormData()
      if (fId) formData.append('id', fId)
      if (fTarget) formData.append('target', fTarget)
      if (fProduct) formData.append('product', fProduct)
      if (fPlugin) formData.append('select_plugin', fPlugin)
      if (fResult) formData.append('result', fResult)
      if (fCreatime) formData.append('creatime', fCreatime)
      const r = await postFormBlob('/api/v1/auto-exp-results/download', formData)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'exp_result.csv'; a.click()
      URL.revokeObjectURL(url)
    }
  }

  function doSearch() { setPage(1); loadList() }

  const columns: ColumnsType<AutoExpResultItem> = [
    ...(canWrite ? [{
      title: <input type="checkbox" onChange={toggleAll} checked={data ? data.items.length > 0 && data.items.every(i => selected.has(i.id)) : false} /> as any,
      key: 'select',
      width: 40,
      render: (_: any, record: AutoExpResultItem) => (
        <input type="checkbox" checked={selected.has(record.id)} onChange={() => toggleSelect(record.id)} />
      ),
    }] : []),
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: 'Task ID', dataIndex: 'task_id', key: 'task_id', width: 80 },
    { title: '目标', dataIndex: 'target', key: 'target', width: 200, ellipsis: true },
    { title: '产品', dataIndex: 'product', key: 'product', width: 120 },
    {
      title: '插件', dataIndex: 'plugin_name', key: 'plugin_name', width: 200, ellipsis: true,
      render: (v: string) => <span title={v}>{v.length > 40 ? v.slice(0, 40) + '...' : v}</span>,
    },
    {
      title: '结果', dataIndex: 'result', key: 'result', width: 200, ellipsis: true,
      render: (v: string) => {
        if (!v) return '-'
        const truncated = v.length > 60 ? v.slice(0, 60) + '...' : v
        return (
          <a onClick={() => {
            const w = window.open('', '_blank')
            if (w) { w.document.title = '结果详情'; const s = w.document.createElement('style'); s.textContent = 'body{font-family:monospace;font-size:13px;padding:20px;white-space:pre-wrap;word-break:break-all;line-height:1.5;max-width:1200px;margin:0 auto;background:#fafaf9;color:#1c1917}'; w.document.head.appendChild(s); w.document.body.textContent = v }
          }} style={{ cursor: 'pointer' }}>
            {truncated}
          </a>
        )
      },
    },
    { title: '创建时间', dataIndex: 'creatime', key: 'creatime', width: 130, render: (v: string | null) => timeNoSec(v), ellipsis: true },
    ...(canWrite ? [{
      title: '操作', key: 'actions', width: 80,
      render: (_: any, record: AutoExpResultItem) => (
        <a onClick={() => deleteOne(record.id)} style={{ cursor: 'pointer', color: 'var(--danger)', fontSize: 12 }}>删除</a>
      ),
    }] : []),
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>自动扫描漏洞结果</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <Input value={fId} onChange={e => setFId(e.target.value)} placeholder="ID" style={{ width: 80 }} onPressEnter={doSearch} />
          <Input value={fTarget} onChange={e => setFTarget(e.target.value)} placeholder="目标" style={{ width: 160 }} onPressEnter={doSearch} />
          <Input value={fProduct} onChange={e => setFProduct(e.target.value)} placeholder="产品" style={{ width: 120 }} onPressEnter={doSearch} />
          <Input value={fPlugin} onChange={e => setFPlugin(e.target.value)} placeholder="插件" style={{ width: 220 }} onPressEnter={doSearch} />
          <Input value={fResult} onChange={e => setFResult(e.target.value)} placeholder="结果" style={{ width: 120 }} onPressEnter={doSearch} />
          <Input value={fCreatime} onChange={e => setFCreatime(e.target.value)} placeholder="日期(如2025-01-01)" style={{ width: 160 }} onPressEnter={doSearch} />
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
              <Table<AutoExpResultItem>
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
    </div>
  )
}

export default AutoExpResultListPage
