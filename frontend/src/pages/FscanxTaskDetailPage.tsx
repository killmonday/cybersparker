import React, { useState, useEffect, useCallback } from 'react'
import { Table, Tag, Select, Button, Modal } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { get, post, timeNoSec } from '../api'
import { useAuth } from '../contexts/AuthContext'

const API = '/api/v1/fscanx-tasks'

interface DetailRow {
  id: number; protocol: string; host: string; port: number
  result_type: number; result_type_label: string
  result_preview: string; result_full: string; created_at: string
}

interface TaskInfo {
  id: number; task_name: string; status: number; process: string
  creat_time: string; startTime: string | null; endTime: string | null
}

const RESULT_COLORS: Record<number, string> = {
  1: 'red', 2: 'blue', 3: 'purple', 4: 'cyan', 5: 'geekblue', 6: 'orange', 7: 'lime', 8: 'green', 9: 'volcano',
}

const FscanxTaskDetailPage: React.FC = () => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const { taskId } = useParams<{ taskId: string }>()
  const nav = useNavigate()
  const [task, setTask] = useState<TaskInfo | null>(null)
  const [detailCount, setDetailCount] = useState(0)
  const [data, setData] = useState<{ rows: DetailRow[]; total: number; total_pages: number; result_type_choices: { value: number; label: string }[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [filterType, setFilterType] = useState<string>('')
  const ROWS = 20

  const load = useCallback(async () => {
    if (!taskId) return
    setLoading(true)
    try {
      const res = await get<{
        status: boolean; task: TaskInfo; detail_count: number; rows: DetailRow[]; total: number; total_pages: number
        result_type_choices: { value: number; label: string }[]
      }>(`${API}/${taskId}/details?page=${page}&rows_per_page=${ROWS}&result_type=${filterType}`)
      if (res.status) {
        setTask(res.task)
        setDetailCount(res.detail_count || 0)
        setData(res)
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [taskId, page, filterType])

  useEffect(() => { load() }, [load])

  function showFull(r: DetailRow) {
    Modal.info({
      title: `${r.protocol}://${r.host}:${r.port} — ${r.result_type_label}`,
      width: 700, maskClosable: true,
      content: <pre style={{ maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 13 }}>{r.result_full}</pre>,
    })
  }

  async function deleteRow(r: DetailRow) {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除 ${r.protocol}://${r.host}:${r.port} 的 ${r.result_type_label} 记录吗？`,
      okText: '删除', cancelText: '取消', okType: 'danger',
      onOk: async () => {
        await post(`${API}/details/${r.id}/delete`, {})
        if (page === 1) load(); else setPage(1)
      },
    })
  }

  const cols: ColumnsType<DetailRow> = [
    { title: '协议', dataIndex: 'protocol', width: 80 },
    { title: '主机', dataIndex: 'host', width: 160, ellipsis: true },
    { title: '端口', dataIndex: 'port', width: 70 },
    {
      title: '成果类型', dataIndex: 'result_type', width: 130,
      render: (v: number) => <Tag color={RESULT_COLORS[v] || 'default'}>{data?.result_type_choices.find(c => c.value === v)?.label || v}</Tag>,
    },
    {
      title: '结果摘要', dataIndex: 'result_preview',
      render: (v: string, r: DetailRow) => v ? (
        <a onClick={() => showFull(r)} style={{ maxWidth: 1000, overflow: 'hidden', textOverflow: 'ellipsis', display: 'inline-block', cursor: 'pointer' }}>
          {v}{v.length < (r.result_full || '').length ? '...' : ''}
        </a>
      ) : '-',
    },
    { title: '时间', dataIndex: 'created_at', width: 140, render: (v: string) => v ? timeNoSec(v) : '-' },
    ...(canWrite ? [{
      title: '操作', key: 'actions', width: 80, fixed: 'right' as const,
      render: (_: unknown, r: DetailRow) => (
        <Button type="link" danger size="small" onClick={() => deleteRow(r)}>删除</Button>
      ),
    }] : []),
  ]

  return (
    <div style={{ padding: 16 }}>
      <Button onClick={() => nav('/fscanx-tasks')} style={{ marginBottom: 12 }}>{'< 返回列表'}</Button>

      <div style={{ background: '#fff', borderRadius: 8, padding: '16px 20px', marginBottom: 16, boxShadow: '0 1px 3px rgba(0,0,0,.06)' }}>
        <h2 style={{ margin: '0 0 8px 0' }}>{task?.task_name || '加载中...'}</h2>
        {task && (
          <span style={{ color: '#888', fontSize: 13 }}>
            共 {detailCount} 条服务详情
            {task.startTime && <span>　开始 {timeNoSec(task.startTime)}</span>}
            {task.endTime && <span>　完成 {timeNoSec(task.endTime)}</span>}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 13, color: '#666' }}>类型筛选：</span>
        <Select
          value={filterType} onChange={(v: string) => { setFilterType(v); setPage(1) }} style={{ width: 150 }} allowClear placeholder="全部类型"
          options={(data?.result_type_choices || []).map(c => ({ value: String(c.value), label: c.label }))}
        />
      </div>

      <Table
        columns={cols} dataSource={data?.rows || []} rowKey="id" loading={loading}
        pagination={{ current: page, total: data?.total || 0, pageSize: ROWS, onChange: setPage, showTotal: t => `共 ${t} 条` }}
        scroll={{ x: 900 }} size="middle"
      />
    </div>
  )
}

export default FscanxTaskDetailPage
