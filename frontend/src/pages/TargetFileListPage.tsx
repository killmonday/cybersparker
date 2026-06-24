import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Table, Modal, Space, Upload, message, Input, Tag, Tooltip, Card, Popconfirm,
} from 'antd'
import {
  UploadOutlined, DownloadOutlined, DeleteOutlined, FileTextOutlined, SearchOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import { get, post, postForm, del } from '../api'
import { useAuth } from '../contexts/AuthContext'

const API_BASE = '/api/v1/target-files'

interface TargetFile {
  file_name: string
  mtime: string
  size: number
  size_display: string
  lines: number
}

interface RefInfo {
  model: string
  task_id: number
}

export default function TargetFileListPage() {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const [files, setFiles] = useState<TargetFile[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])
  const [deleteTarget, setDeleteTarget] = useState<{ filename: string; refs: RefInfo[] } | null>(null)
  const [batchResult, setBatchResult] = useState<{ results: any[] } | null>(null)
  const [uploading, setUploading] = useState(false)

  const fetchFiles = useCallback(async () => {
    setLoading(true)
    try {
      const data = await get<any>(API_BASE)
      if (data?.status && data?.data?.files) setFiles(data.data.files)
    } catch {
      message.error('加载文件列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchFiles() }, [fetchFiles])

  const filtered = useMemo(() => {
    if (!search.trim()) return files
    const kw = search.toLowerCase()
    return files.filter(f => f.file_name.toLowerCase().includes(kw))
  }, [files, search])

  const handleUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onSuccess, onError } = options as any
    const f = file as File
    if (!f.name.toLowerCase().endsWith('.txt')) {
      message.error('仅支持 .txt 后缀的文本文件')
      onError?.(new Error('invalid ext'))
      return
    }
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', f)
      const data: any = await postForm('/api/v1/target-files/upload', form)
      if (data?.status) {
        const savedName = data.data.file_name
        if (data.data.original_name) {
          message.success(`上传成功，文件名已自动重命名为 ${savedName}`)
        } else {
          message.success('上传成功')
        }
        onSuccess?.(data)
        fetchFiles()
      } else {
        message.error(data?.data?.error || '上传失败')
        onError?.(new Error(data?.data?.error))
      }
    } catch {
      message.error('上传失败')
      onError?.(new Error('upload failed'))
    } finally {
      setUploading(false)
    }
  }

  const handleDownload = (filename: string) => {
    window.open(`${API_BASE}/${encodeURIComponent(filename)}/download`, '_blank')
  }

  const handleDeleteSingle = async (filename: string) => {
    try {
      const data = await del<any>(`${API_BASE}/${encodeURIComponent(filename)}`)
      if (data?.status && data?.data?.has_refs) {
        setDeleteTarget({ filename: data.data.file_name, refs: data.data.refs })
      } else if (data?.status) {
        message.success(`已删除 ${data.data.deleted}`)
        fetchFiles()
      }
    } catch {
      message.error('删除失败')
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    try {
      await post(`${API_BASE}/${encodeURIComponent(deleteTarget.filename)}/delete-confirm`, {})
      message.success(`已删除 ${deleteTarget.filename}`)
      setDeleteTarget(null)
      fetchFiles()
    } catch {
      message.error('删除失败')
    }
  }

  const handleBatchDelete = async () => {
    if (selectedKeys.length === 0) {
      message.warning('请先选择要删除的文件')
      return
    }
    try {
      const data = await post<any>(`${API_BASE}/batch-delete`, { filenames: selectedKeys as string[] })
      if (data?.status) {
        const results = data.data.results || []
        const deletedCount = results.filter((r: any) => r.deleted).length
        const pendingCount = results.filter((r: any) => r.has_refs).length
        if (pendingCount > 0) {
          setBatchResult(data.data)
        } else {
          message.success(`成功删除 ${deletedCount} 个文件`)
          setSelectedKeys([])
          fetchFiles()
        }
      }
    } catch {
      message.error('批量删除失败')
    }
  }

  const confirmBatchDelete = async () => {
    if (!batchResult) return
    const allNames = batchResult.results.map((r: any) => r.file_name)
    try {
      const data = await post<any>(`${API_BASE}/batch-delete-confirm`, { filenames: allNames })
      if (data?.status) {
        message.success(`成功删除 ${data.data.deleted.length} 个文件`)
        setBatchResult(null)
        setSelectedKeys([])
        fetchFiles()
      }
    } catch {
      message.error('批量删除失败')
    }
  }

  const columns: ColumnsType<TargetFile> = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', width: 200, ellipsis: true, sorter: (a, b) => a.file_name.localeCompare(b.file_name),
      render: (name: string) => <Space><FileTextOutlined style={{ color: '#a0aae0' }} /><span>{name}</span></Space> },
    { title: '大小', dataIndex: 'size_display', key: 'size', width: 100, sorter: (a, b) => a.size - b.size },
    { title: '行数', dataIndex: 'lines', key: 'lines', width: 80, sorter: (a, b) => a.lines - b.lines,
      render: (n: number) => <Tag>{n.toLocaleString()}</Tag> },
    { title: '上传时间', dataIndex: 'mtime', key: 'mtime', width: 160, sorter: (a, b) => a.mtime.localeCompare(b.mtime), defaultSortOrder: 'descend' },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: any, record: TargetFile) => (
        <Space size="small">
          <Tooltip title="下载">
            <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(record.file_name)}>下载</Button>
          </Tooltip>
          {canWrite && <Popconfirm
            title={`确定删除 ${record.file_name}？`}
            onConfirm={() => handleDeleteSingle(record.file_name)}
            okText="确定" cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 20 }}>
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>文件管理</span>
            <Tag>{files.length} 个文件</Tag>
          </Space>
        }
        extra={
          <Space>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索文件名..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 200 }}
              allowClear
            />
            {canWrite && <Upload customRequest={handleUpload} showUploadList={false} accept=".txt">
              <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
                上传文件
              </Button>
            </Upload>}
            <Button icon={<ReloadOutlined />} onClick={fetchFiles}>刷新</Button>
            {canWrite && selectedKeys.length > 0 && (
              <Popconfirm
                title={`确定删除选中的 ${selectedKeys.length} 个文件？`}
                onConfirm={handleBatchDelete}
                okText="确定" cancelText="取消"
              >
                <Button danger icon={<DeleteOutlined />}>
                  删除选中 ({selectedKeys.length})
                </Button>
              </Popconfirm>
            )}
          </Space>
        }
        styles={{ body: { padding: 0 } }}
      >
        <div style={{ padding: '8px 16px', fontSize: 12, color: '#8b949e' }}>
          支持上传 .txt 文本文件（每行一个目标，最大 30MB），文件将出现在任务表单的"历史上传文件"选择器中
        </div>
        <Table
          columns={columns}
          dataSource={filtered}
          rowKey="file_name"
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 个文件` }}
          rowSelection={canWrite ? {
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys),
          } : undefined}
          size="middle"
        />
      </Card>

      {/* 单个删除引用警告弹窗 */}
      <Modal
        title="删除确认"
        open={!!deleteTarget}
        onOk={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
        okText="确定删除" cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        {deleteTarget && (
          <div>
            <p>文件 <strong>{deleteTarget.filename}</strong> 被以下任务引用：</p>
            <ul>
              {deleteTarget.refs.map((r, i) => (
                <li key={i}>{r.model === 'auto_scan' ? '自动扫描任务' : '批量任务'} ID: {r.task_id}</li>
              ))}
            </ul>
            <p style={{ color: '#e74c3c', marginTop: 12 }}>
              删除后这些任务的"历史文件"选中将自动清除，任务再跑时需重新选择文件。
            </p>
          </div>
        )}
      </Modal>

      {/* 批量删除引用警告弹窗 */}
      <Modal
        title="批量删除确认"
        open={!!batchResult}
        onOk={confirmBatchDelete}
        onCancel={() => setBatchResult(null)}
        okText="确定全部删除" cancelText="取消"
        okButtonProps={{ danger: true }}
        width={500}
      >
        {batchResult && (
          <div>
            {batchResult.results.filter((r: any) => r.deleted).length > 0 && (
              <p>已自动删除 {batchResult.results.filter((r: any) => r.deleted).length} 个无引用的文件。</p>
            )}
            <p style={{ color: '#e74c3c', marginTop: 8 }}>
              以下文件被任务引用，确认后将一并删除并清除引用：
            </p>
            <ul>
              {batchResult.results.filter((r: any) => r.has_refs).map((r: any, i: number) => (
                <li key={i}>
                  <strong>{r.file_name}</strong> — 被 {r.refs?.length || 0} 个任务引用
                </li>
              ))}
            </ul>
          </div>
        )}
      </Modal>
    </div>
  )
}
