import { useState, useMemo } from 'react'
import { Input, Checkbox, Button } from 'antd'

export interface HistoryFile {
  file_name: string
  mtime: string
  size: number
}

type SortKey = 'mtime' | 'name' | 'size'
type SortDir = 'asc' | 'desc'

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'mtime', label: '时间' },
  { key: 'name', label: '文件名' },
  { key: 'size', label: '大小' },
]

export default function HistoryFilePicker({
  files,
  selected,
  onSelectionChange,
  onRefresh,
}: {
  files: HistoryFile[]
  selected: string[]
  onSelectionChange: (v: string[]) => void
  onRefresh: () => void
}) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('mtime')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expanded, setExpanded] = useState(false)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    let list = q ? files.filter(f => f.file_name.toLowerCase().includes(q)) : [...files]

    list.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'mtime') cmp = a.mtime.localeCompare(b.mtime)
      else if (sortKey === 'name') cmp = a.file_name.localeCompare(b.file_name)
      else cmp = a.size - b.size
      return sortDir === 'desc' ? -cmp : cmp
    })
    return list
  }, [files, search, sortKey, sortDir])

  const allChecked = filtered.length > 0 && filtered.every(f => selected.includes(f.file_name))
  const anyChecked = filtered.some(f => selected.includes(f.file_name))

  function toggleAll() {
    if (allChecked) {
      const filteredNames = new Set(filtered.map(f => f.file_name))
      onSelectionChange(selected.filter(s => !filteredNames.has(s)))
    } else {
      const filteredNames = new Set(filtered.map(f => f.file_name))
      const rest = selected.filter(s => !filteredNames.has(s))
      onSelectionChange([...rest, ...filtered.map(f => f.file_name)])
    }
  }

  function toggleOne(name: string) {
    onSelectionChange(
      selected.includes(name)
        ? selected.filter(s => s !== name)
        : [...selected, name],
    )
  }

  function cycleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const maxH = expanded ? 'none' : 240

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>历史文件</span>
        <Button size="small" onClick={onRefresh}>刷新列表</Button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {filtered.length === files.length
            ? `共 ${files.length} 个`
            : `${filtered.length} / ${files.length} 个`}
        </span>
      </div>

      <Input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="搜索文件名..."
        style={{ marginBottom: 6 }}
        allowClear
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 6, flexWrap: 'wrap' }}>
        <Checkbox
          checked={allChecked}
          indeterminate={anyChecked && !allChecked}
          onChange={toggleAll}
        >
          全选
        </Checkbox>
        {SORT_OPTIONS.map(opt => (
          <Button
            key={opt.key}
            size="small"
            type={sortKey === opt.key ? 'primary' : 'default'}
            onClick={() => cycleSort(opt.key)}
            style={{ fontSize: 12 }}
          >
            {opt.label}{sortKey === opt.key ? (sortDir === 'desc' ? ' ↓' : ' ↑') : ''}
          </Button>
        ))}
      </div>

      <div
        style={{
          maxHeight: maxH,
          overflow: 'auto',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 6,
        }}
      >
        {filtered.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', padding: 16 }}>
            {search ? '无匹配文件' : '暂无历史上传文件'}
          </div>
        ) : (
          filtered.map(f => (
            <label
              key={f.file_name}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontSize: 13,
                padding: '4px 6px',
                borderRadius: 4,
                cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              <Checkbox
                checked={selected.includes(f.file_name)}
                onChange={() => toggleOne(f.file_name)}
              />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {f.file_name}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, flexShrink: 0 }}>
                {fmtSize(f.size)}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, flexShrink: 0, width: 130, textAlign: 'right' }}>
                {f.mtime}
              </span>
            </label>
          ))
        )}
      </div>

      {files.length > 10 && (
        <div style={{ textAlign: 'center', marginTop: 4 }}>
          <Button size="small" type="link" onClick={() => setExpanded(e => !e)}>
            {expanded ? '收起' : `展开全部（${files.length} 个）`}
          </Button>
        </div>
      )}
    </div>
  )
}
