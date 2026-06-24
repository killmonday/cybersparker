import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Table, Tag, Input, Button, Modal, Progress, Space, Select, Checkbox, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { TaskItem, TaskListResponse, TaskPollData } from '../types/task'
import type { ZoneItem } from '../types/zone'
import { useTaskPolling } from '../hooks/useTaskPolling'
import HistoryFilePicker from '../components/HistoryFilePicker'
import type { HistoryFile } from '../components/HistoryFilePicker'
import HistoryEngineResultPicker from '../components/HistoryEngineResultPicker'
import type { HistoryEngineResult } from '../components/HistoryEngineResultPicker'
import { HISTORY_ENGINE_FILES_FIELD, HISTORY_ENGINE_INPUT_TYPE } from '../types/historyEngineResultContract'
import { get, post, postForm, ApiError , timeNoSec} from '../api'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
}

interface ChoiceOption {
  value: string | number
  label: string
}

const ROWS_PER_PAGE = 13

const AutoScanTaskListPage: React.FC<Props> = ({ apiUrl }) => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [searchInput, setSearchInput] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [refreshKey, setRefreshKey] = useState(0)
  const [data, setData] = useState<TaskListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  function confirmBatchDelete() {
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个任务？`, content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个任务`); setSelectedIds(new Set()); loadList() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  const pollableIds = useMemo(
    () => (data?.items || [])
      .filter((t) => t.status_key === 'running' || t.status_key === 'waiting' || t.status_key === 'pausing')
      .map((t) => t.id),
    [data?.items],
  )
  const pollData = useTaskPolling<TaskPollData>('/api/v1/identify-tasks/status-batch', pollableIds)

  // Operate modal
  const [opModal, setOpModal] = useState<{ open: boolean; taskId: number; taskName: string; action: string; actionLabel: string; inputType: number }>({ open: false, taskId: 0, taskName: '', action: '', actionLabel: '', inputType: 0 })
  const [opReuseEngine, setOpReuseEngine] = useState(true)

  // Delete modal
  const [delModal, setDelModal] = useState<{ open: boolean; taskId: number; taskName: string }>({ open: false, taskId: 0, taskName: '' })

  // Add/Edit form modal
  const [formModal, setFormModal] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [form, setForm] = useState<Record<string, string>>({
    task_name: '', thread_num: '100', vulnerability_thread_num: '40', sleep_time: '0', http_timeout: '10',
    input_type: '1', search_query: '', engine_type: 'fofa', engine_query: '', engine_max_assets: '100',
    engine_proxy_mode: '0', engine_proxy: '', Vulnerability_scanning: '0', proxy: '', remark: '',
    task_args: '', conflict_strategy: '1', zone: '',
  })
  const [targetFile, setTargetFile] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [fscanxFile, setFscanxFile] = useState<File | null>(null)
  const fscanxFileRef = useRef<HTMLInputElement>(null)
  const [existingTargetName, setExistingTargetName] = useState('')
  const [existingFscanxFileName, setExistingFscanxFileName] = useState('')
  const [historyFiles, setHistoryFiles] = useState<HistoryFile[]>([])
  const [selHistoryFiles, setSelHistoryFiles] = useState<string[]>([])
  const [engineResults, setEngineResults] = useState<HistoryEngineResult[]>([])
  const [selEngineFiles, setSelEngineFiles] = useState<string[]>([])
  const [choices, setChoices] = useState<Record<string, ChoiceOption[]>>({})
  const [zones, setZones] = useState<ZoneItem[]>([])

  function loadZones() {
    get<{ zones: ZoneItem[] }>('/api/v1/zones').then((p) => setZones(p.zones || [])).catch(() => {})
  }

  // 表单弹窗打开时预加载 zones，避免 Select 在选项为空时显示原始 id 而非名称
  useEffect(() => {
    if (formModal && zones.length === 0) loadZones()
  }, [formModal])

  // zones 加载后，若表单未选区域则默认选中"公网"
  useEffect(() => {
    if (!formModal || zones.length === 0) return
    setForm(f => {
      if (f.zone) return f
      const pub = zones.find(z => z.code === 'public')
      return pub ? { ...f, zone: String(pub.id) } : f
    })
  }, [zones, formModal])

  const loadList = useCallback(() => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    params.set('page', String(page))
    params.set('rows_per_page', String(ROWS_PER_PAGE))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    setLoading(true)
    get<TaskListResponse>(`${apiUrl}?${params.toString()}`)
      .then((payload) => { setData(payload) })
      .finally(() => setLoading(false))
  }, [apiUrl, page, q, refreshKey])

  useEffect(() => { loadList() }, [loadList])

  useEffect(() => {
    get<any>('/api/v1/identify-tasks/choices')
      .then((p) => setChoices({
        proxy: (p.proxy_choices || []),
        engine_proxy: (p.engine_proxy_choices || []),
        engine_type: (p.engine_type_choices || []),
        engine_proxy_mode: (p.engine_proxy_mode_choices || []),
        input_type: (p.input_type_choices || []),
        vulnerability_scanning: (p.vulnerability_scanning_choices || []),
      }))
  }, [])



  function handleSearch() {
    if (searchInput.trim()) { setQ(searchInput.trim()); setPage(1) }
    else { setRefreshKey(k => k + 1) }
  }

  function openOperateModal(taskId: number, taskName: string, action: string, inputType: number) {
    const labels: Record<string, string> = { '0': '启动', pause: '暂停', resume: '续跑', rerun: '重跑' }
    setSubmitting(false)
    setOpReuseEngine(true)
    setOpModal({ open: true, taskId, taskName, action, actionLabel: labels[action] || action, inputType })
  }

  function confirmOperate() {
    setSubmitting(true)
    const fd = new FormData()
    fd.append('uid', String(opModal.taskId))
    fd.append('status', opModal.action)
    if (opModal.action === 'rerun' && opModal.inputType === 4)
      fd.append('reuse_engine_data', opReuseEngine ? 'true' : 'false')
    postForm<{ status: boolean }>(`/api/v1/identify-tasks/${opModal.taskId}/operate`, fd)
      .then((p) => {
        if (p.status) { setOpModal(prev => ({ ...prev, open: false })); loadList() }
      })
      .catch(() => {})
      .finally(() => setSubmitting(false))
  }

  function confirmDelete() {
    setSubmitting(true)
    postForm<{ status: boolean }>(`/api/v1/identify-tasks/${delModal.taskId}/delete`, new FormData())
      .then((p) => {
        if (p.status) { setDelModal({ open: false, taskId: 0, taskName: '' }); loadList() }
      })
      .catch(() => {})
      .finally(() => setSubmitting(false))
  }

  function openAddForm() {
    setEditingId(null)
    setForm({
      task_name: '', thread_num: '100', vulnerability_thread_num: '40', sleep_time: '0', http_timeout: '10',
      input_type: '1', search_query: '', engine_type: 'fofa', engine_query: '', engine_max_assets: '100',
      engine_proxy_mode: '0', engine_proxy: '', Vulnerability_scanning: '0', proxy: '', remark: '',
      task_args: '', conflict_strategy: '1', zone: '',
    })
    setTargetFile(null); setExistingTargetName(''); setExistingFscanxFileName(''); setSelHistoryFiles([]); setSelEngineFiles([]); setFormErrors({}); setFormModal(true)
  }

  function openEditForm(id: number) {
    setEditingId(id); setFormErrors({}); setTargetFile(null); setExistingTargetName(''); setExistingFscanxFileName(''); setSelHistoryFiles([]); setSelEngineFiles([])
    get<{ status: boolean; data: any }>(`/api/v1/identify-tasks/${id}`)
      .then(p => {
        if (p.status && p.data) {
          const d = p.data
          setForm({
            task_name: d.task_name || '', thread_num: String(d.thread_num ?? 100), vulnerability_thread_num: String(d.vulnerability_thread_num ?? 40),
            sleep_time: String(d.sleep_time ?? 0), http_timeout: String(d.http_timeout ?? 10),
            input_type: String(d.input_type ?? 1), search_query: d.search_query || '', engine_type: d.engine_type || 'fofa',
            engine_query: d.engine_query || '', engine_max_assets: String(d.engine_max_assets ?? 100),
            engine_proxy_mode: String(d.engine_proxy_mode ?? 0), engine_proxy: d.engine_proxy_id ? String(d.engine_proxy_id) : '',
            Vulnerability_scanning: String(d.Vulnerability_scanning ?? 0), proxy: d.proxy_id ? String(d.proxy_id) : '', remark: d.remark || '',
            task_args: d.task_args || '', conflict_strategy: String(d.conflict_strategy ?? 1),
            zone: d.zone_id ? String(d.zone_id) : '',
          })
          if (d.input_type === 3) {
            const hf = d.history_files
            setSelHistoryFiles(typeof hf === 'string' && hf ? hf.split(',').filter(Boolean) : (Array.isArray(hf) ? hf : []))
          }
          if (d.input_type === 5) {
            const hf = d.history_files
            setSelEngineFiles(typeof hf === 'string' && hf ? hf.split(',').filter(Boolean) : (Array.isArray(hf) ? hf : []))
          }
          if (d.input_type === 1 && d.target) {
            const name = String(d.target).split('/').pop() || ''
            setExistingTargetName(name)
          }
          if (d.input_type === 2 && d.fscanx_file) {
            const name = String(d.fscanx_file).split('/').pop() || ''
            setExistingFscanxFileName(name)
          }
          setFormModal(true)
        }
      })
      .catch(() => {})
  }

  function submitAddForm() {
    if (form.task_args && form.task_args.trim()) {
      try { JSON.parse(form.task_args) } catch { alert('task_args JSON 格式错误'); return }
    }
    setSubmitting(true); setFormErrors({})
    const fd = new FormData()
    Object.entries(form).forEach(([k, v]) => { fd.append(k, v ?? '') })
    if (targetFile) fd.append('target', targetFile)
    if (form.input_type === '2' && fscanxFile) fd.append('fscanx_file', fscanxFile)
    if (form.input_type === '2') fd.append('conflict_strategy', form.conflict_strategy || '1')
    if (form.input_type === '3' && Array.isArray(selHistoryFiles)) selHistoryFiles.forEach(f => fd.append('history_files[]', f))
    if (form.input_type === HISTORY_ENGINE_INPUT_TYPE && Array.isArray(selEngineFiles)) selEngineFiles.forEach(f => fd.append(HISTORY_ENGINE_FILES_FIELD, f))
    const url = editingId ? `/api/v1/identify-tasks/${editingId}/update` : '/api/v1/identify-tasks/create'
    postForm<{ status: boolean; target?: string; fscanx_file?: string; error?: Record<string, string> }>(url, fd)
      .then((p) => {
        if (p.status) {
          if (p.target) {
            setTargetFile(null)
            setExistingTargetName(p.target)
            message.success('文件已保存: ' + p.target)
          }
          if (p.fscanx_file) {
            const name = p.fscanx_file.split('/').pop() || p.fscanx_file
            setFscanxFile(null)
            setExistingFscanxFileName(name)
            message.success('文件已保存: ' + name)
          }
          setFormModal(false); setEditingId(null); loadList()
        }
      })
      .catch((e) => {
        if (e instanceof ApiError && e.errors) {
          setFormErrors({ ...e.errors, form: e.message } as Record<string, string>)
        } else {
          setFormErrors({ form: e instanceof ApiError ? e.message : '保存失败' })
        }
      })
      .finally(() => { setSubmitting(false) })
  }

  function loadHistoryFileList() {
    get<any>('/api/v1/history-files')
      .then((p) => { if (p.status) setHistoryFiles(p.data.files || []) })
  }

  function loadHistoryEngineResults() {
    get<any>('/api/v1/identify-tasks/history-engine-results').then((p) => { if (p.status) setEngineResults(p.data.results || []) }).catch(() => { message.error('加载历史测绘结果失败') })
  }

  // 选择"历史上传文件"输入源时自动拉取文件列表
  useEffect(() => {
    if (formModal && String(form.input_type) === '3') loadHistoryFileList()
  }, [form.input_type, formModal])

  // 选择"历史测绘结果"输入源时自动拉取列表
  useEffect(() => {
    if (formModal && String(form.input_type) === '5') loadHistoryEngineResults()
  }, [form.input_type, formModal])

  function getEffectiveStatus(item: TaskItem) {
    const poll = pollData[item.id]
    const statusKey = poll?.status ?? item.status_key
    const pauseRequested = poll?.pause_requested ?? item.pause_requested
    if (statusKey === 'finish') return { label: '完成', color: 'green' }
    if (statusKey === 'pause') return { label: '已暂停', color: 'orange' }
    if (statusKey === 'running' && pauseRequested) return { label: '暂停中...', color: 'gold' }
    if (statusKey === 'waiting') return { label: '等待中', color: 'blue' }
    if (statusKey === 'running') return { label: '运行中', color: 'green' }
    if (statusKey === 'stopped') return { label: '已停止', color: 'red' }
    if (statusKey === 'unstarted') return { label: '未启动', color: 'default' }
    return { label: item.status_label, color: 'default' }
  }

  function getEffectivePhase(item: TaskItem) {
    const poll = pollData[item.id]
    const phase = poll?.phase ?? item.phase
    const mapping: Record<number, string> = { 1: '正在Web扫描', 2: '正在漏洞扫描', 3: '全部完成' }
    return mapping[phase] || String(phase)
  }

  const columns: ColumnsType<TaskItem> = useMemo(() => [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 50 },
    {
      title: '任务名称', key: 'task_name', width: 220,
      render: (_: any, record: TaskItem) => {
        const label = record.task_name
        const parts = []
        const queued = pollData[record.id]?.queued ?? record.queued
        if (queued) parts.push(<Tag key="queued" color="blue" style={{ marginRight: 4 }}>排队中</Tag>)
        const nameUrl = record.react_result_url
        if (nameUrl && (nameUrl.startsWith('/') || nameUrl.startsWith('http://') || nameUrl.startsWith('https://'))) {
          parts.push(<a key="name" href={nameUrl} target="_blank" rel="noopener noreferrer">{label}</a>)
        } else {
          parts.push(<span key="name">{label}</span>)
        }
        return <>{parts}</>
      },
    },
    {
      title: '区域', dataIndex: 'zone_name', key: 'zone_name', width: 90,
      render: (v: string) => v || '—',
    },
    {
      title: '状态', key: 'status', width: 90,
      render: (_: any, record: TaskItem) => {
        const st = getEffectiveStatus(record)
        return <Tag color={st.color}>{st.label}</Tag>
      },
    },
    {
      title: '进度', key: 'process', width: 140,
      render: (_: any, record: TaskItem) => {
        const proc = pollData[record.id]?.process ?? record.process
        const pct = parseFloat(proc) || 0
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Progress percent={Math.round(pct)} size="small" style={{ width: 80, margin: 0 }} strokeColor="#2563eb" />
          </div>
        )
      },
    },
    {
      title: '阶段', key: 'phase', width: 110,
      render: (_: any, record: TaskItem) => getEffectivePhase(record),
    },
    {
      title: '暂停请求', key: 'pause_requested', width: 80,
      render: (_: any, record: TaskItem) => {
        const pr = pollData[record.id]?.pause_requested ?? record.pause_requested
        return pr ? <Tag color="orange">是</Tag> : <Tag>否</Tag>
      },
    },
    {
      title: '排队', key: 'queued', width: 70,
      render: (_: any, record: TaskItem) => {
        const queued = pollData[record.id]?.queued ?? record.queued
        return queued ? <Tag color="blue">是</Tag> : <Tag>否</Tag>
      },
    },
    {
      title: '开始时间', dataIndex: 'startTime', key: 'startTime', width: 150,
      render: (v: string | null) => timeNoSec(v), ellipsis: true,
    },
    {
      title: '结束时间', dataIndex: 'endTime', key: 'endTime', width: 140,
      render: (v: string | null) => timeNoSec(v), ellipsis: true,
    },
    {
      title: '备注', dataIndex: 'remark', key: 'remark', width: 120,
      render: (v: string | null) => v || '—',
    },
    {
      title: '操作', key: 'actions', width: 260,
      render: (_: any, record: TaskItem) => {
        const statusKey = pollData[record.id]?.status ?? record.status_key
        const pauseRequested = pollData[record.id]?.pause_requested ?? record.pause_requested
        const btns: React.ReactNode[] = []
        if (canWrite) {
          btns.push(<a key="edit" onClick={() => openEditForm(record.id)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>编辑</a>)
          btns.push(<a key="delete" onClick={() => setDelModal({ open: true, taskId: record.id, taskName: record.task_name })} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>删除</a>)
        }
        const resultUrl = record.react_result_url
        if (resultUrl && (resultUrl.startsWith('/') || resultUrl.startsWith('http://') || resultUrl.startsWith('https://'))) {
          btns.push(<a key="result" href={resultUrl} target="_blank" style={{ fontSize: 12, marginRight: 6 }}>结果</a>)
        }
        btns.push(<a key="vuln" href={`/react-shell/auto-exp-results?task_id=${record.id}`} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, marginRight: 6 }}>漏洞</a>)
        if (canWrite) {
          if (statusKey === 'running' && !pauseRequested) btns.push(<a key="pause" onClick={() => openOperateModal(record.id, record.task_name, 'pause', record.input_type)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>暂停</a>)
          if (statusKey === 'unstarted') btns.push(<a key="start" onClick={() => openOperateModal(record.id, record.task_name, '0', record.input_type)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>启动</a>)
          if (statusKey === 'stopped' || statusKey === 'pause') btns.push(<a key="resume" onClick={() => openOperateModal(record.id, record.task_name, 'resume', record.input_type)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>续跑</a>)
          if (statusKey === 'stopped' || statusKey === 'pause') btns.push(<a key="rerun1" onClick={() => openOperateModal(record.id, record.task_name, 'rerun', record.input_type)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>重跑</a>)
          if (statusKey === 'finish') btns.push(<a key="rerun2" onClick={() => openOperateModal(record.id, record.task_name, 'rerun', record.input_type)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>重跑</a>)
        }
        return <>{btns}</>
      },
    },
  ], [pollData])

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>自动扫描任务管理</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && selectedIds.size > 0 && <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>}
            {canWrite && <Button type="primary" onClick={openAddForm}>新增任务</Button>}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onPressEnter={handleSearch}
            placeholder="搜索任务名称"
            style={{ width: 240 }}
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </div>

        <div className="react-task-table-wrap">
          <Table<TaskItem>
            columns={columns}
            dataSource={data?.items || []}
            rowKey="id"
            loading={loading}
            pagination={false}
            size="small"
            rowSelection={canWrite ? { selectedRowKeys: Array.from(selectedIds), onChange: (keys) => setSelectedIds(new Set(keys as number[])) } : undefined}
          />
        </div>

        {data && (
          <div className="react-pagination-bar">
            <span>第 {data.page ?? 1} / {data.total_pages ?? 1} 页，共 {data.total ?? 0} 条</span>
            <Space>
              <input type="number" min={1} max={data.total_pages ?? 1} placeholder="页" style={{ width: 50, height: 30, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
                onKeyDown={e => { if (e.key !== 'Enter') return; const n = parseInt((e.target as HTMLInputElement).value, 10); if (n && n >= 1 && n <= (data.total_pages ?? 1)) setPage(n) }} />
              <Button onClick={() => { const inp = document.querySelector('.react-pagination-bar input[type="number"]') as HTMLInputElement; if (inp) { const n = parseInt(inp.value, 10); if (n && n >= 1 && n <= (data.total_pages ?? 1)) setPage(n) } }}>跳转</Button>
              <Button disabled={(data.page ?? 1) <= 1} onClick={() => setPage(c => Math.max(1, c - 1))}>上一页</Button>
              <Button disabled={data.page >= data.total_pages} onClick={() => setPage(c => c + 1)}>下一页</Button>
            </Space>
          </div>
        )}
      </div>

      {/* Operate Modal */}
      <Modal
        title="操作确认"
        open={opModal.open}
        onCancel={() => setOpModal(prev => ({ ...prev, open: false }))}
        footer={null}
        width={480}
      >
        <p>确认对任务 <strong>{opModal.taskName}</strong> 执行 <strong>{opModal.actionLabel}</strong>？</p>
        {opModal.action === 'rerun' && opModal.inputType === 4 ? (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
            <Checkbox checked={opReuseEngine} onChange={e => setOpReuseEngine(e.target.checked)} />
            复用已有引擎数据
          </label>
        ) : null}
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <Button onClick={() => setOpModal(prev => ({ ...prev, open: false }))}>取消</Button>
          <Button type="primary" onClick={confirmOperate} loading={submitting}>确认</Button>
        </div>
      </Modal>

      {/* Delete Modal */}
      <Modal
        title="删除确认"
        open={delModal.open}
        onCancel={() => setDelModal({ open: false, taskId: 0, taskName: '' })}
        footer={null}
        width={480}
      >
        <p>确认删除任务 <strong>{delModal.taskName}</strong>？</p>
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <Button onClick={() => setDelModal({ open: false, taskId: 0, taskName: '' })}>取消</Button>
          <Button danger type="primary" onClick={confirmDelete} loading={submitting}>确认删除</Button>
        </div>
      </Modal>

      {/* Add Form Modal */}
      <Modal
        title={editingId ? '编辑任务' : '新增任务'}
        open={formModal}
        onCancel={() => setFormModal(false)}
        footer={null}
        width={640}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <label>任务名称
            <Input value={form.task_name} onChange={e => setForm({ ...form, task_name: e.target.value })} />
            {formErrors.task_name ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.task_name}</span> : null}
          </label>
          {form.input_type !== '2' && (
          <label>线程数
            <Input type="number" value={form.thread_num} onChange={e => setForm({ ...form, thread_num: e.target.value })} />
          </label>
          )}
          {form.input_type !== '2' && (
          <label>漏洞线程数
            <Input type="number" value={form.vulnerability_thread_num} onChange={e => setForm({ ...form, vulnerability_thread_num: e.target.value })} />
          </label>
          )}
          {form.input_type !== '2' && (
          <label>休眠时间(秒)
            <Input type="number" value={form.sleep_time} onChange={e => setForm({ ...form, sleep_time: e.target.value })} />
          </label>
          )}
          {form.input_type !== '2' && (
          <label>HTTP超时(秒)
            <Input type="number" value={form.http_timeout} onChange={e => setForm({ ...form, http_timeout: e.target.value })} />
          </label>
          )}
          {form.Vulnerability_scanning !== '2' && (
          <label>输入源类型
            <Select value={form.input_type} onChange={v => setForm({ ...form, input_type: v })} style={{ width: '100%' }}>
              {(choices.input_type || []).map(c => <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>)}
            </Select>
            {formErrors.input_type ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.input_type}</span> : null}
          </label>
          )}
          {form.input_type !== '2' && (
          <label>漏洞扫描
            <Select value={form.Vulnerability_scanning} onChange={v => setForm({ ...form, Vulnerability_scanning: v })} style={{ width: '100%' }}>
              {(choices.vulnerability_scanning || []).map(c => <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>)}
            </Select>
          </label>
          )}
          {form.input_type !== '2' && (
          <label>代理
            <Select value={form.proxy} onChange={v => setForm({ ...form, proxy: v })} style={{ width: '100%' }}>
              {(choices.proxy || []).map(c => <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>)}
            </Select>
          </label>
          )}
          <label>备注
            <Input value={form.remark} onChange={e => setForm({ ...form, remark: e.target.value })} />
          </label>
          <label>扫描区域
            {(form.input_type === '4' || form.input_type === '5') ? (
              <Input value="公网（固定）" disabled />
            ) : (
              <Select
                value={form.zone || undefined}
                onChange={v => setForm({ ...form, zone: v || '' })}
                style={{ width: '100%' }}
                placeholder="请选择区域"
                allowClear
                onFocus={() => { if (zones.length === 0) loadZones() }}
              >
                {zones.map(z => <Select.Option key={z.id} value={String(z.id)}>{z.name}</Select.Option>)}
              </Select>
            )}
          </label>
        </div>

        {form.Vulnerability_scanning !== '2' && (form.input_type === '1' ? (
          <div style={{ marginTop: 12 }}>
            <label style={{ display: 'block' }}>目标文件
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <Button onClick={() => fileRef.current?.click()}>选择文件</Button>
                <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  {targetFile ? targetFile.name : existingTargetName || '未选择'}
                </span>
              </div>
              <input ref={fileRef} type="file" onChange={e => setTargetFile(e.target.files?.[0] || null)} style={{ display: 'none' }} />
            </label>
            {existingTargetName && !targetFile ? (
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
                当前文件：<strong>{existingTargetName}</strong>
                <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>（选新文件将替换）</span>
              </div>
            ) : null}
          </div>
        ) : form.input_type === '3' ? (
          <HistoryFilePicker
            files={historyFiles}
            selected={selHistoryFiles}
            onSelectionChange={setSelHistoryFiles}
            onRefresh={loadHistoryFileList}
          />
        ) : form.input_type === '4' ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
            <label>搜索引擎
              <Select value={form.engine_type} onChange={v => setForm({ ...form, engine_type: v })} style={{ width: '100%' }}>
                {(choices.engine_type || []).map(c => <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>)}
              </Select>
            </label>
            <label>搜索语句
              <Input value={form.engine_query} onChange={e => setForm({ ...form, engine_query: e.target.value })} />
            </label>
            <label>最大资产数
              <Input type="number" value={form.engine_max_assets} onChange={e => setForm({ ...form, engine_max_assets: e.target.value })} />
            </label>
            <label>测绘引擎代理模式
              <Select value={form.engine_proxy_mode} onChange={v => setForm({ ...form, engine_proxy_mode: v })} style={{ width: '100%' }}>
                {(choices.engine_proxy_mode || []).map(c => <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>)}
              </Select>
              {formErrors.engine_proxy_mode ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.engine_proxy_mode}</span> : null}
            </label>
            <label>测绘引擎代理
              <Select value={form.engine_proxy} onChange={v => setForm({ ...form, engine_proxy: v })} style={{ width: '100%' }}>
                {(choices.engine_proxy || []).map(c => <Select.Option key={String(c.value)} value={String(c.value)}>{c.label}</Select.Option>)}
              </Select>
              {formErrors.engine_proxy ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.engine_proxy}</span> : null}
            </label>
          </div>
        ) : form.input_type === HISTORY_ENGINE_INPUT_TYPE ? (
          <HistoryEngineResultPicker
            results={engineResults}
            selected={selEngineFiles}
            onSelectionChange={setSelEngineFiles}
            onRefresh={loadHistoryEngineResults}
          />
        ) : form.input_type === '2' ? (
          <div style={{ marginTop: 12 }}>
            <label style={{ display: 'block' }}>fscanx 输出文件
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <Button onClick={() => fscanxFileRef.current?.click()}>选择文件</Button>
                <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  {fscanxFile ? fscanxFile.name : (existingFscanxFileName || '未选择')}
                </span>
              </div>
              <input ref={fscanxFileRef} type="file" onChange={e => setFscanxFile(e.target.files?.[0] || null)} style={{ display: 'none' }} accept=".txt" />
            </label>
            <label style={{ display: 'block', marginTop: 8 }}>冲突策略
              <Select value={form.conflict_strategy || '1'} onChange={v => setForm({ ...form, conflict_strategy: v })} style={{ width: '100%' }}>
                <Select.Option value="1">覆盖</Select.Option>
                <Select.Option value="2">跳过</Select.Option>
              </Select>
            </label>
          </div>
        ) : form.input_type === '6' ? (
          <div style={{ marginTop: 12 }}>
            <label>检索语句
              <Input.TextArea rows={3} value={form.search_query} onChange={e => setForm({ ...form, search_query: e.target.value })} />
            </label>
          </div>
        ) : null)}

        {form.input_type !== '2' && (
        <div style={{ marginTop: 12 }}>
          <label style={{ display: 'block' }}>任务自定义参数 (JSON)
            <Input.TextArea rows={3} value={form.task_args} onChange={e => setForm({ ...form, task_args: e.target.value })} placeholder='JSON格式，如 {"callback":"http://x.com"}' />
          </label>
        </div>
        )}

        {formErrors.form ? <div style={{ color: 'var(--danger)', marginTop: 12, padding: 8, background: 'var(--danger-bg)', borderRadius: 6 }}>{formErrors.form}</div> : null}

        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <Button onClick={() => setFormModal(false)}>取消</Button>
          <Button type="primary" onClick={submitAddForm} loading={submitting}>{editingId ? '保存修改' : '创建任务'}</Button>
        </div>
      </Modal>
    </div>
  )
}

export default AutoScanTaskListPage
