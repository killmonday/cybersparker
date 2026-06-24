import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Table, Tag, Input, Button, Modal, Space, Select, message } from 'antd'
import type { ZoneItem } from '../types/zone'
import type { ColumnsType } from 'antd/es/table'
import { useTaskPolling } from '../hooks/useTaskPolling'
import { get, post, postForm, ApiError , timeNoSec} from '../api'
import { useAuth } from '../contexts/AuthContext'

interface DirscanTaskItem {
  id: number
  task_name: string
  zone_name: string
  status: number
  status_key: string
  status_label: string
  status_class: string
  phase: number
  phase_label: string
  progress: string
  creatime: string | null
  start_time: string | null
  end_time: string | null
}

interface DirscanTaskListResponse {
  items: DirscanTaskItem[]
  page: number; rows_per_page: number; total: number; total_pages: number
  filters: { q: string }
}

interface DirscanPollData {
  status: string; phase: number; progress_done: number; progress_total: number
}

interface DictOption { id: number; name: string }
interface ProxyOption { id: number; proxy_type_label: string; proxy_address: string; proxy_port: number }
interface AutoTaskOption { id: number; task_name: string }

interface Props { apiUrl: string }

const ROWS_PER_PAGE = 13

const DirscanTaskListPage: React.FC<Props> = ({ apiUrl }) => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [q, setQ] = useState(search.get('q') ?? '')
  const [searchInput, setSearchInput] = useState(search.get('q') ?? '')
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [refreshKey, setRefreshKey] = useState(0)
  const [data, setData] = useState<DirscanTaskListResponse | null>(null)
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
    () => (data?.items || []).filter(t => t.status_key === 'running').map(t => t.id),
    [data?.items],
  )
  const pollData = useTaskPolling<DirscanPollData>('/api/v1/dirscan-tasks/status-batch', pollableIds)

  const [opModal, setOpModal] = useState<{ open: boolean; taskId: number; taskName: string; action: string; actionLabel: string }>({ open: false, taskId: 0, taskName: '', action: '', actionLabel: '' })
  const [delModal, setDelModal] = useState<{ open: boolean; taskId: number; taskName: string }>({ open: false, taskId: 0, taskName: '' })

  // Form state
  const [formModal, setFormModal] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<Record<string, string>>({
    task_name: '', description: '', input_mode: '1', search_query: '',
    pool_size: '200', concurrency: '100', max_body_size: '3145728', max_truncate_size: '1048576',
    proxy: '', enable_vuln_scan: 'true', vuln_thread_num: '60', sleep_time: '0',
    http_timeout: '10', task_args: '', zone: '',
  })
  const [formDictIds, setFormDictIds] = useState<number[]>([])
  const [formSourceTasks, setFormSourceTasks] = useState<number[]>([])
  const [targetFile, setTargetFile] = useState<File | null>(null)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [dicts, setDicts] = useState<DictOption[]>([])
  const [proxies, setProxies] = useState<ProxyOption[]>([])
  const [autoTasks, setAutoTasks] = useState<AutoTaskOption[]>([])
  const [sourceTaskPage, setSourceTaskPage] = useState(1)
  const [sourceTaskTotalPages, setSourceTaskTotalPages] = useState(1)
  const [sourceTaskTotal, setSourceTaskTotal] = useState(0)
  const [sourceTaskSearch, setSourceTaskSearch] = useState('')
  const [sourceTaskLoading, setSourceTaskLoading] = useState(false)
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
    get<DirscanTaskListResponse>(`${apiUrl}?${params.toString()}`)
      .then(setData)
      .finally(() => setLoading(false))
  }, [apiUrl, page, q, refreshKey])

  useEffect(() => { loadList() }, [loadList])

  function handleSearch() {
    if (searchInput.trim()) { setQ(searchInput.trim()); setPage(1) }
    else { setRefreshKey(k => k + 1) }
  }

  // Load dicts & proxies (static options)
  function loadFormOptions() {
    get<any>('/api/v1/dicts?rows_per_page=1000').then(d => setDicts(d.items || [])).catch(() => {})
    get<any>('/api/v1/proxies?rows_per_page=100').then(d => setProxies(d.items || [])).catch(() => {})
    loadAutoTasks(1, '')
  }

  // Load auto tasks with pagination & search
  function loadAutoTasks(pageNum: number, search: string) {
    setSourceTaskLoading(true)
    const params = new URLSearchParams()
    params.set('page', String(pageNum))
    params.set('rows_per_page', '10')
    if (search) params.set('q', search)
    get<any>(`/api/v1/identify-tasks?${params.toString()}`)
      .then(d => {
        setAutoTasks(d.items || [])
        setSourceTaskTotalPages(d.total_pages || 1)
        setSourceTaskTotal(d.total || 0)
      })
      .catch(() => {})
      .finally(() => setSourceTaskLoading(false))
  }

  function getStatusLabel(item: DirscanTaskItem) {
    const p = pollData[item.id]
    const k = p?.status ?? item.status_key
    if (k === 'running') return { label: '运行中', color: 'green' } as const
    if (k === 'paused') return { label: '已暂停', color: 'orange' } as const
    if (k === 'stopped') return { label: '已停止', color: 'red' } as const
    if (k === 'finished') return { label: '已完成', color: 'green' } as const
    if (k === 'pending') return { label: '待执行', color: 'blue' } as const
    return { label: item.status_label, color: 'default' } as const
  }

  function openOperateModal(taskId: number, taskName: string, action: string) {
    const labels: Record<string, string> = { '0': '启动', '1': '重启', pause: '暂停', resume: '续跑', '2': '停止', rerun: '重跑' }
    setSubmitting(false)
    setOpModal({ open: true, taskId, taskName, action, actionLabel: labels[action] || action })
  }

  function confirmOperate() {
    setSubmitting(true)
    const fd = new FormData(); fd.append('status', opModal.action)
    postForm<{ status: boolean }>(`/api/v1/dirscan-tasks/${opModal.taskId}/operate`, fd)
      .then((p) => { if (p.status) { setOpModal(prev => ({ ...prev, open: false })); loadList() } else message.error((p as any).tips || '操作失败') })
      .catch(() => {})
      .finally(() => setSubmitting(false))
  }

  function confirmDelete() {
    setSubmitting(true)
    postForm<{ status: boolean }>(`/api/v1/dirscan-tasks/${delModal.taskId}/delete`, new FormData())
      .then((p) => { if (p.status) { setDelModal({ open: false, taskId: 0, taskName: '' }); loadList() } else message.error('删除失败') })
      .catch(() => {})
      .finally(() => setSubmitting(false))
  }

  // Form: open add
  function openAddForm() {
    setEditingId(null)
    setForm({ task_name: '', description: '', input_mode: '1', search_query: '', pool_size: '200', concurrency: '100', max_body_size: '3145728', max_truncate_size: '1048576', proxy: '', enable_vuln_scan: 'true', vuln_thread_num: '60', sleep_time: '0', http_timeout: '10', task_args: '', zone: '' })
    setFormDictIds([]); setFormSourceTasks([]); setTargetFile(null); setFormErrors({})
    loadFormOptions(); setFormModal(true)
  }

  // Form: open edit
  function openEditForm(id: number) {
    setEditingId(id); setFormErrors({})
    loadFormOptions()
    get<{ status: boolean; data: any }>(`/api/v1/dirscan-tasks/${id}`)
      .then(d => {
        if (d.status && d.data) {
          const dd = d.data
          setForm({
            task_name: dd.task_name || '', description: dd.description || '',
            input_mode: String(dd.input_mode ?? 1), search_query: dd.search_query || '',
            pool_size: String(dd.pool_size ?? 200), concurrency: String(dd.concurrency ?? 100),
            max_body_size: String(dd.max_body_size ?? 3145728), max_truncate_size: String(dd.max_truncate_size ?? 1048576),
            proxy: dd.proxy ? String(dd.proxy) : '', enable_vuln_scan: dd.enable_vuln_scan ? 'true' : 'false',
            vuln_thread_num: String(dd.vuln_thread_num ?? 60),
            sleep_time: String(dd.sleep_time ?? 0),
            http_timeout: String(dd.http_timeout ?? 10),
            task_args: dd.task_args || '',
            zone: dd.zone_id ? String(dd.zone_id) : '',
          })
          setFormDictIds(dd.dicts || [])
          setFormSourceTasks(dd.source_tasks || [])
          setTargetFile(null)
          setFormModal(true)
        } else { message.error('获取任务详情失败') }
      })
      .catch(() => message.error('获取任务详情失败'))
  }

  // Form: submit
  function submitForm() {
    if (form.task_args && form.task_args.trim()) {
      try { JSON.parse(form.task_args) } catch { alert('task_args JSON 格式错误'); return }
    }
    setSubmitting(true); setFormErrors({})
    const fd = new FormData()
    Object.entries(form).forEach(([k, v]) => { if (v) fd.append(k, v) })
    formSourceTasks.forEach(id => fd.append('source_tasks', String(id)))
    formDictIds.forEach(id => fd.append('dicts', String(id)))
    if (targetFile) fd.append('target', targetFile)

    const url = editingId ? `/api/v1/dirscan-tasks/${editingId}/update` : '/api/v1/dirscan-tasks/create'
    postForm<{ status: boolean; error?: Record<string, string>; tips?: string }>(url, fd)
      .then((p) => {
        if (p.status) { setFormModal(false); message.success(editingId ? '修改成功' : '创建成功'); loadList() }
      })
      .catch((e) => { setFormErrors({ form: e instanceof ApiError ? e.message : '操作失败' }) })
      .finally(() => setSubmitting(false))
  }

  const columns: ColumnsType<DirscanTaskItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 50 },
    { title: '任务名称', dataIndex: 'task_name', key: 'task_name', width: 200, ellipsis: true },
    {
      title: '区域', dataIndex: 'zone_name', key: 'zone_name', width: 90,
      render: (v: string) => v || '—',
    },
    {
      title: '状态', key: 'status', width: 80,
      render: (_: any, record: DirscanTaskItem) => {
        const st = getStatusLabel(record)
        return <Tag color={st.color}>{st.label}</Tag>
      },
    },
    {
      title: '阶段', key: 'phase', width: 110,
      render: (_: any, record: DirscanTaskItem) => {
        const pd = pollData[record.id]
        const phaseMap: Record<number, string> = { 0: '未初始化', 1: '正在Web扫描', 2: '正在漏洞扫描', 3: '清理中' }
        return pd ? (phaseMap[pd.phase] || String(pd.phase)) : record.phase_label
      },
    },
    {
      title: '进度', key: 'progress', width: 90,
      render: (_: any, record: DirscanTaskItem) => {
        const pd = pollData[record.id]
        return pd ? `${pd.progress_done}/${pd.progress_total}` : record.progress
      },
    },
    {
      title: '开始时间', key: 'start_time', width: 140,
      render: (_: any, record: DirscanTaskItem) => timeNoSec(record.start_time), ellipsis: true,
    },
    {
      title: '创建时间', dataIndex: 'creatime', key: 'creatime', width: 130,
      render: (v: string | null) => timeNoSec(v), ellipsis: true,
    },
    {
      title: '操作', key: 'actions', width: 320,
      render: (_: any, record: DirscanTaskItem) => {
        const sk = pollData[record.id]?.status ?? record.status_key
        const btns: React.ReactNode[] = []
        if (canWrite) {
          btns.push(<a key="edit" onClick={() => openEditForm(record.id)} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>编辑</a>)
          btns.push(<a key="delete" onClick={() => setDelModal({ open: true, taskId: record.id, taskName: record.task_name })} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>删除</a>)
        }
        btns.push(<a key="results" onClick={() => window.open(`/react-shell/dirscan-results?task_id=${record.id}`, '_blank')} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>查看结果</a>)
        if (canWrite) {
          if (sk === 'pending') btns.push(<a key="start" onClick={() => openOperateModal(record.id, record.task_name, '0')} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>启动</a>)
          if (sk === 'running') btns.push(<a key="pause" onClick={() => openOperateModal(record.id, record.task_name, 'pause')} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>暂停</a>)
          if (sk === 'paused' || sk === 'stopped') btns.push(<a key="resume" onClick={() => openOperateModal(record.id, record.task_name, 'resume')} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>续跑</a>)
          if (sk === 'running' || sk === 'paused') btns.push(<a key="stop" onClick={() => openOperateModal(record.id, record.task_name, '2')} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>停止</a>)
          if (sk === 'stopped' || sk === 'finished') btns.push(<a key="rerun" onClick={() => openOperateModal(record.id, record.task_name, 'rerun')} style={{ fontSize: 12, marginRight: 6, cursor: 'pointer' }}>重跑</a>)
        }
        return <>{btns}</>
      },
    },
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>目录扫描任务管理</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && selectedIds.size > 0 && <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>}
            {canWrite && <Button type="primary" onClick={openAddForm}>新增任务</Button>}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <Input value={searchInput} onChange={e => setSearchInput(e.target.value)} onPressEnter={handleSearch} placeholder="搜索任务名称" style={{ width: 240 }} />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </div>

        {loading ? (
          <div className="react-shell-panel"><span>正在加载目录扫描任务...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<DirscanTaskItem>
                columns={columns}
                dataSource={data?.items || []}
                rowKey="id"
                loading={loading}
                pagination={false}
                size="small"
                rowSelection={canWrite ? { selectedRowKeys: Array.from(selectedIds), onChange: (keys) => setSelectedIds(new Set(keys as number[])) } : undefined}
              />
            </div>
            <div className="react-pagination-bar">
              <span>第 {data?.page ?? 1} / {data?.total_pages ?? 1} 页，共 {data?.total ?? 0} 条</span>
              <Space>
                <input type="number" min={1} max={data?.total_pages ?? 1} placeholder="页" style={{ width: 50, height: 30, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
                  onKeyDown={e => { if (e.key !== 'Enter') return; const n = parseInt((e.target as HTMLInputElement).value, 10); if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n) }} />
                <Button onClick={() => { const inp = document.querySelector('.react-pagination-bar input[type="number"]') as HTMLInputElement; if (inp) { const n = parseInt(inp.value, 10); if (n && n >= 1 && n <= (data?.total_pages ?? 1)) setPage(n) } }}>跳转</Button>
                <Button disabled={(data?.page ?? 1) <= 1} onClick={() => setPage(c => Math.max(1, c - 1))}>上一页</Button>
                <Button disabled={!data || data.page >= data.total_pages} onClick={() => setPage(c => c + 1)}>下一页</Button>
              </Space>
            </div>
          </>
        )}
      </div>

      {/* Operate Modal */}
      <Modal title="操作确认" open={opModal.open} onCancel={() => setOpModal(prev => ({ ...prev, open: false }))} footer={null} width={480}>
        <p>确认对 <strong>{opModal.taskName}</strong> 执行 <strong>{opModal.actionLabel}</strong>？</p>
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <Button onClick={() => setOpModal(prev => ({ ...prev, open: false }))}>取消</Button>
          <Button type="primary" onClick={confirmOperate} loading={submitting}>确认</Button>
        </div>
      </Modal>

      {/* Delete Modal */}
      <Modal title="删除确认" open={delModal.open} onCancel={() => setDelModal({ open: false, taskId: 0, taskName: '' })} footer={null} width={480}>
        <p>确认删除 <strong>{delModal.taskName}</strong>？</p>
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <Button onClick={() => setDelModal({ open: false, taskId: 0, taskName: '' })}>取消</Button>
          <Button danger type="primary" onClick={confirmDelete} loading={submitting}>确认删除</Button>
        </div>
      </Modal>

      {/* Add/Edit Form Modal */}
      <Modal title={editingId ? '编辑目录扫描任务' : '新增目录扫描任务'} open={formModal} onCancel={() => setFormModal(false)} footer={null} width={600}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <label style={{ gridColumn: 'span 2' }}>任务名称
            <Input value={form.task_name} onChange={e => setForm({ ...form, task_name: e.target.value })} />
            {formErrors.task_name ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.task_name}</span> : null}
          </label>
          <label style={{ gridColumn: 'span 2' }}>描述
            <Input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="可选" />
          </label>
          <label>输入模式
            <Select value={form.input_mode} onChange={v => setForm({ ...form, input_mode: v })} style={{ width: '100%' }}>
              <Select.Option value="0">手动选择任务</Select.Option>
              <Select.Option value="1">全选所有任务</Select.Option>
              <Select.Option value="2">检索语句</Select.Option>
            </Select>
          </label>
          <label>并发池大小 <span style={{fontSize:11,color:'var(--text-secondary)',whiteSpace:'nowrap'}}>池内host被随机抽取扫描，越大越随机</span>
            <Input type="number" value={form.pool_size} onChange={e => setForm({ ...form, pool_size: e.target.value })} />
          </label>
          <label>并发数
            <Input type="number" value={form.concurrency} onChange={e => setForm({ ...form, concurrency: e.target.value })} />
          </label>
          <label>代理
            <Select value={form.proxy || undefined} onChange={v => setForm({ ...form, proxy: v || '' })} style={{ width: '100%' }} allowClear placeholder="不使用代理">
              {proxies.map(p => <Select.Option key={p.id} value={String(p.id)}>{p.proxy_type_label}://{p.proxy_address}:{p.proxy_port}</Select.Option>)}
            </Select>
          </label>
          <label>漏洞扫描
            <Select value={form.enable_vuln_scan} onChange={v => setForm({ ...form, enable_vuln_scan: v })} style={{ width: '100%' }}>
              <Select.Option value="true">是</Select.Option>
              <Select.Option value="false">否</Select.Option>
            </Select>
          </label>
          <label>漏洞线程数
            <Input type="number" value={form.vuln_thread_num} onChange={e => setForm({ ...form, vuln_thread_num: e.target.value })} />
          </label>
          <label>休眠时间(秒)
            <Input type="number" value={form.sleep_time} onChange={e => setForm({ ...form, sleep_time: e.target.value })} />
          </label>
          <label>HTTP超时(秒)
            <Input type="number" value={form.http_timeout} onChange={e => setForm({ ...form, http_timeout: e.target.value })} />
          </label>
          <label>最大Body(字节)
            <Input type="number" value={form.max_body_size} onChange={e => setForm({ ...form, max_body_size: e.target.value })} />
          </label>
          <label>最大截断(字节)
            <Input type="number" value={form.max_truncate_size} onChange={e => setForm({ ...form, max_truncate_size: e.target.value })} />
          </label>
          <label>扫描区域
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
          </label>
          {form.input_mode === '2' ? (
            <label style={{ gridColumn: 'span 2' }}>检索语句
              <Input value={form.search_query} onChange={e => setForm({ ...form, search_query: e.target.value })} placeholder='如 product:"nginx" && port:"443"' />
              {formErrors.search_query ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.search_query}</span> : null}
            </label>
          ) : form.input_mode === '0' ? (
            <label style={{ gridColumn: 'span 2' }}>源任务（手动选择）
              <div style={{
                border: '1px solid var(--border)',
                borderRadius: 8,
                background: 'var(--bg-surface)',
              }}>
                {/* 搜索 + 操作栏 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
                  <Input
                    value={sourceTaskSearch}
                    onChange={e => setSourceTaskSearch(e.target.value)}
                    onPressEnter={() => { setSourceTaskPage(1); loadAutoTasks(1, sourceTaskSearch) }}
                    placeholder="搜索任务名称"
                    size="small"
                    style={{ flex: 1, height: 28, fontSize: 12 }}
                  />
                  <Button size="small" onClick={() => { setSourceTaskPage(1); loadAutoTasks(1, sourceTaskSearch) }}
                    style={{ fontSize: 11, height: 28, padding: '0 8px' }}>
                    搜索
                  </Button>
                  {formSourceTasks.length > 0 && (
                    <Button size="small" type="link" danger onClick={() => setFormSourceTasks([])}
                      style={{ fontSize: 11, height: 28, padding: '0 4px' }}>
                      取消全选
                    </Button>
                  )}
                </div>

                {/* 任务列表 */}
                <div style={{ maxHeight: 160, overflow: 'auto', padding: '4px 6px' }}>
                  {sourceTaskLoading ? (
                    <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--text-muted)', fontSize: 12 }}>加载中…</div>
                  ) : autoTasks.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--text-muted)', fontSize: 12 }}>
                      {sourceTaskSearch ? '无匹配任务' : '暂无可选任务'}
                    </div>
                  ) : (
                    autoTasks.map(t => {
                      const checked = formSourceTasks.includes(t.id)
                      return (
                        <label key={t.id} style={{
                          display: 'flex', alignItems: 'center', padding: '3px 6px', cursor: 'pointer', fontSize: 12,
                          borderRadius: 4, marginBottom: 1,
                          background: checked ? '#e6f4ff' : 'transparent',
                          transition: 'background 0.15s',
                        }}>
                          <input type="checkbox" checked={checked}
                            onChange={e => { if (e.target.checked) setFormSourceTasks(prev => [...prev, t.id]); else setFormSourceTasks(prev => prev.filter(id => id !== t.id)) }}
                            style={{ marginRight: 6, accentColor: '#1677ff' }} />
                          <span style={{ color: 'var(--text-muted)', fontWeight: 500, marginRight: 6, minWidth: 36 }}>[{t.id}]</span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.task_name}</span>
                        </label>
                      )
                    })
                  )}
                </div>

                {/* 分页栏 */}
                {sourceTaskTotalPages > 1 && (
                  <div style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '4px 8px', borderTop: '1px solid var(--border)', background: 'var(--bg-subtle)',
                    fontSize: 11, color: 'var(--text-muted)',
                    borderBottomLeftRadius: 7, borderBottomRightRadius: 7,
                  }}>
                    <span>共 {sourceTaskTotal} 项</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Button size="small" disabled={sourceTaskPage <= 1} onClick={() => {
                        const prev = sourceTaskPage - 1; setSourceTaskPage(prev); loadAutoTasks(prev, sourceTaskSearch)
                      }} style={{ fontSize: 11, height: 24, padding: '0 6px' }}>上一页</Button>
                      <span style={{ minWidth: 50, textAlign: 'center' }}>{sourceTaskPage}/{sourceTaskTotalPages}</span>
                      <Button size="small" disabled={sourceTaskPage >= sourceTaskTotalPages} onClick={() => {
                        const next = sourceTaskPage + 1; setSourceTaskPage(next); loadAutoTasks(next, sourceTaskSearch)
                      }} style={{ fontSize: 11, height: 24, padding: '0 6px' }}>下一页</Button>
                    </div>
                  </div>
                )}
              </div>
              {formErrors.source_tasks ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.source_tasks}</span> : null}
            </label>
          ) : null}
          <label style={{ gridColumn: 'span 2' }}>字典选择
            <div style={{ maxHeight: 150, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }}>
              {dicts.length === 0 ? <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>加载中…</span> : dicts.map(d => (
                <label key={d.id} style={{ display: 'inline-flex', alignItems: 'center', marginRight: 14, fontSize: 12, cursor: 'pointer' }}>
                  <input type="checkbox" checked={formDictIds.includes(d.id)}
                    onChange={e => { if (e.target.checked) setFormDictIds(prev => [...prev, d.id]); else setFormDictIds(prev => prev.filter(id => id !== d.id)) }}
                    style={{ marginRight: 4 }} />
                  {d.name}
                </label>
              ))}
            </div>
            {formErrors.dicts ? <span style={{ color: 'var(--danger)', fontSize: 12 }}>{formErrors.dicts}</span> : null}
          </label>
        </div>
        <div style={{ marginTop: 12 }}>
          <label style={{ display: 'block' }}>任务自定义参数 (JSON)
            <Input.TextArea rows={3} value={form.task_args} onChange={e => setForm({ ...form, task_args: e.target.value })} placeholder='JSON格式，如 {"callback":"http://x.com"}' />
          </label>
        </div>
        {formErrors.form ? <div style={{ color: 'var(--danger)', marginTop: 12, padding: 8, background: 'var(--danger-bg)', borderRadius: 6 }}>{formErrors.form}</div> : null}
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <Button onClick={() => setFormModal(false)}>取消</Button>
          <Button type="primary" onClick={submitForm} loading={submitting}>
            {editingId ? '保存修改' : '创建任务'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}

export default DirscanTaskListPage
