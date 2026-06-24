import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Input, Button, Modal, Form, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { get, post, put, del, timeNoSec } from '../api'
import type { ZoneItem, ZoneListResponse } from '../types/zone'
import { useAuth } from '../contexts/AuthContext'

const ZONE_API = '/api/v1/zones?counts=1'

interface ZoneFormState {
  id?: number
  code: string
  name: string
  description: string
}

export default function ZoneListPage() {
  const { role } = useAuth()
  const canWrite = role !== 'user'

  const [zones, setZones] = useState<ZoneItem[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [modalOpen, setModalOpen] = useState(false)
  const [renameModal, setRenameModal] = useState<{ open: boolean; id: number; name: string }>({ open: false, id: 0, name: '' })
  const mountedRef = useRef(false)

  const [form, setForm] = useState<ZoneFormState>({
    code: '',
    name: '',
    description: '',
  })

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await get<ZoneListResponse>(ZONE_API)
      if (mountedRef.current) {
        setZones(result.zones || [])
      }
    } catch {
      if (mountedRef.current) message.error('加载区域列表失败')
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const resetForm = useCallback(() => {
    setForm({ code: '', name: '', description: '' })
    setFormErrors({})
  }, [])

  const openCreate = () => {
    resetForm()
    setModalOpen(true)
  }

  const openRename = (zone: ZoneItem) => {
    setRenameModal({ open: true, id: zone.id, name: zone.name })
  }

  const submitCreate = async () => {
    setSubmitting(true)
    setFormErrors({})
    try {
      await post(`${ZONE_API}/create`, {
        code: form.code,
        name: form.name,
        description: form.description,
      })
      if (mountedRef.current) {
        message.success('创建成功')
        setModalOpen(false)
        resetForm()
        await load()
      }
    } catch (err: any) {
      if (mountedRef.current) {
        if (err?.errors) {
          setFormErrors(err.errors)
        } else {
          setFormErrors({ form: err?.message || '创建失败' })
        }
      }
    } finally {
      if (mountedRef.current) setSubmitting(false)
    }
  }

  const submitRename = async () => {
    setSubmitting(true)
    try {
      await put(`${ZONE_API}/${renameModal.id}/update`, { name: renameModal.name })
      if (mountedRef.current) {
        message.success('改名成功')
        setRenameModal({ open: false, id: 0, name: '' })
        await load()
      }
    } catch (err: any) {
      if (mountedRef.current) {
        message.error(err?.message || '改名失败')
      }
    } finally {
      if (mountedRef.current) setSubmitting(false)
    }
  }

  const handleDelete = (zone: ZoneItem) => {
    Modal.confirm({
      title: `确定删除区域"${zone.name}"？`,
      content: zone.asset_count > 0
        ? `该区域下有 ${zone.asset_count} 个资产，${zone.auto_scan_task_count} 个自动扫描任务，${zone.batch_task_count} 个批量任务，${zone.dirscan_task_count} 个目录扫描任务，${zone.directory_result_count} 个目录结果。删除可能受限制。`
        : '删除后无法恢复。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await del<{ status?: boolean; tips?: string; refs?: any[] }>(`${ZONE_API}/${zone.id}/delete`)
          if (mountedRef.current) {
            message.success('已删除')
            await load()
          }
        } catch (err: any) {
          if (mountedRef.current) {
            const refs = err?.refs || err?.data?.refs
            if (refs && refs.length > 0) {
              message.error(`无法删除：该区域被 ${refs.length} 处引用`)
            } else {
              message.error(err?.message || '删除失败')
            }
          }
        }
      },
    })
  }

  const columns: ColumnsType<ZoneItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '编码', dataIndex: 'code', key: 'code', width: 120 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
    {
      title: '备注', dataIndex: 'description', key: 'description', width: 160,
      render: (v: string) => v || '—', ellipsis: true,
    },
    { title: '资产数', dataIndex: 'asset_count', key: 'asset_count', width: 80 },
    { title: '自动扫描任务', dataIndex: 'auto_scan_task_count', key: 'auto_scan_task_count', width: 100 },
    { title: '批量任务', dataIndex: 'batch_task_count', key: 'batch_task_count', width: 80 },
    { title: '目录扫描任务', dataIndex: 'dirscan_task_count', key: 'dirscan_task_count', width: 100 },
    { title: '目录结果', dataIndex: 'directory_result_count', key: 'directory_result_count', width: 80 },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 140,
      render: (val: string) => timeNoSec(val) || '—', ellipsis: true,
    },
    {
      title: '操作', key: 'action', width: 140,
      render: (_: unknown, record: ZoneItem) => (
        canWrite ? (
          <>
            <Button type="link" size="small" onClick={() => openRename(record)}>改名</Button>
            {!record.is_system && (
              <Button type="link" size="small" danger onClick={() => handleDelete(record)}>删除</Button>
            )}
          </>
        ) : null
      ),
    },
  ]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>扫描区域</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canWrite && <Button type="primary" onClick={openCreate}>新增区域</Button>}
          </div>
        </div>

        <Modal
          title="新增区域"
          open={modalOpen}
          onOk={submitCreate}
          onCancel={() => { setModalOpen(false); resetForm() }}
          confirmLoading={submitting}
          okText="创建"
          cancelText="取消"
          width={480}
          destroyOnClose
        >
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="编码" help={formErrors.code ? <span className="react-error-text">{formErrors.code}</span> : undefined}>
              <Input
                value={form.code}
                onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
                placeholder="如 public, internal"
              />
            </Form.Item>
            <Form.Item label="名称" help={formErrors.name ? <span className="react-error-text">{formErrors.name}</span> : undefined}>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如 公网"
              />
            </Form.Item>
            <Form.Item label="备注">
              <Input
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="可选"
              />
            </Form.Item>
            {formErrors.form ? <div className="react-error-box" style={{ marginBottom: 8 }}>{formErrors.form}</div> : null}
          </Form>
        </Modal>

        <Modal
          title="修改区域名称"
          open={renameModal.open}
          onOk={submitRename}
          onCancel={() => setRenameModal({ open: false, id: 0, name: '' })}
          confirmLoading={submitting}
          okText="保存"
          cancelText="取消"
          width={400}
          destroyOnClose
        >
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="名称">
              <Input
                value={renameModal.name}
                onChange={(e) => setRenameModal((prev) => ({ ...prev, name: e.target.value }))}
              />
            </Form.Item>
          </Form>
        </Modal>

        {loading ? (
          <div className="react-shell-panel"><span>正在加载区域列表...</span></div>
        ) : (
          <div className="react-task-table-wrap">
            <Table<ZoneItem>
              columns={columns}
              dataSource={zones}
              rowKey="id"
              loading={loading}
              pagination={false}
              size="small"
            />
          </div>
        )}
      </div>
    </div>
  )
}
