import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Button, Tag, Alert, Select, Input, Space } from 'antd'
import { FilterOutlined } from '@ant-design/icons'
import { get, timeNoSec } from '../api'
import type { ColumnsType } from 'antd/es/table'

interface DirscanResultItem {
  id: number
  task_id: number
  ip: string
  port: number
  uri_path: string
  target: string
  status_code: number | null
  title: string
  products: string[]
  cert_org: string
  cert_org_unit: string
  cert_common_name: string
  cert_serial: string
  content_length: number | null
  header: string
  html: string
  creatime: string
}

interface DirscanResultsResponse {
  status: string
  results: DirscanResultItem[]
  total: number
  page: number
  total_pages: number
  rows_per_page: number
}

interface FilterOptions {
  status_codes: number[]
  uri_paths: string[]
  products: string[]
  titles: string[]
  cert_orgs: string[]
  cert_org_units: string[]
  cert_common_names: string[]
}

const STATUS_COLOR: Record<number, string> = {
  200: 'green', 301: 'blue', 302: 'blue', 304: 'blue',
  400: 'orange', 401: 'orange', 403: 'orange', 404: 'red', 500: 'red',
}

function productChips(products: string[]) {
  if (!products.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, maxWidth: 200 }}>
      {products.map(p => <Tag key={p} style={{ margin: 0 }}>{p}</Tag>)}
    </div>
  )
}

function openContent(title: string, content: string) {
  const w = window.open('', '_blank')
  if (!w) return
  w.document.title = title
  const s = w.document.createElement('style')
  s.textContent = 'body{background:#f5f3f0;margin:0;padding:20px 28px;font-family:"DM Sans",monospace}pre{background:#fafaf9;border:1px solid #e7e5e4;border-radius:6px;padding:20px 24px;overflow-x:auto;font-size:13px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#292524;margin:0}'
  w.document.head.appendChild(s)
  const pre = w.document.createElement('pre')
  pre.textContent = content
  w.document.body.appendChild(pre)
}

