import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Input, Button, Pagination, Alert, Modal, message, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { get, post, del, buildQuery, ApiError , timeNoSec} from '../api'
import type {
  FingerprintItem,
  FingerprintListResponse,
  FingerprintFormState,
  FingerprintDetailResponse,
  FingerprintPluginItem,
  FingerprintPluginsResponse,
} from '../types/fingerprint'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../contexts/AuthContext'

const { TextArea } = Input

interface Props {
  apiUrl: string
  csrfToken?: string
}

export default function FingerprintListPage({ apiUrl, csrfToken: _csrfToken }: Props) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '10'))
  const [data, setData] = useState<FingerprintListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [formModal, setFormModal] = useState(false)
  // 关联插件弹窗
  const [pluginModal, setPluginModal] = useState(false)
  const [pluginModalFpId, setPluginModalFpId] = useState<number | null>(null)
  const [pluginData, setPluginData] = useState<FingerprintPluginsResponse | null>(null)
  const [pluginLoading, setPluginLoading] = useState(false)
  const [pluginSearch, setPluginSearch] = useState('')
  const [pluginPage, setPluginPage] = useState(1)
  const mountedRef = useRef(false)

  const [form, setForm] = useState<FingerprintFormState>({
    product: '',
    condition: '',
  })

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

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
      const result = await get<FingerprintListResponse>(`${apiUrl}?${query}`)
      if (mountedRef.current) setData(result)
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof ApiError ? err.message : '加载失败')
      }
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [apiUrl, q, page, rowsPerPage])

  useEffect(() => {
    load()
  }, [load])

  const resetForm = useCallback(() => {
    setForm({ product: '', condition: '' })
    setFormErrors({})
  }, [])

  function openAdd() {
    resetForm()
    setFormModal(true)
  }

  const openEdit = async (id: number) => {
    setFormErrors({})
    try {
      const result = await get<FingerprintDetailResponse>(`/api/v1/fingerprints/${id}`)
      if (!result.status) return
      if (mountedRef.current) {
        setForm({
          id: result.data.id,
          product: result.data.product,
          condition: result.data.condition,
        })
        setFormModal(true)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '获取详情失败')
    }
  }

  const submitForm = async () => {
    setSubmitting(true)
    setFormErrors({})
    const isEdit = !!form.id
    const url = isEdit ? `/api/v1/fingerprints/${form.id}/update` : '/api/v1/fingerprints/create'
    const body = {
      product: form.product,
      condition: form.condition,
    }

    try {
      await post(url, body)
      if (mountedRef.current) {
        message.success(isEdit ? '保存成功' : '创建成功')
        setFormModal(false)
        resetForm()
        await load()
      }
    } catch (err) {
      if (err instanceof ApiError && err.errors) {
        setFormErrors(err.errors)
      } else {
        setFormErrors({ form: err instanceof ApiError ? err.message : '保存失败' })
      }
    } finally {
      if (mountedRef.current) setSubmitting(false)
    }
  }

  const handleSearch = () => {
    setPage(1)
    load()
  }

  // ---- 关联插件弹窗 ----
  async function openPluginModal(fpId: number) {
    setPluginModalFpId(fpId)
    setPluginSearch('')
    setPluginPage(1)
    setPluginModal(true)
    await loadPlugins(fpId, 1, '')
  }

  async function loadPlugins(fpId: number, p: number, q: string) {
    setPluginLoading(true)
    try {
      const qs = buildQuery({ q: q || undefined, page: p, rows_per_page: 10 })
      const result = await get<FingerprintPluginsResponse>(`/api/v1/fingerprints/${fpId}/plugins?${qs}`)
      setPluginData(result)
    } catch {
      setPluginData(null)
    } finally {
      setPluginLoading(false)
    }
  }

  async function addPluginToFingerprint(expId: number) {
    try {
      await post(`/api/v1/fingerprints/${pluginModalFpId}/plugins`, { exp_id: expId })
      message.success('已添加关联')
      // 刷新弹窗内列表 + 主列表
      if (pluginModalFpId) await loadPlugins(pluginModalFpId, pluginPage, pluginSearch)
      await load()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '添加失败')
    }
  }

  async function removePluginFromFingerprint(expId: number) {
    try {
      await del(`/api/v1/fingerprints/${pluginModalFpId}/plugins/${expId}`)
      message.success('已删除关联')
      if (pluginModalFpId) await loadPlugins(pluginModalFpId, pluginPage, pluginSearch)
      await load()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  function handlePluginSearch() {
    setPluginPage(1)
    if (pluginModalFpId) loadPlugins(pluginModalFpId, 1, pluginSearch)
  }

  function handlePluginPageChange(p: number) {
    setPluginPage(p)
    if (pluginModalFpId) loadPlugins(pluginModalFpId, p, pluginSearch)
  }

  const columns: ColumnsType<FingerprintItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '产品', dataIndex: 'product', key: 'product', width: 120 },
    { title: '匹配条件', dataIndex: 'condition', key: 'condition', width: 200, ellipsis: true },
    {
      title: '关联插件',
      dataIndex: 'exp_count',
      key: 'exp_count',
      width: 90,
      render: (val: number, record: FingerprintItem) => (
        canWrite ? <a onClick={() => openPluginModal(record.id)} style={{ cursor: 'pointer' }}>
          {val || 0}
        </a> : <span>{val || 0}</span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at', width: 130,
      render: (val: string) => timeNoSec(val) || '-', ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: FingerprintItem) => (
        canWrite ? <Button type="link" onClick={() => openEdit(record.id)}>编辑</Button> : null
      ),
    },
  ]

  function confirmBatchDelete() {
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个指纹？`, content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个指纹`); setSelectedIds(new Set()); load() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>指纹列表</h2>
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
            placeholder="搜索产品或条件"
            style={{ width: 240 }}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
        </div>

        {error && (
          <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} closable onClose={() => setError(null)} />
        )}

        {loading ? (
          <div className="react-shell-panel"><span>正在加载指纹列表...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<FingerprintItem>
                columns={columns}
                dataSource={data?.items || []}
                rowKey="id"
                rowSelection={canWrite ? { selectedRowKeys: Array.from(selectedIds), onChange: (keys) => setSelectedIds(new Set(keys as number[])) } : undefined}
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
          title={form.id ? '编辑指纹' : '新增指纹'}
          open={formModal}
          onCancel={() => setFormModal(false)}
          footer={null}
          destroyOnClose
          width={720}
        >
          <div className="react-form-grid" style={{ marginTop: 8 }}>
            <label>
              产品
              <Input
                value={form.product}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, product: e.target.value }))}
              />
              {formErrors.product ? <span className="react-error-text">{formErrors.product}</span> : null}
            </label>
            <label style={{ gridColumn: '1 / -1' }}>
              匹配条件
              <TextArea
                value={form.condition}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setForm((f) => ({ ...f, condition: e.target.value }))}
                rows={4}
              />
              {formErrors.condition ? <span className="react-error-text">{formErrors.condition}</span> : null}
            </label>
          </div>
          {formErrors.form ? <div className="react-error-box" style={{ marginTop: 12 }}>{formErrors.form}</div> : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
            <Button onClick={() => setFormModal(false)}>取消</Button>
            <Button type="primary" onClick={submitForm} loading={submitting}>
              {submitting ? '提交中...' : form.id ? '保存修改' : '新增指纹'}
            </Button>
          </div>
        </Modal>

        {/* 关联插件弹窗 */}
        <Modal
          title="关联插件管理"
          open={pluginModal}
          onCancel={() => setPluginModal(false)}
          footer={null}
          destroyOnClose
          width={900}
        >
          <div style={{ marginBottom: 12 }}>
            <Input.Search
              value={pluginSearch}
              onChange={(e) => setPluginSearch(e.target.value)}
              onSearch={handlePluginSearch}
              placeholder="搜索插件名或CVE..."
              enterButton="搜索"
              style={{ maxWidth: 400 }}
            />
          </div>

          <div className="react-task-table-wrap" style={{ marginBottom: 12 }}>
            <Table<FingerprintPluginItem>
              columns={[
                { title: '插件名', dataIndex: 'title', key: 'title', width: 200, ellipsis: true },
                { title: 'CVE', dataIndex: 'CVE', key: 'CVE', width: 140, render: (v: string) => v || '—' },
                { title: '类型', dataIndex: 'type_label', key: 'type_label', width: 120 },
                {
                  title: '危害等级', dataIndex: 'severity_label', key: 'severity_label', width: 90,
                  render: (v: string) => v ? <Tag color={v === 'critical' ? 'red' : v === 'high' ? 'orange' : 'blue'}>{v}</Tag> : '—',
                },
                {
                  title: '操作', key: 'action', width: 60,
                  render: (_: unknown, record: FingerprintPluginItem) => (
                    canWrite ? <Button type="link" danger size="small" onClick={() => {
                      Modal.confirm({
                        title: '确认删除', content: `确定移除插件"${record.title}"的关联？`, okText: '删除', okType: 'danger', cancelText: '取消',
                        onOk: () => removePluginFromFingerprint(record.id),
                      })
                    }}>删除</Button> : null
                  ),
                },
              ]}
              dataSource={pluginData?.items || []}
              rowKey="id"
              loading={pluginLoading}
              pagination={false}
              size="small"
            />
          </div>

          <div className="react-pagination-bar">
            <span>第 {pluginData?.page ?? 1} / {pluginData?.total_pages ?? 1} 页，共 {pluginData?.total ?? 0} 条</span>
            <Pagination
              current={pluginData?.page || 1}
              total={pluginData?.total || 0}
              pageSize={pluginData?.rows_per_page || 10}
              onChange={handlePluginPageChange}
              showSizeChanger={false}
            />
          </div>

          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 12 }}>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 4 }}>搜索结果（点击添加）：</div>
            {pluginSearch.trim() ? (
              <SearchPluginResults
                search={pluginSearch}
                excludeIds={(pluginData?.items || []).map((p) => p.id)}
                onAdd={(id) => {
                  Modal.confirm({
                    title: '确认关联', content: '确定将此插件关联到当前指纹？', okText: '确定', cancelText: '取消',
                    onOk: () => addPluginToFingerprint(id),
                  })
                }}
              />
            ) : (
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>在上方搜索框输入关键字搜索要添加的插件</div>
            )}
          </div>
        </Modal>
      </div>
    </div>
  )
}

