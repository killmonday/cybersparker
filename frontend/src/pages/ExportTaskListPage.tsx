import React, { useState, useEffect, useCallback } from 'react'
import { Table, Tag, Button, Space, Modal, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { get, post, timeNoSec } from '../api'
import type { ExportTaskItem, ExportTaskListResponse } from '../types/task'
import { useAuth } from '../contexts/AuthContext'

interface Props {
  apiUrl: string
}

const ROWS_PER_PAGE = 13

const STATUS_COLORS: Record<string, string> = {
  '已完成': 'green',
  '处理中': 'blue',
  '失败': 'red',
  '等待中': 'orange',
}

const ExportTaskListPage: React.FC<Props> = ({ apiUrl }) => {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const search = new URLSearchParams(window.location.search)
  const [page, setPage] = useState(Number(search.get('page') ?? '1'))
  const [data, setData] = useState<ExportTaskListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const loadList = useCallback(() => {
    const params = new URLSearchParams()
    params.set('page', String(page))
    params.set('rows_per_page', String(ROWS_PER_PAGE))
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    setLoading(true)
    get<ExportTaskListResponse>(`${apiUrl}?${params.toString()}`).then(setData)
      .finally(() => setLoading(false))
  }, [apiUrl, page])

  useEffect(() => { loadList() }, [loadList])

  function confirmBatchDelete() {
    Modal.confirm({
      title: `确定删除选中的 ${selectedIds.size} 个导出任务？`, content: '删除后无法恢复。', okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: handleBatchDelete,
    })
  }
  async function handleBatchDelete() {
    setDeleting(true)
    try {
      const res = await post<{ status: boolean; tips?: string }>(`${apiUrl}/batch-delete`, { uids: Array.from(selectedIds) })
      if (res.status) { message.success(`已删除 ${selectedIds.size} 个导出任务`); setSelectedIds(new Set()); loadList() }
      else message.error(res.tips || '删除失败')
    } catch { message.error('删除请求失败') }
    finally { setDeleting(false) }
  }

  const columns: ColumnsType<ExportTaskItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '类型', dataIndex: 'task_type_label', key: 'task_type_label', width: 100 },
    { title: '任务名', dataIndex: 'task_name', key: 'task_name', width: 160, ellipsis: true, render: (v: string) => v || '—' },
    {
      title: '状态', dataIndex: 'status_label', key: 'status_label', width: 100,
      render: (label: string, record: ExportTaskItem) => (
        <Tag color={STATUS_COLORS[label] || STATUS_COLORS[record.status] || 'default'}>{label}</Tag>
      ),
    },
    { title: '行数', dataIndex: 'total_rows', key: 'total_rows', width: 80, render: (v: number | null) => v ?? '—' },
    { title: '创建时间', dataIndex: 'creatime', key: 'creatime', width: 130, render: (v: string | null) => timeNoSec(v), ellipsis: true },
    {
      title: '操作', key: 'download', width: 80,
      render: (_: any, record: ExportTaskItem) => {
        const u = record.download_url
        if (!u) return '—'
        return u.startsWith('/') || u.startsWith('http://') || u.startsWith('https://')
          ? <a href={u}>下载</a> : '—'
      },
    },
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>导出任务</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && selectedIds.size > 0 && <Button danger loading={deleting} onClick={confirmBatchDelete}>删除选中 ({selectedIds.size})</Button>}
            <Button onClick={loadList}>刷新</Button>
          </div>
        </div>

        {loading ? (
          <div className="react-shell-panel"><span>加载中...</span></div>
        ) : (
          <>
            <div className="react-task-table-wrap">
              <Table<ExportTaskItem>
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
    </div>
  )
}

export default ExportTaskListPage
