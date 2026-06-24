import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Input, Button, Select, Modal, Form, Alert, message } from 'antd'
import { get, post, del, ApiError, timeNoSec } from '../api'
import type { AiModelConfigItem, AiModelConfigListResponse, AiModelConfigFormState } from '../types/aiModelConfig'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../contexts/AuthContext'

const API_URL = '/api/v1/ai-model-configs'

const DEFAULT_FORM: AiModelConfigFormState = {
  name: '',
  model_id: '',
  api_url: '',
  api_key: '',
  model_type: 'thinking',
}

export default function AiModelConfigPage() {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const [data, setData] = useState<AiModelConfigListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState<AiModelConfigFormState>({ ...DEFAULT_FORM })
  const [modelTypeFilter, setModelTypeFilter] = useState<string>('')
  const modelTypeChoices = data?.model_type_choices || []
  const mountedRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (modelTypeFilter) params.set('model_type', modelTypeFilter)
      const qs = params.toString()
      const result = await get<AiModelConfigListResponse>(qs ? `${API_URL}?${qs}` : API_URL)
      if (mountedRef.current) setData(result)
    } catch (err) {
      if (mountedRef.current) setError(err instanceof ApiError ? err.message : '加载失败')
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [modelTypeFilter])

  useEffect(() => { load() }, [load])

  const resetForm = useCallback(() => {
    setForm({ ...DEFAULT_FORM })
    setFormErrors({})
  }, [])

  const loadDetail = async (id: number) => {
    setFormErrors({})
    try {
      const result = await get<{ status: boolean; data: AiModelConfigFormState }>(`${API_URL}/${id}`)
      if (!result.status) return
      // 详情通过列表数据获取（列表已含所有字段），直接查 items
      const item = data?.items?.find((i) => i.id === id)
      if (item && mountedRef.current) {
        setForm({
          id: item.id,
          name: item.name,
          model_id: item.model_id,
          api_url: item.api_url,
          api_key: '',
          model_type: item.model_type as 'thinking' | 'vision',
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
    const url = isEdit ? `${API_URL}/${form.id}` : API_URL
    const body = {
      name: form.name,
      model_id: form.model_id,
      api_url: form.api_url,
      api_key: form.api_key,
      model_type: form.model_type,
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
        const fieldErrors: Record<string, string> = {}
        for (const [k, v] of Object.entries(err.errors)) {
          fieldErrors[k] = String(v ?? '')
        }
        setFormErrors(fieldErrors)
      } else {
        setFormErrors({ form: err instanceof ApiError ? err.message : '保存失败' })
      }
    } finally {
      if (mountedRef.current) setSubmitting(false)
    }
  }

  const handleDelete = async (id: number) => {
    Modal.confirm({
      title: '确定删除该模型配置？',
      content: '删除后不可恢复。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await del(`${API_URL}/${id}`)
          if (mountedRef.current) {
            message.success('已删除')
            await load()
          }
        } catch (err) {
          message.error(err instanceof ApiError ? err.message : '删除失败')
        }
      },
    })
  }

  const columns: ColumnsType<AiModelConfigItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 120 },
    { title: '模型 ID', dataIndex: 'model_id', key: 'model_id', width: 140 },
    { title: 'API 地址', dataIndex: 'api_url', key: 'api_url', width: 200, ellipsis: true },
    { title: 'API Key', dataIndex: 'api_key', key: 'api_key', width: 160 },
    {
      title: '类型', dataIndex: 'model_type_label', key: 'model_type_label', width: 100,
      filters: modelTypeChoices.map((c) => ({ text: c.label, value: c.value })),
      filteredValue: modelTypeFilter ? [modelTypeFilter] : null,
      onFilter: () => true,
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 130,
      render: (val: string) => timeNoSec(val) || '-', ellipsis: true,
    },
    ...(canWrite ? [{
      title: '操作', key: 'action', width: 140,
      render: (_: unknown, record: AiModelConfigItem) => (
        <span>
          <Button type="link" onClick={() => loadDetail(record.id)}>编辑</Button>
          <Button type="link" danger onClick={() => handleDelete(record.id)}>删除</Button>
        </span>
      ),
    }] : []),
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>AI模型配置</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && <Button type="primary" onClick={openCreate}>新增配置</Button>}
            <Select
              allowClear
              placeholder="按类型筛选"
              value={modelTypeFilter || undefined}
              onChange={(val) => setModelTypeFilter(val || '')}
              style={{ width: 140 }}
              options={modelTypeChoices.map((c) => ({ value: c.value, label: c.label }))}
            />
          </div>
        </div>

        <Modal
          title={form.id ? '编辑模型配置' : '新增模型配置'}
          open={modalOpen}
          onOk={submitForm}
          onCancel={() => { setModalOpen(false); resetForm() }}
          confirmLoading={submitting}
          okText={form.id ? '保存' : '创建'}
          cancelText="取消"
          width={520}
          destroyOnClose
        >
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="配置名称" help={formErrors.name ? <span className="react-error-text">{formErrors.name}</span> : undefined}>
              <Input
                value={form.name}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如：生产-GPT4"
              />
            </Form.Item>
            <Form.Item label="模型 ID" help={formErrors.model_id ? <span className="react-error-text">{formErrors.model_id}</span> : undefined}>
              <Input
                value={form.model_id}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, model_id: e.target.value }))}
                placeholder="如：gpt-4o"
              />
            </Form.Item>
            <Form.Item label="API 地址" help={formErrors.api_url ? <span className="react-error-text">{formErrors.api_url}</span> : undefined}>
              <Input
                value={form.api_url}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, api_url: e.target.value }))}
                placeholder="如：https://api.openai.com/v1"
              />
            </Form.Item>
            <Form.Item label="API Key" help={formErrors.api_key ? <span className="react-error-text">{formErrors.api_key}</span> : undefined}>
              <Input
                value={form.api_key}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                placeholder={form.id ? '留空则不修改' : '输入 API Key'}
              />
            </Form.Item>
            <Form.Item label="模型类型">
              <Select
                value={form.model_type}
                onChange={(val) => setForm((f) => ({ ...f, model_type: val }))}
                style={{ width: '100%' }}
                options={modelTypeChoices.map((c) => ({ value: c.value, label: c.label }))}
              />
              {formErrors.model_type ? <span className="react-error-text">{formErrors.model_type}</span> : null}
            </Form.Item>
            {formErrors.form ? <div className="react-error-box" style={{ marginBottom: 8 }}>{formErrors.form}</div> : null}
          </Form>
        </Modal>

        {error && (
          <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} closable onClose={() => setError(null)} />
        )}

        {loading ? (
          <div className="react-shell-panel"><span>正在加载...</span></div>
        ) : (
          <Table<AiModelConfigItem>
            columns={columns}
            dataSource={data?.items || []}
            rowKey="id"
            loading={loading}
            pagination={false}
            size="small"
            onChange={(_, filters) => {
              const typeFilter = filters.model_type_label
              setModelTypeFilter(typeFilter && typeFilter.length > 0 ? String(typeFilter[0]) : '')
            }}
          />
        )}
      </div>
    </div>
  )
}
