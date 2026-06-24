import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Input, Button, Select, Switch, Pagination, Alert, Modal, Form, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { get, post, buildQuery, ApiError } from '../api'
import type {
  EngineItem,
  EngineListResponse,
  EngineFormState,
  EngineDetailResponse,
  EngineDefaults,
} from '../types/engine'
import type { ChoiceOption } from '../types'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
  csrfToken?: string
}

export default function EngineListPage({ apiUrl, csrfToken: _csrfToken }: Props) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '10'))
  const [data, setData] = useState<EngineListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [modalOpen, setModalOpen] = useState(false)
  const [engineTypeChoices, setEngineTypeChoices] = useState<ChoiceOption[]>([])
  const [engineDefaults, setEngineDefaults] = useState<Record<string, EngineDefaults>>({})
  const [proxyChoices, setProxyChoices] = useState<ChoiceOption[]>([])
  const mountedRef = useRef(false)

  const [form, setForm] = useState<EngineFormState>({
    engine_type: 'fofa',
    api_base_url: '',
    account_email: '',
    api_key: '',
    use_proxy: false,
    proxy: '',
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
      const result = await get<EngineListResponse>(`${apiUrl}?${query}`)
      if (mountedRef.current) {
        setData(result)
        if (result.engine_type_choices) setEngineTypeChoices(result.engine_type_choices)
        if (result.engine_defaults) setEngineDefaults(result.engine_defaults)
        if (result.proxy_choices) setProxyChoices(result.proxy_choices)
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
    const initialType = data?.engine_type_choices[0]?.value ? String(data.engine_type_choices[0].value) : 'fofa'
    const def = engineDefaults[initialType]
    setForm({
      engine_type: initialType,
      api_base_url: def?.api_base_url || '',
      account_email: '',
      api_key: '',
      use_proxy: false,
      proxy: '',
      remark: '',
    })
    setFormErrors({})
  }, [data, engineDefaults])

  useEffect(() => {
    if (data && !form.id && !form.api_base_url) {
      resetForm()
    }
  }, [data, form.id, form.api_base_url, resetForm])

  const loadDetail = async (id: number) => {
    setFormErrors({})
    try {
      const result = await get<EngineDetailResponse>(`/api/v1/cyberspace-engines/${id}`)
      if (!result.status) return
      if (mountedRef.current) {
        setForm({
          id: result.data.id,
          engine_type: result.data.engine_type,
          api_base_url: result.data.api_base_url,
          account_email: result.data.account_email ?? '',
          api_key: result.data.api_key,
          use_proxy: result.data.use_proxy,
          proxy: result.data.proxy ? String(result.data.proxy) : '',
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
    const url = isEdit ? `/api/v1/cyberspace-engines/${form.id}/update` : '/api/v1/cyberspace-engines/create'
    const body = {
      engine_type: form.engine_type,
      api_base_url: form.api_base_url,
      account_email: form.account_email,
      api_key: form.api_key,
      use_proxy: form.use_proxy,
      proxy: form.proxy ? Number(form.proxy) : null,
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

  const engineTypeOpts = engineTypeChoices.length > 0 ? engineTypeChoices : (data?.engine_type_choices || [])
  const proxyOpts = proxyChoices.length > 0 ? proxyChoices : (data?.proxy_choices || [])

  const columns: ColumnsType<EngineItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '引擎', dataIndex: 'engine_type', key: 'engine_type', width: 120 },
    { title: 'API地址', dataIndex: 'api_base_url', key: 'api_base_url', width: 200, ellipsis: true },
    { title: '账户邮箱', dataIndex: 'account_email', key: 'account_email', width: 150, render: (val: string) => val || '-' },
    {
      title: '使用代理', dataIndex: 'use_proxy', key: 'use_proxy', width: 80,
      render: (val: boolean) => val ? '是' : '否',
    },
    { title: '代理', dataIndex: 'proxy_label', key: 'proxy_label', width: 120, render: (val: string) => val || '-' },
    { title: '备注', dataIndex: 'remark', key: 'remark', width: 120, render: (val: string) => val || '-' },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: EngineItem) => (
        canWrite ? <Button type="link" onClick={() => loadDetail(record.id)}>编辑</Button> : null
      ),
    },
  ]

  function confirmBatchDelete() {
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个引擎？`, content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个引擎`); setSelectedIds(new Set()); load() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>测绘引擎列表</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && <Button type="primary" onClick={openCreate}>新增引擎</Button>}
            {canWrite && selectedIds.size > 0 && <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>}
          </div>
        </div>

        <div className="react-filter-bar react-filter-bar-simple">
          <Input
            value={q}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQ(e.target.value)}
            onPressEnter={handleSearch}
            placeholder="搜索引擎 / API / 邮箱"
            style={{ width: 240 }}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
        </div>

        <Modal
          title={form.id ? '编辑引擎设置' : '新增引擎设置'}
          open={modalOpen}
          onOk={submitForm}
          onCancel={() => { setModalOpen(false); resetForm() }}
          confirmLoading={submitting}
          okText={form.id ? '保存' : '创建'}
          cancelText="取消"
          width={560}
          destroyOnClose
        >
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="引擎类型">
              <Select
                value={form.engine_type}
                onChange={(val: string) => {
                  const def = engineDefaults[val]
                  setForm((f) => ({
                    ...f,
                    engine_type: val,
                    api_base_url: def?.api_base_url || f.api_base_url,
                    account_email: def?.needs_email === false ? '' : f.account_email,
                  }))
                }}
                style={{ width: '100%' }}
              >
                {engineTypeOpts.map((c) => (
                  <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="API地址" help={formErrors.api_base_url ? <span className="react-error-text">{formErrors.api_base_url}</span> : undefined}>
              <Input
                value={form.api_base_url}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, api_base_url: e.target.value }))}
              />
            </Form.Item>
            {(engineDefaults[form.engine_type]?.needs_email !== false) && (
              <Form.Item label="账户邮箱" help={formErrors.account_email ? <span className="react-error-text">{formErrors.account_email}</span> : undefined}>
                <Input
                  value={form.account_email}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, account_email: e.target.value }))}
                />
              </Form.Item>
            )}
            <Form.Item label="API Key" help={formErrors.api_key ? <span className="react-error-text">{formErrors.api_key}</span> : undefined}>
              <Input
                value={form.api_key}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, api_key: e.target.value }))}
              />
            </Form.Item>
            <Form.Item label="代理" help={formErrors.proxy ? <span className="react-error-text">{formErrors.proxy}</span> : undefined}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Switch
                  checked={form.use_proxy}
                  onChange={(checked: boolean) => setForm((f) => ({ ...f, use_proxy: checked }))}
                  size="small"
                />
                <span style={{ fontSize: 12, whiteSpace: 'nowrap' }}>使用代理</span>
                <Select
                  value={form.proxy || undefined}
                  onChange={(val: string) => setForm((f) => ({ ...f, proxy: val || '' }))}
                  placeholder="不选择"
                  style={{ width: 200 }}
                  allowClear
                  disabled={!form.use_proxy}
                  size="small"
                >
                  {proxyOpts.map((c) => (
                    <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>
                  ))}
                </Select>
              </div>
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
          <div className="react-shell-panel"><span>正在加载引擎列表...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<EngineItem>
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