// 搜索插件结果组件（独立组件，避免复杂状态在主组件中）
function SearchPluginResults({ search, excludeIds, onAdd }: { search: string; excludeIds: number[]; onAdd: (id: number) => void }) {
  const [results, setResults] = useState<FingerprintPluginItem[]>([])
  const [searching, setSearching] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!search.trim()) { setResults([]); return }
    setSearching(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      try {
        const qs = buildQuery({ q: search, page: 1, rows_per_page: 20 })
        // 搜索全部插件用 plugins 列表 API
        const result = await get<{ items: { id: number; title: string; CVE: string; type_label: string; severity_label: string }[] }>(`/api/v1/plugins?${qs}`)
        setResults((result.items || []).filter((p) => !excludeIds.includes(p.id)))
      } catch { setResults([]) }
      finally { setSearching(false) }
    }, 300)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [search, excludeIds])

  if (searching) return <div style={{ padding: 8, fontSize: 12, color: 'var(--text-dim)' }}>搜索中...</div>
  if (!results.length) return <div style={{ padding: 8, fontSize: 12, color: 'var(--text-dim)' }}>无匹配结果</div>
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 6, maxHeight: 200, overflow: 'auto' }}>
      {results.map((p) => (
        <div
          key={p.id}
          onClick={() => onAdd(p.id)}
          style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}
          onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'var(--bg-elevated)' }}
          onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'transparent' }}
        >
          <span>{p.title}{p.CVE ? ` (${p.CVE})` : ''}</span>
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{p.type_label}</span>
        </div>
      ))}
    </div>
  )
}
