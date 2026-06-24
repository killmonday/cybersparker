import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Input, Button, Select, Pagination, Alert, Modal, Form, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { get, post, buildQuery, ApiError , timeNoSec} from '../api'
import type {
  ProxyItem,
  ProxyListResponse,
  ProxyFormState,
  ProxyDetailResponse,
  ProxyTypeChoice,
} from '../types/proxy'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
  csrfToken?: string
}

export default function ProxyListPage({ apiUrl, csrfToken: _csrfToken }: Props) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '10'))
  const [data, setData] = useState<ProxyListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [proxyTypeChoices, setProxyTypeChoices] = useState<ProxyTypeChoice[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const mountedRef = useRef(false)

  const [form, setForm] = useState<ProxyFormState>({
    proxy_type: '1',
    proxy_address: '',
    proxy_port: '',
    remark: '',
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
      const result = await get<ProxyListResponse>(`${apiUrl}?${query}`)
      if (mountedRef.current) {
        setData(result)
        if (result.proxy_type_choices) setProxyTypeChoices(result.proxy_type_choices)
      }
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
    setForm({
      proxy_type: data?.proxy_type_choices[0]?.value ? String(data.proxy_type_choices[0].value) : '1',
      proxy_address: '',
      proxy_port: '',
      remark: '',
    })
    setFormErrors({})
  }, [data])

  useEffect(() => {
    if (data && !form.id && !form.proxy_address) {
      resetForm()
    }
  }, [data, form.id, form.proxy_address, resetForm])

  const loadDetail = async (id: number) => {
    setFormErrors({})
    try {
      const result = await get<ProxyDetailResponse>(`/api/v1/proxies/${id}`)
      if (!result.status) return
      if (mountedRef.current) {
        setForm({
          id: result.data.id,
          proxy_type: String(result.data.proxy_type),
          proxy_address: result.data.proxy_address,
          proxy_port: String(result.data.proxy_port),
          remark: result.data.remark ?? '',
        })
        setModalOpen(true)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '获取详情失败')
    }
  }

  const openCreate = () => {
    resetForm()
    setModalOpen(true)
  }

  const submitForm = async () => {
    setSubmitting(true)
    setFormErrors({})
    const isEdit = !!form.id
    const url = isEdit ? `/api/v1/proxies/${form.id}/update` : '/api/v1/proxies/create'
    const body = {
      proxy_type: Number(form.proxy_type),
      proxy_address: form.proxy_address,
      proxy_port: Number(form.proxy_port),
      remark: form.remark,
    }

    try {
      await post(url, body)
      if (mountedRef.current) {
        message.success(isEdit ? '保存成功' : '创建成功')
        setModalOpen(false)
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

  const columns: ColumnsType<ProxyItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '代理类型', dataIndex: 'proxy_type_label', key: 'proxy_type_label', width: 80 },
    { title: '代理地址', dataIndex: 'proxy_address', key: 'proxy_address', width: 150 },
    { title: '代理端口', dataIndex: 'proxy_port', key: 'proxy_port', width: 80 },
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
      render: (_: unknown, record: ProxyItem) => (
        canWrite ? <Button type="link" onClick={() => loadDetail(record.id)}>编辑</Button> : null
      ),
    },
  ]

  function confirmBatchDelete() {
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个代理？`, content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个代理`); setSelectedIds(new Set()); load() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>代理列表</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && <Button type="primary" onClick={openCreate}>新增代理</Button>}
            {canWrite && selectedIds.size > 0 && <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>}
          </div>
        </div>

        <div className="react-filter-bar react-filter-bar-simple">
          <Input
            value={q}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQ(e.target.value)}
            onPressEnter={handleSearch}
            placeholder="搜索 IP 或端口"
            style={{ width: 240 }}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
        </div>

        <Modal
          title={form.id ? '编辑代理' : '新增代理'}
          open={modalOpen}
          onOk={submitForm}
          onCancel={() => { setModalOpen(false); resetForm() }}
          confirmLoading={submitting}
          okText={form.id ? '保存' : '创建'}
          cancelText="取消"
          width={480}
          destroyOnClose
        >
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="代理类型">
              <Select
                value={form.proxy_type}
                onChange={(val: string) => setForm((f) => ({ ...f, proxy_type: val }))}
                style={{ width: '100%' }}
              >
                {(proxyTypeChoices.length > 0 ? proxyTypeChoices : data?.proxy_type_choices || []).map((c) => (
                  <Select.Option key={c.value} value={String(c.value)}>{c.label}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="代理地址" help={formErrors.proxy_address ? <span className="react-error-text">{formErrors.proxy_address}</span> : undefined}>
              <Input
                value={form.proxy_address}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, proxy_address: e.target.value }))}
              />
            </Form.Item>
            <Form.Item label="代理端口" help={formErrors.proxy_port ? <span className="react-error-text">{formErrors.proxy_port}</span> : undefined}>
              <Input
                value={form.proxy_port}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, proxy_port: e.target.value }))}
              />
            </Form.Item>
            <Form.Item label="备注" help={formErrors.remark ? <span className="react-error-text">{formErrors.remark}</span> : undefined}>
              <Input
                value={form.remark}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, remark: e.target.value }))}
              />
            </Form.Item>
            {formErrors.form ? <div className="react-error-box" style={{ marginBottom: 8 }}>{formErrors.form}</div> : null}
          </Form>
        </Modal>

        {error && (
          <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} closable onClose={() => setError(null)} />
        )}

        {loading ? (
          <div className="react-shell-panel"><span>正在加载代理列表...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<ProxyItem>
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
      </div>
    </div>
  )
}
