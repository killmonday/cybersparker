import React, { useState, useEffect, useCallback } from 'react'
import { Input, Button, Modal, Space, message } from 'antd'
import { get, postForm, buildQuery, ApiError , timeNoSec, post } from '../api'
import type { DictItem, DictListResponse, DictGroupItem, DictGroupListResponse } from '../types/dict'
import { useAuth } from '../contexts/AuthContext'

export default function DictListPage({ apiUrl }: { apiUrl: string }) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '10'))
  const [data, setData] = useState<DictListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  // Form modal
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formName, setFormName] = useState('')
  const [formPaths, setFormPaths] = useState('')
  const [formGroupIds, setFormGroupIds] = useState<number[]>([])
  const [groups, setGroups] = useState<DictGroupItem[]>([])
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    params.set('page', String(page))
    params.set('rows_per_page', String(rowsPerPage))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)

    setLoading(true)
    try {
      const query = buildQuery({ q: q || undefined, page, rows_per_page: rowsPerPage })
      const result = await get<DictListResponse>(`${apiUrl}?${query}`)
      setData(result)
    } catch {
      // silently fail
    } finally {
      setLoading(false)
    }
  }, [apiUrl, q, page, rowsPerPage])

  useEffect(() => { load() }, [load])

  function loadGroups() {
    get<DictGroupListResponse>('/api/v1/dict-groups?rows_per_page=1000')
      .then((d) => setGroups(d.items))
      .catch(() => {})
  }

  function openAdd() {
    setEditingId(null)
    setFormName('')
    setFormPaths('')
    setFormGroupIds([])
    setFormError('')
    setModalOpen(true)
    loadGroups()
  }

  function openEdit(id: number) {
    setEditingId(id)
    setFormError('')
    loadGroups()
    get<{ status: boolean; data: { name: string; paths_text: string; groups: number[] } }>(`/api/v1/dicts/${id}`)
      .then(d => {
        if (d.status) {
          setFormName(d.data.name || '')
          setFormPaths(d.data.paths_text || '')
          setFormGroupIds(d.data.groups || [])
          setModalOpen(true)
        } else {
          message.error('获取详情失败')
        }
      })
      .catch(() => { message.error('获取详情失败') })
  }

  async function handleSave() {
    if (!formName.trim()) { setFormError('请输入字典名'); return }
    if (!formPaths.trim()) { setFormError('请输入至少一条路径'); return }
    setSaving(true)
    setFormError('')

    const fd = new FormData()
    fd.append('name', formName.trim())
    fd.append('paths_text', formPaths.trim())
    formGroupIds.forEach(gid => fd.append('groups', String(gid)))

    const url = editingId ? `/api/v1/dicts/${editingId}/update` : '/api/v1/dicts/create'
    try {
      const p = await postForm<{ status: boolean; error?: string | Record<string, string>; tips?: string }>(url, fd)
      setSaving(false)
      if (p.status) {
        setModalOpen(false)
        message.success(editingId ? '修改成功' : '新增成功')
        load()
      } else {
        setFormError(typeof p.error === 'object' ? JSON.stringify(p.error) : (p.error || p.tips || '操作失败'))
      }
    } catch (e) {
      setSaving(false)
      setFormError(e instanceof ApiError ? e.message : '操作失败')
    }
  }

  function toggleSelect(id: number) {
    setSelectedIds(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  }
  function toggleAll() {
    const items = data?.items ?? []
    if (items.length === 0) return
    if (selectedIds.size === items.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(items.map(it => it.id)))
  }
  function confirmBatchDelete() {
    if (selectedIds.size === 0) return
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个字典？`,
      content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个字典`); setSelectedIds(new Set()); load() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  async function handleDelete(id: number) {
    if (!confirm('确认删除该字典？')) return
    try {
      const p = await post<{ status: boolean; error?: string }>(`/api/v1/dicts/${id}/delete`, {})
      if (p.status) { message.success('删除成功'); load() }
      else { message.error(p.error || '删除失败') }
    } catch {
      message.error('删除失败')
    }
  }

  const handleSearch = () => { setPage(1); load() }

  const items = data?.items ?? []

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>字典管理</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && selectedIds.size > 0 && (
              <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>
            )}
            {canWrite && <Button type="primary" onClick={openAdd}>新增字典</Button>}
          </div>
        </div>

        <div className="react-filter-bar react-filter-bar-simple">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索字典名"
            onPressEnter={handleSearch}
            style={{ minWidth: 200 }}
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </div>

        {loading ? (
          <div className="react-shell-panel"><span>正在加载字典列表...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
            <table className="react-table">
              <thead>
                <tr>
                  {canWrite && <th style={{ width: 40 }}><input type="checkbox" checked={items.length > 0 && selectedIds.size === items.length} onChange={toggleAll} /></th>}
                  <th>ID</th>
                  <th>字典名</th>
                  <th>路径数</th>
                  <th>所属组</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((item) => (
                  <tr key={item.id}>
                    {canWrite && <td><input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleSelect(item.id)} /></td>}
                    <td>{item.id}</td>
                    <td>{item.name}</td>
                    <td>{item.path_count}</td>
                    <td>{item.groups.length ? item.groups.join(', ') : '-'}</td>
                    <td>{timeNoSec(item.created_at)}</td>
                    <td>
                      <Space size={4}>
                        {canWrite && <a style={{ cursor: 'pointer', fontSize: 12 }} onClick={() => openEdit(item.id)}>编辑</a>}
                        {canWrite && <a style={{ cursor: 'pointer', color: 'var(--danger)', fontSize: 12 }} onClick={() => handleDelete(item.id)}>删除</a>}
                      </Space>
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
              <div className="react-pagination-actions">
                <input type="number" min={1} max={data?.total_pages ?? 1} placeholder="页" style={{ width: 50, height: 34, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
                  onKeyDown={e => { if (e.key !== 'Enter') return; const n = parseInt((e.target as HTMLInputElement).value, 10); if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n) }} />
                <Button onClick={() => { const inp = document.querySelector('.react-pagination-bar input[type="number"]') as HTMLInputElement; if (inp) { const n = parseInt(inp.value, 10); if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n) } }}>跳转</Button>
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

      {/* Add/Edit Modal */}
      <Modal
        title={editingId ? '编辑字典' : '新增字典'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={560}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <label>
            <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>字典名</span>
            <Input value={formName} onChange={e => setFormName(e.target.value)} placeholder="输入字典名称" />
          </label>
          <label>
            <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>所属组</span>
            <div style={{ maxHeight: 150, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px' }}>
              {groups.length === 0 ? <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>加载中…</span> : groups.map(g => (
                <label key={g.id} style={{ display: 'block', fontSize: 13, padding: '2px 0', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={formGroupIds.includes(g.id)}
                    onChange={e => {
                      if (e.target.checked) setFormGroupIds(prev => [...prev, g.id])
                      else setFormGroupIds(prev => prev.filter(id => id !== g.id))
                    }}
                    style={{ marginRight: 6 }}
                  />
                  {g.name}
                </label>
              ))}
            </div>
          </label>
          <label>
            <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>路径列表（每行一条）</span>
            <Input.TextArea
              value={formPaths}
              onChange={e => setFormPaths(e.target.value)}
              placeholder={'每行一条路径，例如：\n/admin\n/login\n/robots.txt'}
              rows={10}
            />
          </label>
          {formError ? <div className="react-error-box">{formError}</div> : null}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button onClick={() => setModalOpen(false)}>取消</Button>
            <Button type="primary" onClick={handleSave} loading={saving}>
              {saving ? '保存中…' : '保存'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
