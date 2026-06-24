import React, { useState, useEffect } from 'react'
import { Table, Tag, Spin, Alert, Button, Typography } from 'antd'
import { LinkOutlined } from '@ant-design/icons'
import { get } from '../api'
import type { IpDetailResponse, IpDetailAssetItem } from '../types/result'

const { Text, Title } = Typography

const STATUS_COLOR: Record<number, string> = { 200: 'green', 301: 'blue', 302: 'blue', 304: 'blue', 400: 'orange', 401: 'orange', 403: 'orange', 404: 'red', 405: 'red', 500: 'red', 502: 'red', 503: 'red' }

function statusTag(code: number | null) {
  if (code == null) return <Text type="secondary">—</Text>
  return <Tag color={STATUS_COLOR[code] ?? 'default'}>{code}</Tag>
}

function productChips(products: string[]) {
  if (!products.length) return <Text type="secondary">未识别</Text>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {products.map(p => (
        <Tag key={p} style={{ background: '#fff', border: '1px solid rgb(189, 217, 255)', color: 'rgb(81, 89, 99)' }}>{p}</Tag>
      ))}
    </div>
  )
}

export default function IpPortDetailPage() {
  const params = new URLSearchParams(window.location.search)
  const ip = params.get('ip') ?? ''
  const [data, setData] = useState<IpDetailAssetItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!ip) { setError('缺少 IP 参数'); setLoading(false); return }
    setLoading(true)
    get<IpDetailResponse>(`/api/v1/ip-detail?ip=${encodeURIComponent(ip)}`)
      .then((payload) => {
        if (payload.status !== 'ok') throw new Error('API 返回异常')
        setData(payload.assets)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [ip])

  if (!ip) return <Alert type="error" message="缺少 IP 参数" showIcon style={{ margin: 40 }} />
  if (loading) return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />
  if (error) return <Alert type="error" message={`加载失败: ${error}`} showIcon style={{ margin: 40 }} />
  if (!data || data.length === 0) return <Alert type="info" message={`未找到 IP ${ip} 的资产数据`} showIcon style={{ margin: 40 }} />

  const vulnColumns = [
    { title: '插件', dataIndex: 'plugin_name', key: 'plugin_name', width: 180 },
    { title: 'CVE', dataIndex: 'cve', key: 'cve', width: 160, render: (v: string) => v || '—' },
    { title: '产品', dataIndex: 'product', key: 'product', width: 120, render: (v: string) => v || '—' },
  ]

  const dirscanColumns = [
    { title: '路径', dataIndex: 'uri_path', key: 'uri_path', width: 200 },
    { title: '状态码', dataIndex: 'status_code', key: 'status_code', width: 80, render: (v: number | null) => statusTag(v) },
    { title: '标题', dataIndex: 'title', key: 'title', width: 160, ellipsis: true },
    { title: '产品', dataIndex: 'products', key: 'products', width: 120, render: (v: string[]) => productChips(v) },
  ]

  const columns = [
    { title: '协议', dataIndex: 'protocol', key: 'protocol', width: 70 },
    { title: '端口', dataIndex: 'port', key: 'port', width: 70 },
    { title: 'URL', dataIndex: 'target', key: 'target', width: 220, ellipsis: true,
      render: (v: string) => v ? <a href={v} target="_blank" rel="noopener noreferrer"><LinkOutlined /> {v}</a> : '—' },
    { title: '产品', dataIndex: 'products', key: 'products', width: 180, render: (v: string[]) => productChips(v) },
    { title: '标题', dataIndex: 'title', key: 'title', width: 200, ellipsis: true, render: (v: string) => v || '—' },
    { title: '状态码', dataIndex: 'status_code', key: 'status_code', width: 80, render: (v: number | null) => statusTag(v) },
    { title: '证书主体', dataIndex: 'cert_common_name', key: 'cert_common_name', width: 150, ellipsis: true, render: (v: string) => v || '—' },
    { title: '证书组织', dataIndex: 'cert_org', key: 'cert_org', width: 150, ellipsis: true, render: (v: string) => v || '—' },
    { title: '漏洞', key: 'vulns', width: 90,
      render: (_: unknown, row: IpDetailAssetItem) => {
        const n = row.related_vulns.length
        return n > 0 ? <Tag color="volcano">{n} 个</Tag> : <Tag>无</Tag>
      } },
    { title: '目录扫描', key: 'dirscan', width: 100,
      render: (_: unknown, row: IpDetailAssetItem) => {
        const n = row.dirscan_results.length
        return n > 0 ? <Tag color="geekblue">{n} 条</Tag> : <Tag>无</Tag>
      } },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>同 IP 端口详情</Title>
        <Tag color="blue">IP: {ip}</Tag>
        <Text type="secondary">共 {data.length} 个端口</Text>
      </div>

      <Table
        dataSource={data}
        columns={columns}
        rowKey="id"
        size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50', '100'], showTotal: (t: number) => `共 ${t} 条` }}
        expandable={{
          expandedRowRender: (row: IpDetailAssetItem) => (
            <div style={{ padding: '8px 0' }}>
              {row.related_vulns.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <Text strong>相关漏洞</Text>
                  <Table
                    dataSource={row.related_vulns}
                    columns={vulnColumns}
                    rowKey="id"
                    size="small"
                    pagination={false}
                    style={{ marginTop: 8 }}
                  />
                </div>
              )}
              {row.dirscan_results.length > 0 && (
                <div>
                  <Text strong>目录扫描结果</Text>
                  <Table
                    dataSource={row.dirscan_results}
                    columns={dirscanColumns}
                    rowKey="uri_path"
                    size="small"
                    pagination={false}
                    style={{ marginTop: 8 }}
                  />
                </div>
              )}
              {row.related_vulns.length === 0 && row.dirscan_results.length === 0 && (
                <Text type="secondary">无额外数据</Text>
              )}
            </div>
          ),
          rowExpandable: (row: IpDetailAssetItem) => row.related_vulns.length > 0 || row.dirscan_results.length > 0,
        }}
      />
    </div>
  )
}
