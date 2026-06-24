import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Input, Button, Tag, Alert, Spin, message, Descriptions, Modal, Radio } from 'antd'
import { ArrowLeftOutlined, ThunderboltOutlined, SaveOutlined, CopyOutlined } from '@ant-design/icons'
import { get, post, ApiError } from '../api'
import { copyToClipboard } from '../utils'
import type { PocGenTaskItem } from '../types/pocGenTask'
import { useAuth } from '../contexts/AuthContext'

const STATUS_COLORS: Record<string, string> = {
  pending: 'default', crawling: 'processing', ready: 'blue',
  generating: 'processing', generated: 'success', failed: 'error',
}

export default function PocGenTaskExecutePage() {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<PocGenTaskItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [saveLoading, setSaveLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [titleModalOpen, setTitleModalOpen] = useState(false)
  const [titleInput, setTitleInput] = useState('')
  const [prompts, setPrompts] = useState({
    task_description_prompt: '',
    plugin_spec_prompt: '',
    reference_material_prompt: '',
    custom_prompt: '',
  })
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const mountedRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const loadTask = useCallback(async () => {
    setLoading(true)
    try {
      const result = await get<{ status: boolean; data: PocGenTaskItem }>(`/api/v1/poc-gen-tasks/${id}`)
      if (mountedRef.current && result.status) {
        setTask(result.data)
        setPrompts({
          task_description_prompt: result.data.task_description_prompt || '',
          plugin_spec_prompt: result.data.plugin_spec_prompt || '',
          reference_material_prompt: result.data.reference_material_prompt || '',
          custom_prompt: result.data.custom_prompt || '',
        })
        if (result.data.status === 'generating') startPolling()
      }
    } catch (err) {
      if (mountedRef.current) setError(err instanceof ApiError ? err.message : '加载失败')
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [id])

  useEffect(() => { loadTask() }, [loadTask])

  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const result = await get<{ status: boolean; data: PocGenTaskItem }>(`/api/v1/poc-gen-tasks/${id}`)
        if (!mountedRef.current) return
        if (result.status) {
          setTask(result.data)
          if (result.data.status !== 'generating') {
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = null
            setGenerating(false)
            if (result.data.status === 'generated') message.success('生成完成')
            else if (result.data.status === 'failed') message.error('生成失败')
          }
        }
      } catch { /* ignore poll errors */ }
    }, 2000)
  }

  const savePrompt = async (field: string, value: string) => {
    try { await post(`/api/v1/poc-gen-tasks/${id}`, { [field]: value }) } catch { /* ignore */ }
  }

  const handleSwitchLanguage = async (lang: 1 | 2) => {
    try {
      const result = await post<{ status: boolean; data: PocGenTaskItem }>(`/api/v1/poc-gen-tasks/${id}`, { plugin_language: lang })
      if (result.status && mountedRef.current) {
        setTask(result.data)
        setPrompts({
          task_description_prompt: result.data.task_description_prompt || '',
          plugin_spec_prompt: result.data.plugin_spec_prompt || '',
          reference_material_prompt: result.data.reference_material_prompt || '',
          custom_prompt: result.data.custom_prompt || '',
        })
        message.success(`已切换为 ${lang === 1 ? 'Python' : 'Nuclei YAML'}`)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '切换失败')
    }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    setError(null)
    try {
      await post(`/api/v1/poc-gen-tasks/${id}/generate`, {})
      startPolling()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) { startPolling() }
      else { setGenerating(false); message.error(err instanceof ApiError ? err.message : '生成请求失败') }
    }
  }

  const handleSaveToExp = async () => {
    const meta = task?.generated_metadata ? (() => { try { return JSON.parse(task.generated_metadata) } catch { return {} } })() : {}
    if (!meta.title) { setTitleInput(''); setTitleModalOpen(true); return }
    await doSaveToExp()
  }

  const doSaveToExp = async (overrideTitle?: string) => {
    setSaveLoading(true)
    try {
      const body: Record<string, string> = {}
      if (overrideTitle) body.title = overrideTitle
      await post(`/api/v1/poc-gen-tasks/${id}/save-to-exp`, body)
      message.success('已保存到插件库')
      await loadTask()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '保存失败'
      if (msg.includes('已存在于插件库')) message.warning(msg)
      else message.error(msg)
    } finally { setSaveLoading(false) }
  }

  const canGenerate = (task?.status === 'ready' || task?.status === 'generated' || task?.status === 'failed') && task.plugin_language != null

  const handleCopyFullPrompt = async () => {
    try {
      const result = await get<{ status: boolean; data: { prompt: string } }>(`/api/v1/poc-gen-tasks/${id}/preview-prompt`)
      if (result.status && result.data?.prompt) {
        const ok = await copyToClipboard(result.data.prompt)
        if (ok) message.success('完整提示词已复制到剪贴板')
        else message.error('复制失败')
      } else {
        message.error('获取提示词失败')
      }
    } catch {
      message.error('获取提示词失败')
    }
  }
  const isGenerated = task?.status === 'generated'

  let metadata: Record<string, unknown> = {}
  if (task?.generated_metadata) {
    try { metadata = JSON.parse(task.generated_metadata) } catch {}
  }

  if (loading) {
    return <div className="react-shell-page"><div className="react-shell-card" style={{ padding: 40, textAlign: 'center' }}><Spin size="large" /></div></div>
  }
  if (!task) {
    return <div className="react-shell-page"><div className="react-shell-card" style={{ padding: 40, textAlign: 'center' }}><Alert type="error" message={error || '任务不存在'} showIcon /></div></div>
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card" style={{ marginBottom: 16, padding: '12px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/poc-gen-tasks')}>返回</Button>
            <strong style={{ fontSize: 16 }}>{task.title}</strong>
            <Tag>{task.task_type_label}</Tag>
            <Radio.Group
              value={task.plugin_language}
              onChange={(e) => handleSwitchLanguage(e.target.value)}
              size="small"
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value={1}>Python</Radio.Button>
              <Radio.Button value={2}>Nuclei YAML</Radio.Button>
            </Radio.Group>
            <Tag color={STATUS_COLORS[task.status] || 'default'}>{task.status_label}</Tag>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleGenerate} loading={generating} disabled={!canGenerate || generating}>
              {generating ? '生成中...' : '生成'}
            </Button>}
            {canWrite && <Button icon={<SaveOutlined />} onClick={handleSaveToExp} loading={saveLoading}
              disabled={task.saved_to_exp || task.status !== 'generated' || !task.generated_poc_content}>
              {task.saved_to_exp ? '已保存到插件库' : '保存到PoC库'}
            </Button>}
            <Button icon={<CopyOutlined />} onClick={handleCopyFullPrompt}>复制完整提示词</Button>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, minHeight: 'calc(100vh - 200px)' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
          <PromptEditor label="任务说明提示词" value={prompts.task_description_prompt}
            onChange={(v) => setPrompts((p) => ({ ...p, task_description_prompt: v }))}
            onBlur={() => savePrompt('task_description_prompt', prompts.task_description_prompt)} rows={10} />
          <PromptEditor label="插件规范提示词" value={prompts.plugin_spec_prompt}
            onChange={(v) => setPrompts((p) => ({ ...p, plugin_spec_prompt: v }))}
            onBlur={() => savePrompt('plugin_spec_prompt', prompts.plugin_spec_prompt)} rows={10} />
          <PromptEditor label="PoC参考资料提示词" value={prompts.reference_material_prompt}
            onChange={(v) => setPrompts((p) => ({ ...p, reference_material_prompt: v }))}
            onBlur={() => savePrompt('reference_material_prompt', prompts.reference_material_prompt)} rows={10} />
          <PromptEditor label="用户自定义提示词" value={prompts.custom_prompt}
            onChange={(v) => setPrompts((p) => ({ ...p, custom_prompt: v }))}
            onBlur={() => savePrompt('custom_prompt', prompts.custom_prompt)} rows={5} />
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
          {error && <Alert message={error} type="error" showIcon closable onClose={() => setError(null)} />}

          {isGenerated && task.generated_poc_content ? (
            <>
              {Object.keys(metadata).length > 0 && (
                <div className="react-shell-card" style={{ padding: 16 }}>
                  <Descriptions title="PoC 元数据" size="small" column={2} colon={false}>
                    {metadata.title ? <Descriptions.Item label="标题">{String(metadata.title)}</Descriptions.Item> : null}
                    {metadata.cve ? <Descriptions.Item label="CVE">{String(metadata.cve)}</Descriptions.Item> : null}
                    {metadata.type ? <Descriptions.Item label="类型">{String(metadata.type)}</Descriptions.Item> : null}
                    {metadata.severity ? <Descriptions.Item label="危害等级"><Tag>{String(metadata.severity)}</Tag></Descriptions.Item> : null}
                    {metadata.tags ? <Descriptions.Item label="标签">{String(metadata.tags)}</Descriptions.Item> : null}
                    {metadata.extentions ? <Descriptions.Item label="扩展">{String(metadata.extentions)}</Descriptions.Item> : null}
                    {metadata.ctime ? <Descriptions.Item label="公开日期">{String(metadata.ctime)}</Descriptions.Item> : null}
                  </Descriptions>
                </div>
              )}
              <div className="react-shell-card" style={{ padding: 16, flex: 1, overflow: 'auto' }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>生成的 PoC 代码</div>
                <pre style={{
                  background: 'var(--color-bg-layout, #f1f3f5)', padding: 16, borderRadius: 8,
                  fontSize: 13, fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                  maxHeight: 400, overflow: 'auto',
                }}>{task.generated_poc_content}</pre>
              </div>
            </>
          ) : isGenerated && !task.generated_poc_content ? (
            <div className="react-shell-card" style={{ padding: 16, flex: 1 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>生成结果</div>
              <Alert type="warning" message="模型未生成有效的 PoC 代码" showIcon />
            </div>
          ) : task.status === 'generating' ? (
            <div className="react-shell-card" style={{ padding: 40, textAlign: 'center', flex: 1 }}>
              <Spin size="large" tip="正在生成 PoC..." />
            </div>
          ) : (
            <div className="react-shell-card" style={{ padding: 40, textAlign: 'center', flex: 1 }}>
              <span style={{ color: '#8b949e' }}>点击左侧"生成"按钮开始</span>
            </div>
          )}

          {isGenerated && task.generated_extra_info && (
            <div className="react-shell-card" style={{ padding: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>模型反馈</div>
              <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 13, color: '#6c757d' }}>
                {task.generated_extra_info}
              </div>
            </div>
          )}

          {task.status === 'failed' && (
            <div className="react-shell-card" style={{ padding: 16 }}>
              <Alert type="error" message="生成失败" description={task.generated_extra_info || '未知错误'} showIcon />
            </div>
          )}
        </div>
      </div>

      <Modal title="补充插件标题" open={titleModalOpen}
        onOk={() => { setTitleModalOpen(false); doSaveToExp(titleInput) }}
        onCancel={() => setTitleModalOpen(false)} okText="保存" cancelText="取消" confirmLoading={saveLoading}>
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 8 }}>模型生成的 PoC 缺少标题，请手动输入：</div>
          <Input value={titleInput} onChange={(e) => setTitleInput(e.target.value)} placeholder="如：CVE-2024-XXXX - XXX RCE" />
        </div>
      </Modal>
    </div>
  )
}

function PromptEditor({ label, value, onChange, onBlur, rows }: {
  label: string; value: string; onChange: (v: string) => void; onBlur: () => void; rows: number
}) {
  return (
    <div className="react-shell-card" style={{ padding: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 13 }}>{label}</div>
      <Input.TextArea value={value}
        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
        onBlur={onBlur} rows={rows} style={{ fontFamily: 'monospace', fontSize: 12 }} />
    </div>
  )
}
