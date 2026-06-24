import React, { useState, useEffect, useCallback } from 'react'
import { Input, Button, Select, Modal, message } from 'antd'
import { get, post, buildQuery } from '../api'
import type { PluginItem, PluginListResponse } from '../types/plugin'
import { useAuth } from '../contexts/AuthContext'

export default function PluginListPage({ apiUrl }: { apiUrl: string }) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [severity, setSeverity] = useState(search.get('severity') ?? '')
  const [tag, setTag] = useState(search.get('tag') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '10'))
  const [data, setData] = useState<PluginListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (severity) params.set('severity', severity)
    if (tag) params.set('tag', tag)
    params.set('page', String(page))
    params.set('rows_per_page', String(rowsPerPage))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)

    setLoading(true)
    try {
      const query = buildQuery({ q: q || undefined, severity: severity || undefined, tag: tag || undefined, page, rows_per_page: rowsPerPage })
      const result = await get<PluginListResponse>(`${apiUrl}?${query}`)
      setData(result)
    } catch {
      // silently fail
    } finally {
      setLoading(false)
    }
  }, [apiUrl, q, severity, tag, page, rowsPerPage])

  useEffect(() => { load() }, [load])

  const handleSearch = () => {
    setPage(1)
  }

  useEffect(() => {
    load()
  }, [page, q, severity, tag, load])

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    const items = data?.items ?? []
    if (items.length === 0) return
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(items.map((it) => it.id)))
    }
  }

  function confirmDelete() {
    if (selectedIds.size === 0) return
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个插件？`,
      content: '删除后无法恢复。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }

  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(
        `${apiUrl}/batch-delete`,
        { uids: Array.from(selectedIds) },
      )
      if (res.status) {
        message.success(`已删除 ${selectedIds.size} 个插件`)
        setSelectedIds(new Set())
        load()
      } else {
        message.error(res.tips || '删除失败')
      }
    } catch {
      message.error('删除请求失败')
    } finally {
      setDeleting(false)
    }
  }

  const items = data?.items ?? []

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>插件列表</h2>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {canWrite && selectedIds.size > 0 && (
              <Button danger loading={deleting} onClick={confirmDelete}>
                删除选中 ({selectedIds.size})
              </Button>
            )}
          </div>
        </div>

        <div className="react-filter-bar">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索标题 / CVE"
            onPressEnter={handleSearch}
            style={{ minWidth: 160 }}
          />
          <Select
            value={severity || undefined}
            onChange={(v) => { setSeverity(v ?? ''); setPage(1); }}
            placeholder="全部等级"
            style={{ minWidth: 120 }}
            allowClear
            options={data?.severity_choices.map((choice) => ({ value: choice.value, label: choice.label })) ?? []}
          />
          <Input
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="标签搜索"
            onPressEnter={handleSearch}
            style={{ minWidth: 120 }}
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </div>

        {loading ? (
          <div className="react-shell-panel"><span>正在加载插件列表...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
            <table className="react-table">
              <thead>
                <tr>
                  {canWrite && <th style={{ width: 40 }}>
                    <input type="checkbox"
                      checked={items.length > 0 && selectedIds.size === items.length}
                      onChange={toggleAll}
                    />
                  </th>}
                  <th>ID</th>
                  <th>标题</th>
                  <th>CVE</th>
                  <th>等级</th>
                  <th>语言</th>
                  <th>状态</th>
                  <th>类型</th>
                  <th>标签</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    {canWrite && <td>
                      <input type="checkbox"
                        checked={selectedIds.has(item.id)}
                        onChange={() => toggleSelect(item.id)}
                      />
                    </td>}
                    <td>{item.id}</td>
                    <td>
                      <a href={`/react-shell/exp-debug?plugin_id=${item.id}`} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {item.title}
                      </a>
                    </td>
                    <td>{item.CVE || '-'}</td>
                    <td>{item.severity_label}</td>
                    <td>{item.plugin_language_label}</td>
                    <td>{item.use_label}</td>
                    <td>{item.type_label}</td>
                    <td>{item.tags.length ? item.tags.join(', ') : '-'}</td>
                    <td>
                      <a href={`/react-shell/plugins/${item.id}`} className="react-inline-link">
                        详情
                      </a>
                      {canWrite && <a href={`/react-shell/exp-debug?plugin_id=${item.id}`} className="react-inline-link" style={{ marginLeft: 12 }} target="_blank">
                        编辑
                      </a>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>

            <div className="react-pagination-bar">
              <span>
                第 {data?.page ?? 1} / {data?.total_pages ?? 1} 页，共 {data?.total ?? 0} 条
              </span>
              <div className="react-pagination-actions" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input
                  type="number"
                  min={1}
                  max={data?.total_pages ?? 1}
                  placeholder="页"
                  style={{ width: 50, height: 34, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
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
                <Button disabled={(data?.page ?? 1) <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
                  上一页
                </Button>
                <Button
                  disabled={!data || data.page >= data.total_pages}
                  onClick={() => setPage((current) => current + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
