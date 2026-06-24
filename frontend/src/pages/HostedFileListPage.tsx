import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Table, Modal, Space, Upload, message, Input, Tag, Tooltip, Card, Popconfirm, Switch, Select,
} from 'antd'
import TextArea from 'antd/es/input/TextArea'
import {
  UploadOutlined, DownloadOutlined, DeleteOutlined, FileOutlined,
  SearchOutlined, ReloadOutlined, EditOutlined, CopyOutlined, FormOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import { get, post, put, postForm, del } from '../api'
import { copyToClipboard } from '../utils'
import { useAuth } from '../contexts/AuthContext'

const API_BASE = '/api/v1/hosted-files'
const DOWNLOAD_BASE = '/files'

interface HostedFile {
  id: number
  original_name: string
  stored_name: string
  file_size: number
  is_public: boolean
  note: string
  created_at: string
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const size = (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)
  return `${size} ${units[i]}`
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function HostedFileListPage() {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const [files, setFiles] = useState<HostedFile[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadPublic, setUploadPublic] = useState(true)
  const [renameTarget, setRenameTarget] = useState<HostedFile | null>(null)
  const [renameInput, setRenameInput] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [noteTarget, setNoteTarget] = useState<HostedFile | null>(null)
  const [noteInput, setNoteInput] = useState('')
  const [noteSaving, setNoteSaving] = useState(false)

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
    return files.filter(f => f.original_name.toLowerCase().includes(kw))
  }, [files, search])

  const handleUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onSuccess, onError } = options as any
    const f = file as File
    if (f.size > 200 * 1024 * 1024) {
      message.error('文件大小不能超过 200MB')
      onError?.(new Error('too large'))
      return
    }
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', f)
      form.append('is_public', String(uploadPublic))
      const data: any = await postForm(`${API_BASE}/upload`, form)
      if (data?.status) {
        message.success('上传成功')
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

  const handleDownload = (record: HostedFile) => {
    window.open(`${DOWNLOAD_BASE}/${record.id}/${encodeURIComponent(record.original_name)}`, '_blank')
  }

  const handleCopyLink = (record: HostedFile) => {
    const url = `${window.location.origin}${DOWNLOAD_BASE}/${record.id}/${encodeURIComponent(record.original_name)}`
    copyToClipboard(url).then((ok) => {
      if (ok) message.success('下载链接已复制')
      else message.error('复制失败')
    })
  }

  const handleDelete = async (record: HostedFile) => {
    try {
      const data = await del<any>(`${API_BASE}/${record.id}`)
      if (data?.status) {
        message.success('已删除')
        fetchFiles()
      } else {
        message.error(data?.data?.error || '删除失败')
      }
    } catch {
      message.error('删除失败')
    }
  }

  const handleRename = async () => {
    if (!renameTarget || !renameInput.trim()) return
    setRenaming(true)
    try {
      const data = await put<any>(`${API_BASE}/${renameTarget.id}/rename`, { new_name: renameInput.trim() })
      if (data?.status) {
        message.success('重命名成功')
        setRenameTarget(null)
        fetchFiles()
      } else {
        message.error(data?.data?.error || '重命名失败')
      }
    } catch {
      message.error('重命名失败')
    } finally {
      setRenaming(false)
    }
  }

  const handleToggleAccess = async (record: HostedFile) => {
    try {
      const data = await put<any>(`${API_BASE}/${record.id}/access`, { is_public: !record.is_public })
      if (data?.status) {
        message.success(record.is_public ? '已设为需登录' : '已设为公开')
        fetchFiles()
      } else {
        message.error(data?.data?.error || '修改失败')
      }
    } catch {
      message.error('修改失败')
    }
  }

  const handleSaveNote = async () => {
    if (!noteTarget) return
    setNoteSaving(true)
    try {
      const data = await put<any>(`${API_BASE}/${noteTarget.id}/note`, { note: noteInput })
      if (data?.status) {
        message.success('备注已保存')
        setNoteTarget(null)
        fetchFiles()
      } else {
        message.error(data?.data?.error || '保存失败')
      }
    } catch {
      message.error('保存失败')
    } finally {
      setNoteSaving(false)
    }
  }

  const columns: ColumnsType<HostedFile> = [
    { title: '文件名', dataIndex: 'original_name', key: 'name', width: 220, ellipsis: true,
      sorter: (a, b) => a.original_name.localeCompare(b.original_name),
      render: (name: string) => <Space><FileOutlined style={{ color: '#a0aae0' }} /><span>{name}</span></Space> },
    { title: '大小', dataIndex: 'file_size', key: 'size', width: 100,
      sorter: (a, b) => a.file_size - b.file_size,
      render: (size: number) => <Tag>{formatSize(size)}</Tag> },
    { title: '访问级别', dataIndex: 'is_public', key: 'access', width: 110,
      render: (pub: boolean, record: HostedFile) => (
        canWrite ? <Switch
          checked={pub}
          checkedChildren="公开"
          unCheckedChildren="需登录"
          onChange={() => handleToggleAccess(record)}
        /> : <Tag>{pub ? '公开' : '需登录'}</Tag>
      ) },
    { title: '备注', dataIndex: 'note', key: 'note', width: 160, ellipsis: true,
      render: (note: string) => (
        <span style={{ color: note ? undefined : '#8b949e' }}>{note || '-'}</span>
      ) },
    { title: '上传时间', dataIndex: 'created_at', key: 'time', width: 150,
      sorter: (a, b) => a.created_at.localeCompare(b.created_at),
      defaultSortOrder: 'descend',
      render: (t: string) => formatTime(t) },
    {
      title: '操作', key: 'actions', width: 320,
      render: (_: any, record: HostedFile) => (
        <Space size="small">
          <Tooltip title="下载">
            <Button type="link" size="small" icon={<DownloadOutlined />}
              onClick={() => handleDownload(record)}>下载</Button>
          </Tooltip>
          <Tooltip title="复制下载链接">
            <Button type="link" size="small" icon={<CopyOutlined />}
              onClick={() => handleCopyLink(record)}>复制链接</Button>
          </Tooltip>
          {canWrite && <Tooltip title="备注">
            <Button type="link" size="small" icon={<FormOutlined />}
              onClick={() => { setNoteTarget(record); setNoteInput(record.note || '') }}>备注</Button>
          </Tooltip>}
          {canWrite && <Tooltip title="重命名">
            <Button type="link" size="small" icon={<EditOutlined />}
              onClick={() => { setRenameTarget(record); setRenameInput(record.original_name) }}>重命名</Button>
          </Tooltip>}
          {canWrite && <Popconfirm
            title={`确定删除 ${record.original_name}？`}
            onConfirm={() => handleDelete(record)}
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
            <FileOutlined />
            <span>文件托管</span>
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
            {canWrite && <Select value={uploadPublic} onChange={setUploadPublic} style={{ width: 100 }}>
              <Select.Option value={true}>公开</Select.Option>
              <Select.Option value={false}>需登录</Select.Option>
            </Select>}
            {canWrite && <Upload customRequest={handleUpload} showUploadList={false}>
              <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
                上传文件
              </Button>
            </Upload>}
            <Button icon={<ReloadOutlined />} onClick={fetchFiles}>刷新</Button>
          </Space>
        }
        styles={{ body: { padding: 0 } }}
      >
        <div style={{ padding: '8px 16px', fontSize: 12, color: '#8b949e' }}>
          上传任意文件（≤200MB），公开文件可通过 <code>/files/文件名</code> 直接下载无需登录，鉴权文件需登录后下载
        </div>
        <Table
          columns={columns}
          dataSource={filtered}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 个文件` }}
          size="middle"
        />
      </Card>

      <Modal
        title="重命名文件"
        open={!!renameTarget}
        onOk={handleRename}
        onCancel={() => setRenameTarget(null)}
        okText="确定" cancelText="取消"
        confirmLoading={renaming}
      >
        {renameTarget && (
          <div>
            <p style={{ marginBottom: 8, color: '#8b949e' }}>
              原文件名：{renameTarget.original_name}
            </p>
            <Input
              value={renameInput}
              onChange={e => setRenameInput(e.target.value)}
              onPressEnter={handleRename}
              placeholder="输入新文件名（含后缀）"
            />
            <p style={{ marginTop: 8, fontSize: 12, color: '#e74c3c' }}>
              重命名后旧下载链接将失效
            </p>
          </div>
        )}
      </Modal>

      <Modal
        title="编辑备注"
        open={!!noteTarget}
        onOk={handleSaveNote}
        onCancel={() => setNoteTarget(null)}
        okText="保存" cancelText="取消"
        confirmLoading={noteSaving}
      >
        {noteTarget && (
          <div>
            <p style={{ marginBottom: 8, color: '#8b949e' }}>
              文件：{noteTarget.original_name}
            </p>
            <TextArea
              value={noteInput}
              onChange={e => setNoteInput(e.target.value)}
              placeholder="输入备注信息"
              rows={3}
              maxLength={500}
              showCount
            />
          </div>
        )}
      </Modal>
    </div>
  )
}
