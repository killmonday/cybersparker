import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Input, Button, Select, Modal, Alert, message,
  Form, Radio, Tag, Descriptions,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { get, post, del, postForm, ApiError, timeNoSec } from '../api'
import type { PocGenTaskItem, PocGenTaskListResponse } from '../types/pocGenTask'
import type { AiModelConfigItem, AiModelConfigListResponse } from '../types/aiModelConfig'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../contexts/AuthContext'

const API_URL = '/api/v1/poc-gen-tasks'

const STATUS_COLORS: Record<string, string> = {
  pending: 'default', crawling: 'processing', ready: 'blue',
  generating: 'processing', generated: 'success', failed: 'error',
}

const CRAWL_STATUS_COLORS: Record<string, string> = {
  pending: 'default', processing: 'processing', success: 'success', failed: 'error',
}

export default function PocGenTaskListPage() {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const navigate = useNavigate()
  const search = new URLSearchParams(window.location.search)
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [rowsPerPage] = useState(Number(search.get('rows_per_page') ?? '10'))
  const [data, setData] = useState<PocGenTaskListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const mountedRef = useRef(false)

  const [thinkingModels, setThinkingModels] = useState<AiModelConfigItem[]>([])
  const [visionModels, setVisionModels] = useState<AiModelConfigItem[]>([])
  const [proxies, setProxies] = useState<{ id: number; label: string }[]>([])

  const [taskTitle, setTaskTitle] = useState('')
  const [taskType, setTaskType] = useState<'url_crawl' | 'file_upload' | 'text_input'>('url_crawl')
  const [thinkingModelId, setThinkingModelId] = useState<number | null>(null)
  const [visionModelId, setVisionModelId] = useState<number | null>(null)
  const [proxyId, setProxyId] = useState<number | undefined>(undefined)
  const [apiProxyId, setApiProxyId] = useState<number | undefined>(undefined)
  const [urlsText, setUrlsText] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)

  // 编辑状态
  const [editOpen, setEditOpen] = useState(false)
  const [editTask, setEditTask] = useState<PocGenTaskItem | null>(null)
  const [editLoading, setEditLoading] = useState(false)
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [editFormErrors, setEditFormErrors] = useState<Record<string, string>>({})
  const [editTitle, setEditTitle] = useState('')
  const [editThinkingModelId, setEditThinkingModelId] = useState<number | null>(null)
  const [editVisionModelId, setEditVisionModelId] = useState<number | null>(null)
  const [editProxyId, setEditProxyId] = useState<number | undefined>(undefined)
  const [editApiProxyId, setEditApiProxyId] = useState<number | undefined>(undefined)
  const [editUrlsText, setEditUrlsText] = useState('')
  const [editReferenceText, setEditReferenceText] = useState('')

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const load = useCallback(async () => {
    const params = new URLSearchParams()
    params.set('page', String(page))
    params.set('rows_per_page', String(rowsPerPage))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)

    setLoading(true)
    setError(null)
    try {
      const result = await get<PocGenTaskListResponse>(`${API_URL}?page=${page}&rows_per_page=${rowsPerPage}`)
      if (mountedRef.current) setData(result)
    } catch (err) {
      if (mountedRef.current) setError(err instanceof ApiError ? err.message : '加载失败')
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [page, rowsPerPage])

  useEffect(() => { load() }, [load])

  // 加载创建表单选项
  const loadFormOptions = async () => {
    try {
      const [modelRes, proxyRes] = await Promise.all([
        get<AiModelConfigListResponse>('/api/v1/ai-model-configs'),
        get<{ status: boolean; items: { id: number; proxy_type_label: string; proxy_address: string; proxy_port: number }[] }>('/api/v1/proxies?q='),
      ])
      if (modelRes.status) {
        setThinkingModels((modelRes.items || []).filter((m: AiModelConfigItem) => m.model_type === 'thinking'))
        setVisionModels((modelRes.items || []).filter((m: AiModelConfigItem) => m.model_type === 'vision'))
      }
      if (proxyRes && proxyRes.items) {
        setProxies((proxyRes.items || []).map((p) => ({
          id: p.id,
          label: `${p.proxy_address}:${p.proxy_port} (${p.proxy_type_label})`,
        })))
      }
    } catch { /* 忽略 */ }
  }

  const resetForm = () => {
    setTaskTitle('')
    setTaskType('url_crawl')
    setThinkingModelId(null)
    setVisionModelId(null)
    setProxyId(undefined)
    setUrlsText('')
    setReferenceText('')
    setUploadFile(null)
    setFormErrors({})
  }

  const openCreate = () => {
    resetForm()
    loadFormOptions()
    setCreateOpen(true)
  }

  const handleCreate = async () => {
    setSubmitting(true)
    setFormErrors({})
    try {
      if (taskType === 'file_upload') {
        if (!uploadFile) {
          setFormErrors({ file: '请选择上传文件' })
          setSubmitting(false)
          return
        }
        const formData = new FormData()
        formData.append('title', taskTitle)
        formData.append('task_type', taskType)
        formData.append('thinking_model_id', String(thinkingModelId || ''))
        if (visionModelId) formData.append('vision_model_id', String(visionModelId))
        if (proxyId) formData.append('proxy_id', String(proxyId))
        if (apiProxyId) formData.append('api_proxy_id', String(apiProxyId))
        formData.append('file', uploadFile)
        await postForm(API_URL, formData)
      } else {
        const body: Record<string, unknown> = {
          title: taskTitle,
          task_type: taskType,
          thinking_model_id: thinkingModelId,
          vision_model_id: visionModelId || null,
          proxy_id: proxyId || null,
          api_proxy_id: apiProxyId || null,
        }
        if (taskType === 'url_crawl') {
          body.urls = urlsText
        } else if (taskType === 'text_input') {
          body.reference_text = referenceText
        }
        await post(API_URL, body)
      }
      if (mountedRef.current) {
        message.success(taskType === 'text_input' ? '任务创建成功' : '任务创建成功，正在提取资料...')
        setCreateOpen(false)
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
        message.error(err instanceof ApiError ? err.message : '创建失败')
      }
    } finally {
      if (mountedRef.current) setSubmitting(false)
    }
  }

  const openEdit = async (id: number) => {
    setEditLoading(true)
    try {
      const [modelRes, proxyRes, taskRes] = await Promise.all([
        get<AiModelConfigListResponse>('/api/v1/ai-model-configs'),
        get<{ status: boolean; items: { id: number; proxy_type_label: string; proxy_address: string; proxy_port: number }[] }>('/api/v1/proxies?q='),
        get<{ status: boolean; data: PocGenTaskItem }>(`${API_URL}/${id}`),
      ])
      if (modelRes.status) {
        setThinkingModels((modelRes.items || []).filter((m: AiModelConfigItem) => m.model_type === 'thinking'))
        setVisionModels((modelRes.items || []).filter((m: AiModelConfigItem) => m.model_type === 'vision'))
      }
      if (proxyRes && proxyRes.items) {
        setProxies((proxyRes.items || []).map((p) => ({
          id: p.id,
          label: `${p.proxy_address}:${p.proxy_port} (${p.proxy_type_label})`,
        })))
      }
      if (taskRes.status && taskRes.data) {
        const t = taskRes.data
        setEditTask(t)
        setEditTitle(t.title)
        setEditThinkingModelId(t.thinking_model_id)
        setEditVisionModelId(t.vision_model_id)
        setEditProxyId(t.proxy_id || undefined)
        setEditApiProxyId(t.api_proxy_id || undefined)
        setEditUrlsText(t.task_type === 'url_crawl' ? (() => { try { return JSON.parse(t.urls || '[]').join('\n') } catch { return '' } })() : '')
        setEditReferenceText(t.task_type === 'text_input' ? (t.reference_material_prompt || '') : '')
        setEditFormErrors({})
        setEditOpen(true)
      }
    } catch {
      message.error('加载任务详情失败')
    } finally {
      setEditLoading(false)
    }
  }

  const handleEditSubmit = async () => {
    if (!editTask) return
    setEditSubmitting(true)
    setEditFormErrors({})
    try {
      const body: Record<string, unknown> = {
        title: editTitle,
        thinking_model_id: editThinkingModelId,
        vision_model_id: editVisionModelId || null,
        proxy_id: editProxyId || null,
        api_proxy_id: editApiProxyId || null,
      }
      if (editTask.task_type === 'url_crawl') {
        body.urls = editUrlsText
      }
      if (editTask.task_type === 'text_input') {
        body.reference_material_prompt = editReferenceText
      }
      await post(`${API_URL}/${editTask.id}`, body)
      if (mountedRef.current) {
        message.success('已更新')
        setEditOpen(false)
        setEditTask(null)
        await load()
      }
    } catch (err) {
      if (err instanceof ApiError && err.errors) {
        const fieldErrors: Record<string, string> = {}
        for (const [k, v] of Object.entries(err.errors)) {
          fieldErrors[k] = String(v ?? '')
        }
        setEditFormErrors(fieldErrors)
      } else {
        message.error(err instanceof ApiError ? err.message : '更新失败')
      }
    } finally {
      if (mountedRef.current) setEditSubmitting(false)
    }
  }

  const handleRetry = async (id: number) => {
    Modal.confirm({
      title: '确定重试该任务？',
      content: '系统将清空已有爬取结果，重新爬取所有 URL。',
      okText: '重试',
      cancelText: '取消',
      onOk: async () => {
        try {
          await post(`${API_URL}/${id}/retry`, {})
          message.success('已开始重新爬取')
          await load()
        } catch (err) {
          message.error(err instanceof ApiError ? err.message : '重试失败')
        }
      },
    })
  }

  const handleDelete = async (id: number) => {
    Modal.confirm({
      title: '确定删除该任务？',
      content: '删除后任务目录和所有相关数据将被清理，不可恢复。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await del(`${API_URL}/${id}`)
          message.success('已删除')
          await load()
        } catch (err) {
          message.error(err instanceof ApiError ? err.message : '删除失败')
        }
      },
    })
  }

  const columns: ColumnsType<PocGenTaskItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '标题', dataIndex: 'title', key: 'title', width: 200, ellipsis: true },
    {
      title: '任务类型', dataIndex: 'task_type_label', key: 'task_type_label', width: 90,
      render: (_: string, r: PocGenTaskItem) => <Tag>{r.task_type_label}</Tag>,
    },
    {
      title: '插件类型', dataIndex: 'plugin_language_label', key: 'plugin_language_label', width: 100,
      render: (_: string, r: PocGenTaskItem) => {
        if (r.plugin_language === null || r.plugin_language === undefined) return <Tag>未选择</Tag>
        return <Tag color={r.plugin_language === 1 ? 'blue' : 'purple'}>{r.plugin_language_label}</Tag>
      },
    },
    {
      title: '资料状态', dataIndex: 'crawl_status_label', key: 'crawl_status', width: 100,
      render: (_: string, r: PocGenTaskItem) => (
        <Tag color={CRAWL_STATUS_COLORS[r.crawl_status] || 'default'}>{r.crawl_status_label}</Tag>
      ),
    },
    {
      title: '任务状态', dataIndex: 'status_label', key: 'status', width: 100,
      render: (_: string, r: PocGenTaskItem) => (
        <Tag color={STATUS_COLORS[r.status] || 'default'}>{r.status_label}</Tag>
      ),
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 130,
      render: (val: string) => timeNoSec(val) || '-', ellipsis: true,
    },
    {
      title: '操作', key: 'action', width: 240,
      render: (_: unknown, record: PocGenTaskItem) => (
        <span style={{ whiteSpace: 'nowrap' }}>
          {record.status !== 'pending' && record.status !== 'crawling' ? (
            <Button type="link" onClick={() => navigate(`/poc-gen-tasks/${record.id}`)}>执行</Button>
          ) : (
            <Button type="link" disabled>等待资料</Button>
          )}
          {canWrite && <Button type="link" onClick={() => openEdit(record.id)}>编辑</Button>}
          {canWrite && record.task_type === 'url_crawl' && (
            <Button type="link" disabled={record.status === 'generating'} onClick={() => handleRetry(record.id)}>重试</Button>
          )}
          {canWrite && <Button type="link" danger onClick={() => handleDelete(record.id)}>删除</Button>}
        </span>
      ),
    },
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>AI生成PoC</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建任务</Button>}
          </div>
        </div>

        {error && (
          <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} closable onClose={() => setError(null)} />
        )}

        {loading ? (
          <div className="react-shell-panel"><span>正在加载...</span></div>
        ) : (
          <>
            <Table<PocGenTaskItem>
              columns={columns}
              dataSource={data?.items || []}
              rowKey="id"
              loading={loading}
              pagination={false}
              size="small"
            />

            <div className="react-pagination-bar">
            <span>
              第 {data?.page ?? 1} / {data?.total_pages ?? 1} 页，共 {data?.total ?? 0} 条
            </span>
            <div className="react-pagination-actions">
              <input type="number" min={1} max={data?.total_pages ?? 1} placeholder="页"
                style={{ width: 50, height: 34, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
                onKeyDown={e => {
                  if (e.key !== 'Enter') return
                  const n = parseInt((e.target as HTMLInputElement).value, 10)
                  if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n)
                }} />
              <Button onClick={() => {
                const inp = document.querySelector('.react-pagination-bar input[type="number"]') as HTMLInputElement
                if (inp) { const n = parseInt(inp.value, 10); if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n) }
              }}>跳转</Button>
              <Button disabled={!data || data.page <= 1} onClick={() => setPage((c) => Math.max(1, c - 1))}>
                上一页
              </Button>
              <Button disabled={!data || data.page >= data.total_pages} onClick={() => setPage((c) => c + 1)}>
                下一页
              </Button>
            </div>
          </div>
          </>
        )}
      </div>

      {/* 创建任务对话框 */}
      <Modal
        title="新建PoC生成任务"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={submitting}
        okText="创建"
        cancelText="取消"
        width={640}
        destroyOnClose
      >
        <Form layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="任务标题" required help={formErrors.title}>
            <Input value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} placeholder="如：CVE-2024-XXXX 漏洞分析" />
          </Form.Item>

          <Form.Item label="任务类型" required>
            <Radio.Group value={taskType} onChange={(e) => setTaskType(e.target.value)}>
              <Radio.Button value="url_crawl">通过URL爬取</Radio.Button>
              <Radio.Button value="file_upload">上传文件</Radio.Button>
              <Radio.Button value="text_input">直接输入文本</Radio.Button>
            </Radio.Group>
          </Form.Item>

          <Form.Item label="思考模型" required help={formErrors.thinking_model_id}>
            <Select
              value={thinkingModelId}
              onChange={(val) => setThinkingModelId(val)}
              placeholder="选择思考模型"
              style={{ width: '100%' }}
              options={thinkingModels.map((m) => ({ value: m.id, label: `${m.name} (${m.model_id})` }))}
            />
          </Form.Item>

          <Form.Item label="识图模型（可选）">
            <Select
              allowClear
              value={visionModelId}
              onChange={(val) => setVisionModelId(val)}
              placeholder="选择识图模型（仅支持 DashScope API）"
              style={{ width: '100%' }}
              options={visionModels.map((m) => ({ value: m.id, label: `${m.name} (${m.model_id})` }))}
            />
          </Form.Item>

          <Form.Item label="URL爬取代理（可选）">
            <Select
              allowClear
              value={proxyId}
              onChange={(val) => setProxyId(val)}
              placeholder="无代理"
              style={{ width: '100%' }}
              options={proxies.map((p) => ({ value: p.id, label: p.label }))}
            />
          </Form.Item>

          <Form.Item label="AI API代理（可选）">
            <Select
              allowClear
              value={apiProxyId}
              onChange={(val) => setApiProxyId(val)}
              placeholder="无代理"
              style={{ width: '100%' }}
              options={proxies.map((p) => ({ value: p.id, label: p.label }))}
            />
          </Form.Item>

          {taskType === 'url_crawl' ? (
            <Form.Item label="URL 列表" required help={formErrors.urls || '每行一个 URL'}>
              <Input.TextArea
                value={urlsText}
                onChange={(e) => setUrlsText(e.target.value)}
                rows={5}
                placeholder="https://example.com/vuln-detail&#10;https://blog.example.com/cve-2024-xxxx"
              />
            </Form.Item>
          ) : taskType === 'text_input' ? (
            <Form.Item label="参考资料内容" required help={formErrors.reference_text || '直接粘贴漏洞相关的技术文章、报告、代码片段等'}>
              <Input.TextArea
                value={referenceText}
                onChange={(e) => setReferenceText(e.target.value)}
                rows={12}
                placeholder="直接粘贴漏洞分析文章、技术报告、安全公告、代码片段等作为 AI 生成的参考资料..."
              />
            </Form.Item>
          ) : (
            <Form.Item label="上传文件" required help={formErrors.file || '支持 md/txt/zip/tar.gz/tar/7z压缩包等（≤100MB）'}>
              <Input
                type="file"
                onChange={(e) => {
                  const file = e.target.files?.[0] || null
                  setUploadFile(file)
                }}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 编辑任务对话框 */}
      <Modal
        title="编辑PoC生成任务"
        open={editOpen}
        onOk={handleEditSubmit}
        onCancel={() => { setEditOpen(false); setEditTask(null) }}
        confirmLoading={editSubmitting}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnClose
      >
        {editLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>加载中...</div>
        ) : editTask ? (
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="任务标题" required help={editFormErrors.title}>
              <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} placeholder="如：CVE-2024-XXXX 漏洞分析" />
            </Form.Item>

            <Form.Item label="任务类型" required>
              <Radio.Group value={editTask.task_type} disabled>
                <Radio.Button value="url_crawl">通过URL爬取</Radio.Button>
                <Radio.Button value="file_upload">上传文件</Radio.Button>
                <Radio.Button value="text_input">直接输入文本</Radio.Button>
              </Radio.Group>
            </Form.Item>

            <Form.Item label="思考模型" required help={editFormErrors.thinking_model_id}>
              <Select
                value={editThinkingModelId}
                onChange={(val) => setEditThinkingModelId(val)}
                placeholder="选择思考模型"
                style={{ width: '100%' }}
                options={thinkingModels.map((m) => ({ value: m.id, label: `${m.name} (${m.model_id})` }))}
              />
            </Form.Item>

            <Form.Item label="识图模型（可选）">
              <Select
                allowClear
                value={editVisionModelId}
                onChange={(val) => setEditVisionModelId(val)}
                placeholder="选择识图模型（仅支持 DashScope API）"
                style={{ width: '100%' }}
                options={visionModels.map((m) => ({ value: m.id, label: `${m.name} (${m.model_id})` }))}
              />
            </Form.Item>

            <Form.Item label="URL爬取代理（可选）">
              <Select
                allowClear
                value={editProxyId}
                onChange={(val) => setEditProxyId(val)}
                placeholder="无代理"
                style={{ width: '100%' }}
                options={proxies.map((p) => ({ value: p.id, label: p.label }))}
              />
            </Form.Item>

            <Form.Item label="AI API代理（可选）">
              <Select
                allowClear
                value={editApiProxyId}
                onChange={(val) => setEditApiProxyId(val)}
                placeholder="无代理"
                style={{ width: '100%' }}
                options={proxies.map((p) => ({ value: p.id, label: p.label }))}
              />
            </Form.Item>

            {editTask.task_type === 'url_crawl' ? (
              <Form.Item label="URL 列表" required help={editFormErrors.urls || '每行一个 URL'}>
                <Input.TextArea
                  value={editUrlsText}
                  onChange={(e) => setEditUrlsText(e.target.value)}
                  rows={5}
                  placeholder="https://example.com/vuln-detail&#10;https://blog.example.com/cve-2024-xxxx"
                />
              </Form.Item>
            ) : editTask.task_type === 'text_input' ? (
              <Form.Item label="参考资料内容" required help={editFormErrors.reference_material_prompt || '直接粘贴漏洞相关的技术文章、报告、代码片段等'}>
                <Input.TextArea
                  value={editReferenceText}
                  onChange={(e) => setEditReferenceText(e.target.value)}
                  rows={12}
                  placeholder="直接粘贴漏洞分析文章、技术报告、安全公告、代码片段等作为 AI 生成的参考资料..."
                />
              </Form.Item>
            ) : (
              <Form.Item label="上传文件">
                <Input value={editTask.uploaded_file?.split('/').pop() || '（已上传，不可修改）'} disabled />
              </Form.Item>
            )}
          </Form>
        ) : null}
      </Modal>
    </div>
  )
}
