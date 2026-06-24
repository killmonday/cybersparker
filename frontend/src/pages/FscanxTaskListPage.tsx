import React, { useState, useEffect, useCallback } from 'react'
import { Table, Tag, Input, Button, Modal, Space, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { get, post, timeNoSec } from '../api'
import { useAuth } from '../contexts/AuthContext'

const API = '/api/v1/fscanx-tasks'
const ROWS = 13
const DETAIL_PATH = '/fscanx-tasks'

interface TaskRow {
  id: number; task_name: string; zone_name: string; status: number; process: string
  creat_time: string; startTime: string | null; endTime: string | null
  asset_count: number; detail_count: number
  conflict_strategy: number; failed: boolean; last_error: string
}

const STATUS_MAP: Record<number, { label: string; color: string }> = {
  1: { label: '完成', color: 'green' },
  2: { label: '运行中', color: 'blue' },
  3: { label: '停止', color: 'default' },
  4: { label: '暂停', color: 'orange' },
}

const FscanxTaskListPage: React.FC = () => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<{ rows: TaskRow[]; total: number; total_pages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await get<{ status: boolean; rows: TaskRow[]; total: number; total_pages: number }>(
        `${API}?page=${page}&rows_per_page=${ROWS}&q=${encodeURIComponent(q)}`
      )
      if (res.status) setData(res)
    } catch { message.error('加载失败') }
    finally { setLoading(false) }
  }, [page, q])

  useEffect(() => { load() }, [load])

  // 轮询：运行中任务每 3s 刷新
  useEffect(() => {
    const hasRunning = data?.rows.some(r => r.status === 2)
    if (!hasRunning) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [data, load])

  function doSearch() { setQ(searchInput); setPage(1) }

  async function handleDelete(id: number) {
    Modal.confirm({
      title: '确定删除该导入任务？', content: '服务详情和关联数据将一并删除。', okText: '删除', okType: 'danger',
      onOk: async () => {
        try {
          const res = await post<{ status: boolean; tips?: string }>(`${API}/${id}/delete`, {})
          if (res.status) { message.success('已删除'); load() }
          else message.error(res.tips || '删除失败')
        } catch { message.error('删除请求失败') }
      },
    })
  }

  const cols: ColumnsType<TaskRow> = [
    { title: '任务ID', dataIndex: 'id', width: 80 },
    { title: '任务名称', dataIndex: 'task_name', ellipsis: true },
    {
      title: '区域', dataIndex: 'zone_name', key: 'zone_name', width: 90,
      render: (_: unknown, r: TaskRow) => r.zone_name || '—',
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: number, r: TaskRow) => (
        <Space>
          <Tag color={STATUS_MAP[s]?.color}>{STATUS_MAP[s]?.label || s}</Tag>
          {r.failed && <Tag color="red">失败</Tag>}
        </Space>
      ),
    },
    { title: '进度', dataIndex: 'process', width: 80 },
    { title: '资产数', dataIndex: 'asset_count', width: 80 },
    { title: '服务详情数', dataIndex: 'detail_count', width: 100 },
    {
      title: '冲突策略', dataIndex: 'conflict_strategy', width: 100,
      render: (v: number) => v === 1 ? '覆盖' : '跳过',
    },
    {
      title: '创建时间', dataIndex: 'creat_time', width: 140,
      render: (v: string) => v ? timeNoSec(v) : '-',
    },
    {
      title: '开始时间', dataIndex: 'startTime', width: 140,
      render: (v: string | null) => v ? timeNoSec(v) : '-',
    },
    {
      title: '操作', key: 'actions', width: 160, fixed: 'right',
      render: (_: unknown, r: TaskRow) => (
        <Space>
          <Button type="link" size="small" onClick={() => nav(`${DETAIL_PATH}/${r.id}`)}>查看结果</Button>
          {canWrite && r.status !== 2 && <Button type="link" size="small" danger onClick={() => handleDelete(r.id)}>删除</Button>}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ marginBottom: 16 }}>fscanx 导入任务</h2>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search value={searchInput} onChange={e => setSearchInput(e.target.value)} onSearch={doSearch} placeholder="搜索任务名" style={{ width: 300 }} allowClear />
      </Space>
      <Table
        columns={cols} dataSource={data?.rows || []} rowKey="id" loading={loading}
        pagination={{ current: page, total: data?.total || 0, pageSize: ROWS, onChange: setPage, showTotal: t => `共 ${t} 条` }}
        scroll={{ x: 1100 }} size="middle"
      />
    </div>
  )
}

export default FscanxTaskListPage
