import { useState, useMemo } from 'react'
import { Input, Checkbox, Button } from 'antd'

export interface HistoryEngineResult {
  target: string
  engine_type: string
  engine_query: string
  task_name: string
  creat_time: string
  target_count: number
}

type SortKey = 'time' | 'engine' | 'count'

function shortName(target: string): string {
  const parts = target.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || target
}

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'time', label: '时间' },
  { key: 'engine', label: '引擎' },
  { key: 'count', label: '目标数' },
]

export default function HistoryEngineResultPicker({
  results,
  selected,
  onSelectionChange,
  onRefresh,
}: {
  results: HistoryEngineResult[]
  selected: string[]
  onSelectionChange: (v: string[]) => void
  onRefresh: () => void
}) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('time')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [expanded, setExpanded] = useState(false)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    let list = q
      ? results.filter(r =>
          r.task_name.toLowerCase().includes(q) ||
          r.engine_query.toLowerCase().includes(q) ||
          r.engine_type.toLowerCase().includes(q) ||
          shortName(r.target).toLowerCase().includes(q),
        )
      : [...results]

    list.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'time') cmp = a.creat_time.localeCompare(b.creat_time)
      else if (sortKey === 'engine') cmp = a.engine_type.localeCompare(b.engine_type)
      else cmp = a.target_count - b.target_count
      return sortDir === 'desc' ? -cmp : cmp
    })
    return list
  }, [results, search, sortKey, sortDir])

  const allChecked = filtered.length > 0 && filtered.every(r => selected.includes(r.target))
  const anyChecked = filtered.some(r => selected.includes(r.target))

  function toggleAll() {
    if (allChecked) {
      const filteredTargets = new Set(filtered.map(r => r.target))
      onSelectionChange(selected.filter(s => !filteredTargets.has(s)))
    } else {
      const filteredTargets = new Set(filtered.map(r => r.target))
      const rest = selected.filter(s => !filteredTargets.has(s))
      onSelectionChange([...rest, ...filtered.map(r => r.target)])
    }
  }

  function toggleOne(target: string) {
    onSelectionChange(
      selected.includes(target)
        ? selected.filter(s => s !== target)
        : [...selected, target],
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
        <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>历史测绘结果</span>
        <Button size="small" onClick={onRefresh}>刷新列表</Button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {filtered.length === results.length
            ? `共 ${results.length} 个`
            : `${filtered.length} / ${results.length} 个`}
        </span>
      </div>

      <Input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="搜索任务名、查询语句、引擎..."
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
            {search ? '无匹配结果' : '暂无历史测绘结果'}
          </div>
        ) : (
          filtered.map(r => (
            <label
              key={r.target}
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
                checked={selected.includes(r.target)}
                onChange={() => toggleOne(r.target)}
              />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.task_name || shortName(r.target)}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, flexShrink: 0 }}>
                {r.engine_type}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, flexShrink: 0, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.engine_query}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, flexShrink: 0 }}>
                {r.target_count} 个目标
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 12, flexShrink: 0, width: 130, textAlign: 'right' }}>
                {r.creat_time}
              </span>
            </label>
          ))
        )}
      </div>

      {results.length > 10 && (
        <div style={{ textAlign: 'center', marginTop: 4 }}>
          <Button size="small" type="link" onClick={() => setExpanded(e => !e)}>
            {expanded ? '收起' : `展开全部（${results.length} 个）`}
          </Button>
        </div>
      )}
    </div>
  )
}