export default function DirscanResultsPage() {
  const params = new URLSearchParams(window.location.search)
  const host = params.get('host') ?? ''
  const port = params.get('port') ?? ''
  const protocol = params.get('protocol') ?? ''
  const taskId = params.get('task_id') ?? ''
  const byTask = !!taskId
  const label = byTask
    ? `任务 #${taskId}`
    : (host && port ? (protocol ? `${protocol}://${host}:${port}` : `${host}:${port}`) : '')
  const [data, setData] = useState<DirscanResultsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [rowsPerPage] = useState(15)

  // 筛选状态
  const [filters, setFilters] = useState<Record<string, string | null>>({})
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null)
  const [targetSearch, setTargetSearch] = useState('')
  const [contentLengthSort, setContentLengthSort] = useState<string | null>(null)
  const filtersLoadedRef = useRef(false)

  // 构建 API 的基础 query（不含分页和列筛选）
  const buildBaseQuery = useCallback((): string[] => {
    const parts: string[] = []
    if (byTask) {
      parts.push(`task_id=${encodeURIComponent(taskId)}`)
    } else {
      parts.push(`host=${encodeURIComponent(host)}`, `port=${port}`)
      if (protocol) parts.push(`protocol=${encodeURIComponent(protocol)}`)
    }
    return parts
  }, [byTask, taskId, host, port, protocol])

  // 加载下拉选项
  const loadFilterOptions = useCallback(async () => {
    if (!byTask && (!host || !port)) return
    const baseParts = buildBaseQuery()
    try {
      const result = await get<FilterOptions & { status: string }>(
        `/api/v1/assets/dirscan-results/filters?${baseParts.join('&')}`
      )
      if (result.status === 'ok') {
        setFilterOptions(result)
      }
    } catch {
      // 选项加载失败不影响列表
    }
  }, [buildBaseQuery, byTask, host, port])

  // 加载列表
  const load = useCallback(async () => {
    if (!byTask && (!host || !port)) return
    setLoading(true)
    setError('')
    try {
      const parts = buildBaseQuery()
      // 附加列筛选参数
      Object.entries(filters).forEach(([key, val]) => {
        if (val) {
          if (key === 'target_search') {
            parts.push(`target_search=${encodeURIComponent(val)}`)
          } else {
            parts.push(`${key}=${encodeURIComponent(val)}`)
          }
        }
      })
      if (contentLengthSort) parts.push(`sort=${contentLengthSort}`)
      parts.push(`page=${page}`, `rows_per_page=${rowsPerPage}`)
      const result = await get<DirscanResultsResponse>(
        `/api/v1/assets/dirscan-results?${parts.join('&')}`
      )
      if (result.status === 'ok') setData(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [byTask, host, port, buildBaseQuery, filters, page, rowsPerPage, contentLengthSort])

  useEffect(() => {
    if (!filtersLoadedRef.current) {
      filtersLoadedRef.current = true
      loadFilterOptions()
    }
    load()
  }, [load, loadFilterOptions])

  // 筛选变更 → 重置页码并重新加载
  function onFilterChange(key: string, val: string | null) {
    setPage(1)
    if (key === 'target_search') {
      setTargetSearch(val || '')
      setFilters(prev => {
        const next = { ...prev }
        if (val) { next.target_search = val } else { delete next.target_search }
        return next
      })
    } else {
      setFilters(prev => {
        const next = { ...prev }
        if (val) { next[key] = val } else { delete next[key] }
        return next
      })
    }
  }

  // 构建带筛选图标的列标题
  function filterTitle(label: string, field: string): React.ReactNode {
    const active = !!filters[field]
    return (
      <span>
        {label}
        <FilterOutlined style={{ marginLeft: 4, fontSize: 11, color: active ? '#1677ff' : '#bbb' }} />
      </span>
    )
  }

  // 构建下拉筛选 dropdown
  function selectFilterDropdown(
    field: string,
    options: (string | number)[] | undefined,
  ) {
    const items = (options || []).map(v => ({ label: String(v), value: String(v) }))
    return (
      <div style={{ padding: 8 }}>
        <Select
          allowClear
          showSearch
          placeholder="筛选…"
          style={{ width: 180 }}
          value={filters[field] || undefined}
          onChange={(v: string | undefined) => onFilterChange(field, v || null)}
          options={items}
          filterOption={(input, option) =>
            (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
          }
        />
      </div>
    )
  }

  // 目标模糊搜索 dropdown
  function targetFilterDropdown() {
    return (
      <div style={{ padding: 8 }}>
        <Input.Search
          placeholder="搜索目标…"
          allowClear
          value={targetSearch}
          onChange={e => setTargetSearch(e.target.value)}
          onSearch={v => onFilterChange('target_search', v || null)}
          style={{ width: 200 }}
        />
      </div>
    )
  }

  // 清除全部筛选
  function clearAllFilters() {
    setFilters({})
    setTargetSearch('')
    setPage(1)
  }

  if (!byTask && (!host || !port)) return <Alert type="error" message="缺少 host 或 port 参数" showIcon style={{ margin: 40 }} />
  if (loading && !data) return <div style={{ textAlign: 'center', padding: 80 }}>正在加载...</div>
  if (error) return <Alert type="error" message={`加载失败: ${error}`} showIcon style={{ margin: 40 }} />
  if (!data || (data.results.length === 0 && data.total === 0)) {
    const hasFilter = Object.keys(filters).length > 0
    if (hasFilter) {
      return (
        <div className="react-shell-page">
          <div className="react-shell-card react-list-card">
            <div className="react-list-header">
              <div><h2>目录扫描结果 — {label}</h2></div>
              <Button onClick={clearAllFilters}>清除筛选</Button>
            </div>
            <Table<DirscanResultItem> columns={makeColumns()} dataSource={[]} rowKey="id" size="small" pagination={false} />
            <div className="react-pagination-bar">
              <span>筛选结果为空</span>
            </div>
          </div>
        </div>
      )
    }
    return <Alert type="info" message={`未找到 ${label} 的目录扫描结果`} showIcon style={{ margin: 40 }} />
  }

  function makeColumns(): ColumnsType<DirscanResultItem> {
    return [
      { title: '端口', dataIndex: 'port', key: 'port', width: 70 },
      {
        title: filterTitle('URI路径', 'uri_path'), dataIndex: 'uri_path', key: 'uri_path', width: 200, ellipsis: true,
        filterDropdown: () => selectFilterDropdown('uri_path', filterOptions?.uri_paths),
        render: (v: string) => v || '—',
      },
      {
        title: filterTitle('目标', 'target_search'), dataIndex: 'target', key: 'target', width: 200, ellipsis: true,
        filterDropdown: targetFilterDropdown,
        render: (v: string) => v ? <a href={v} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>{v}</a> : '—',
      },
      {
        title: filterTitle('状态码', 'status_code'), dataIndex: 'status_code', key: 'status_code', width: 80,
        filterDropdown: () => selectFilterDropdown('status_code', filterOptions?.status_codes),
        render: (v: number | null) => v ? <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag> : '—',
      },
      {
        title: (
          <span
            style={{ cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setContentLengthSort(prev => {
              if (!prev) return 'content_length_desc'
              if (prev === 'content_length_desc') return 'content_length_asc'
              return null
            })}
          >
            页面长度
            <span style={{ marginLeft: 4, fontSize: 11, color: contentLengthSort ? '#1677ff' : '#bbb' }}>
              {contentLengthSort === 'content_length_desc' ? '↓' : contentLengthSort === 'content_length_asc' ? '↑' : '↕'}
            </span>
          </span>
        ),
        dataIndex: 'content_length', key: 'content_length', width: 100,
        render: (v: number | null) => {
          if (v == null) return '—'
          if (v < 1024) return `${v} B`
          if (v < 1048576) return `${(v / 1024).toFixed(1)} KB`
          return `${(v / 1048576).toFixed(1)} MB`
        },
      },
      {
        title: filterTitle('标题', 'title'), dataIndex: 'title', key: 'title', width: 180, ellipsis: true,
        filterDropdown: () => selectFilterDropdown('title', filterOptions?.titles),
        render: (v: string) => v || '—',
      },
      {
        title: filterTitle('产品', 'product'), dataIndex: 'products', key: 'products', width: 160,
        filterDropdown: () => selectFilterDropdown('product', filterOptions?.products),
        render: (v: string[]) => productChips(v) || '—',
      },
      {
        title: '响应头', dataIndex: 'header', key: 'header', width: 80,
        render: (v: string, r: DirscanResultItem) => v ? <Button size="small" onClick={() => openContent(`${r.ip}:${r.port}${r.uri_path} — 响应头`, v)}>查看</Button> : '—',
      },
      {
        title: '响应正文', dataIndex: 'html', key: 'html', width: 80,
        render: (v: string, r: DirscanResultItem) => v ? <Button size="small" onClick={() => openContent(`${r.ip}:${r.port}${r.uri_path} — 响应正文`, v)}>查看</Button> : '—',
      },
      {
        title: '创建时间', dataIndex: 'creatime', key: 'creatime', width: 130,
        render: (v: string) => timeNoSec(v) || '—',
      },
    ]
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>目录扫描结果 — {label}</h2>
          </div>
          {Object.keys(filters).length > 0 && <Button onClick={clearAllFilters}>清除筛选</Button>}
        </div>
        <Table<DirscanResultItem>
          columns={makeColumns()}
          dataSource={data.results}
          rowKey="id"
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={false}
          loading={loading}
        />
        <div className="react-pagination-bar">
          <span>第 {data.page} / {data.total_pages} 页，共 {data.total} 条</span>
          <div className="react-pagination-actions">
            <input type="number" min={1} max={data.total_pages} placeholder="页"
              style={{ width: 50, height: 34, borderRadius: 4, border: '1px solid #d6d3d1', textAlign: 'center' }}
              onKeyDown={e => {
                if (e.key !== 'Enter') return
                const n = parseInt((e.target as HTMLInputElement).value, 10)
                if (n && n >= 1 && n <= data.total_pages) setPage(n)
              }} />
            <Button onClick={() => {
              const inp = document.querySelector('.react-pagination-bar input[type="number"]') as HTMLInputElement
              if (inp) { const n = parseInt(inp.value, 10); if (n && n >= 1 && n <= data.total_pages) setPage(n) }
            }}>跳转</Button>
            <Button disabled={data.page <= 1} onClick={() => setPage(c => c - 1)}>上一页</Button>
            <Button disabled={data.page >= data.total_pages} onClick={() => setPage(c => c + 1)}>下一页</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
