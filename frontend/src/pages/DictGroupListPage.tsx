import React, { useState, useEffect, useCallback } from 'react'
import { Table, Input, Button, Space, Pagination, Modal, Alert, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { get, post, postForm, buildQuery, ApiError , timeNoSec} from '../api'
import type { DictGroupItem, DictGroupListResponse } from '../types/dict'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
}

export default function DictGroupListPage({ apiUrl }: Props) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '13'))
  const [data, setData] = useState<DictGroupListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formModal, setFormModal] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [formName, setFormName] = useState('')
  const [formDesc, setFormDesc] = useState('')
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    params.set('page', String(page))
    params.set('rows_per_page', String(rowsPerPage))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)

    setLoading(true)
    setError(null)
    try {
      const query = buildQuery({ q: q || undefined, page, rows_per_page: rowsPerPage })
      const result = await get<DictGroupListResponse>(`${apiUrl}?${query}`)
      setData(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [apiUrl, q, page, rowsPerPage])

  useEffect(() => { load() }, [load])

  const openAdd = () => {
    setEditId(null)
    setFormName('')
    setFormDesc('')
    setFormError('')
    setFormModal(true)
  }

  const openEdit = async (id: number) => {
    setFormError('')
    try {
      const result = await get<{ status: boolean; data: { id: number; name: string; description: string } }>(`/api/v1/dict-groups/${id}`)
      if (!result.status) {
        setFormError('加载失败')
        return
      }
      setEditId(result.data.id)
      setFormName(result.data.name)
      setFormDesc(result.data.description)
      setFormModal(true)
    } catch (_err) {
      setFormError('加载失败')
    }
  }

  const submitForm = async () => {
    if (!formName.trim()) {
      setFormError('组名不能为空')
      return
    }
    setSubmitting(true)
    setFormError('')
    const isEdit = editId !== null
    const url = isEdit ? `/api/v1/dict-groups/${editId}/update` : '/api/v1/dict-groups/create'
    const formData = new FormData()
    formData.append('name', formName.trim())
    formData.append('description', formDesc.trim())

    try {
      const payload = await postForm<{ status: boolean; error?: string; errors?: Record<string, string> }>(url, formData)
      setSubmitting(false)
      if (!payload.status) {
        setFormError(payload.errors ? JSON.stringify(payload.errors) : (payload.error ?? '保存失败'))
        return
      }
      setFormModal(false)
      await load()
    } catch (_err) {
      setSubmitting(false)
      setFormError('保存失败')
    }
  }

  const deleteOne = async (id: number) => {
    if (!confirm('确认删除该字典组？')) return
    setSubmitting(true)
    try {
      const payload = await postForm<{ status: boolean }>(`/api/v1/dict-groups/${id}/delete`, new FormData())
      setSubmitting(false)
      if (!payload.status) {
        message.error('删除失败')
        return
      }
      message.success('删除成功')
      await load()
    } catch (_err) {
      setSubmitting(false)
      message.error('删除失败')
    }
  }

  const handleSearch = () => {
    setPage(1)
    load()
  }

  const columns: ColumnsType<DictGroupItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '组名', dataIndex: 'name', key: 'name', width: 160 },
    { title: '描述', dataIndex: 'description', key: 'description', width: 200, render: (val: string) => val || '-' },
    { title: '创建时间', dataIndex: 'creatime', key: 'creatime', width: 130, render: (v: string | null) => timeNoSec(v), ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: DictGroupItem) => (
        <Space>
          {canWrite && <Button onClick={() => openEdit(record.id)} disabled={submitting}>编辑</Button>}
          {canWrite && <Button onClick={() => deleteOne(record.id)} disabled={submitting}>删除</Button>}
        </Space>
      ),
    },
  ]

  const items = data?.items ?? []
  function confirmBatchDelete() {
    if (selectedIds.size === 0) return
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个字典组？`, content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个字典组`); setSelectedIds(new Set()); load() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>字典组管理</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && selectedIds.size > 0 && <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>}
            {canWrite && <Button type="primary" onClick={openAdd}>新增</Button>}
          </div>
        </div>

        <div className="react-filter-bar react-filter-bar-simple">
          <Input
            value={q}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQ(e.target.value)}
            onPressEnter={handleSearch}
            placeholder="搜索组名或描述"
            style={{ minWidth: 200 }}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
        </div>

        {error && (
          <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} closable onClose={() => setError(null)} />
        )}

        {loading ? (
          <div className="react-shell-panel"><span>加载中...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<DictGroupItem>
                columns={columns}
                dataSource={data?.items || []}
                rowSelection={canWrite ? { selectedRowKeys: Array.from(selectedIds), onChange: (keys) => setSelectedIds(new Set(keys as number[])) } : undefined}
                rowKey="id"
                loading={loading}
                pagination={false}
                size="small"
              />
            </div>

            <div className="react-pagination-bar">
              <span>
                第 {data?.page ?? 1} / {data?.total_pages ?? 1} 页，共 {data?.total ?? 0} 条
              </span>
              <Pagination
                showQuickJumper
                current={data?.page || 1}
                total={data?.total || 0}
                pageSize={data?.rows_per_page || rowsPerPage}
                onChange={(p: number) => setPage(p)}
                showSizeChanger={false}
              />
            </div>
          </>
        )}

        <Modal
          title={`${editId ? '编辑' : '新增'}字典组`}
          open={formModal}
          onCancel={() => setFormModal(false)}
          footer={null}
          destroyOnClose
        >
          <div className="react-form-grid" style={{ marginTop: 8 }}>
            <label>
              组名
              <Input
                value={formName}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormName(e.target.value)}
              />
            </label>
            <label>
              描述
              <Input
                value={formDesc}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormDesc(e.target.value)}
              />
            </label>
          </div>
          {formError ? <div className="react-error-box" style={{ marginTop: 12 }}>{formError}</div> : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
            <Button onClick={() => setFormModal(false)}>取消</Button>
            <Button type="primary" onClick={submitForm} loading={submitting}>
              {submitting ? '保存中...' : '保存'}
            </Button>
          </div>
        </Modal>
      </div>
    </div>
  )
}
