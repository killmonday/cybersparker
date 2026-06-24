import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Input, Button, Select, Dropdown, Checkbox, Space, Tag, Spin } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { StreamLanguage } from '@codemirror/language'
import { yaml as yamlMode } from '@codemirror/legacy-modes/mode/yaml'
import { get, post, buildQuery } from '../api'
import { useAuth } from '../contexts/AuthContext'

type PluginOption2 = { id: number; title: string; CVE: string; label: string }

const PLUGIN_TYPE_CHOICES = [
  { v: 1, l: 'Command Execute' }, { v: 2, l: 'Code Execute' }, { v: 3, l: 'sql inject' },
  { v: 4, l: 'information leakage' }, { v: 5, l: 'File upload' }, { v: 6, l: 'File Reading' },
  { v: 7, l: 'Directory Traversal' }, { v: 8, l: 'Cross-site request forgery' },
  { v: 9, l: 'Identity bypass' }, { v: 10, l: 'weak password' }, { v: 11, l: 'Path leakage' },
  { v: 12, l: 'other' },
]
const EXT_CHOICES = ['verify', 'command', 'code', 'file', 'attack']

export default function ExpDebugPage({ apiUrl: _apiUrl }: { apiUrl: string }) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const [plugins, setPlugins] = useState<PluginOption2[]>([])
  const [pluginsLoading, setPluginsLoading] = useState(false)
  const [pluginsHasMore, setPluginsHasMore] = useState(true)
  const pluginsOffsetRef = useRef(0)
  const pluginsSearchRef = useRef('')
  const pluginSearchTimer = useRef<ReturnType<typeof setTimeout>>()
  const [pluginId, setPluginId] = useState('')
  const [pocContent, setPocContent] = useState('')
  const [pocLang, setPocLang] = useState(1)
  const [formCVE, setFormCVE] = useState('')
  const [formTitle, setFormTitle] = useState('')
  const [formType, setFormType] = useState(1)
  const [formTime, setFormTime] = useState('')
  const [extentions, setExtentions] = useState<string[]>([])
  const [target, setTarget] = useState('')
  const [execModel, setExecModel] = useState('verify')
  const [execCmd, setExecCmd] = useState('')
  const [taskArgs, setTaskArgs] = useState('')
  const [httpTimeout, setHttpTimeout] = useState('10')
  const [execResult, setExecResult] = useState('')
  const [execMatched, setExecMatched] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [message, setMessage] = useState('')
  const [availableModels, setAvailableModels] = useState<string[]>(['verify'])
  // 代理
  const [proxies, setProxies] = useState<{ id: number; proxy_address: string; proxy_port: number; proxy_type_label: string }[]>([])
  const [proxyId, setProxyId] = useState('0')
  // 关联指纹
  const [fingerprints, setFingerprints] = useState<{ id: number; product: string }[]>([])
  const [fpSearch, setFpSearch] = useState('')
  const [fpSearchResults, setFpSearchResults] = useState<{ id: number; product: string }[]>([])
  const [fpSearching, setFpSearching] = useState(false)
  const fpBlurTimer = useRef<ReturnType<typeof setTimeout>>()
  const fpTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    get<{ items: { id: number; proxy_address: string; proxy_port: number; proxy_type_label: string }[] }>('/api/v1/proxies')
      .then((p) => { setProxies(p.items || []) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const pid = new URLSearchParams(window.location.search).get('plugin_id')
    if (pid) selectPlugin(pid)
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  async function selectPlugin(id: string) {
    setPluginId(id)
    if (!id) return
    try {
      const p = await post<any>('/api/v1/exp-debug/info', { plugin_id: Number(id) })
      if (p.data) {
        const d = p.data
        const label = `[${d.CVE}] ${d.title}`
        setPlugins((prev) => {
          const without = prev.filter((x) => x.id !== Number(id))
          return [{ id: Number(id), title: d.title, CVE: d.CVE, label }, ...without]
        })
        setFormCVE(d.CVE); setFormTitle(d.title); setFormType(Number(d.Type) || 1); setPocLang(d.plugin_model || 1)
        setPocContent(d.content || ''); setFormTime(d.time || getToday())
        setExtentions((d.support_function || []).map(String))
        setAvailableModels((d.support_function || []).length ? d.support_function.map((s: number) => EXT_CHOICES[s - 1] || String(s)) : ['verify'])
        setExecModel((d.support_function || []).length ? (EXT_CHOICES[d.support_function[0] - 1] || 'verify') : 'verify')
        setFingerprints((d.fingerprints || []) as { id: number; product: string }[])
      }
    } catch {}
  }

  function getToday() {
    const d = new Date()
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
  }

  function clearForm() {
    setPluginId(''); setFormCVE(''); setFormTitle(''); setFormType(1); setPocContent('')
    setPocLang(1); setFormTime(getToday()); setExtentions([]); setAvailableModels(['verify'])
    setExecModel('verify'); setMessage('')
    setFingerprints([]); setFpSearch(''); setFpSearchResults([])
  }

  const doFpSearch = useCallback((keyword: string) => {
    if (!keyword.trim()) { setFpSearchResults([]); return }
    setFpSearching(true)
    const qs = buildQuery({ q: keyword })
    get<{ items: { id: number; product: string }[] }>(`/api/v1/fingerprints?${qs}`)
      .then((p) => { setFpSearchResults((p.items || []).filter((fp) => !fingerprints.some((f) => f.id === fp.id))) })
      .catch(() => { setFpSearchResults([]) })
      .finally(() => setFpSearching(false))
  }, [fingerprints])

  function handleFpSearchChange(v: string) {
    setFpSearch(v)
    if (fpTimerRef.current) clearTimeout(fpTimerRef.current)
    fpTimerRef.current = setTimeout(() => doFpSearch(v), 300)
  }

  function addFingerprint(fp: { id: number; product: string }) {
    if (fingerprints.some((f) => f.id === fp.id)) return
    setFingerprints((p) => [...p, fp])
    setFpSearchResults((p) => p.filter((r) => r.id !== fp.id))
  }

  function removeFingerprint(fpId: number) {
    setFingerprints((p) => p.filter((f) => f.id !== fpId))
  }

  async function handleSave() {
    setSaving(true); setMessage('')
    const body: Record<string, unknown> = {
      title_model: pluginId ? 'edit plugin' : 'add plugin',
      plugin_id: pluginId, CVE: formCVE, title: formTitle, Type: String(formType),
      ctime: formTime, poc_content: pocContent, plugin_language: String(pocLang),
      extentions: extentions.join(','),
      affected_product: fingerprints.map((f) => f.id).join(','),
    }
    try {
      const p = await post<any>('/api/v1/exp-debug/save', body)
      setSaving(false)
      setMessage('保存成功')
      if (!pluginId) {
        const newId = String(p.plugin_id || '')
        setPluginId(newId)
        reloadPlugins()
      }
      if (p.selected_label) reloadPlugins()
    } catch (e: any) {
      setSaving(false)
      setMessage(JSON.stringify(e?.message || '保存失败'))
    }
  }

  async function handleExecute() {
    setExecuting(true); setExecResult(''); setExecMatched(null)
    try {
      const p = await post<any>('/api/v1/exp-debug/execute', { target, plugin_id: Number(pluginId), model: execModel, cmd: execCmd, proxy_id: proxyId, task_args: taskArgs, http_timeout: httpTimeout })
      setExecMatched(!!p.matched)
      setExecResult(typeof p.result === 'string' ? p.result : JSON.stringify(p.result || p, null, 2))
    } catch (e: any) {
      setExecResult(JSON.stringify({ error: e?.message || '执行失败' }, null, 2))
    }
    setExecuting(false)
  }

  async function fetchPlugins(keyword: string, offset: number, append: boolean) {
    setPluginsLoading(true)
    try {
      const params = new URLSearchParams({ offset: String(offset), limit: '50' })
      if (keyword) params.set('q', keyword)
      const p = await get<any>(`/api/v1/exp-debug/plugins?${params}`)
      if (p.status) {
        if (append) {
          setPlugins((prev) => [...prev, ...p.data])
        } else {
          setPlugins(p.data)
        }
        setPluginsHasMore(p.has_more)
      }
    } catch {} finally { setPluginsLoading(false) }
  }

  function handlePluginDropdownOpen(open: boolean) {
    if (open && plugins.length === 0) {
      pluginsSearchRef.current = ''
      pluginsOffsetRef.current = 0
      setPluginsHasMore(true)
      fetchPlugins('', 0, false)
    }
  }

  function handlePluginSearch(keyword: string) {
    if (pluginSearchTimer.current) clearTimeout(pluginSearchTimer.current)
    pluginSearchTimer.current = setTimeout(() => {
      pluginsSearchRef.current = keyword
      pluginsOffsetRef.current = 0
      setPluginsHasMore(true)
      fetchPlugins(keyword, 0, false)
    }, 300)
  }

  function handlePluginPopupScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.target as HTMLDivElement
    if (pluginsLoading || !pluginsHasMore) return
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 10) {
      const nextOffset = pluginsOffsetRef.current + 50
      pluginsOffsetRef.current = nextOffset
      fetchPlugins(pluginsSearchRef.current, nextOffset, true)
    }
  }

  function reloadPlugins() {
    setPlugins([])
    setPluginsHasMore(true)
    pluginsOffsetRef.current = 0
    pluginsSearchRef.current = ''
  }

  const pocExts = pocLang === 2 ? [StreamLanguage.define(yamlMode)] : [python()]

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>插件调试</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button onClick={clearForm}>清空表单</Button>
                      </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '580px 1fr', gap: 16 }}>
          {/* Left: plugin selector + form */}
          <div>
            <div className="react-form-grid">
              <label style={{ gridColumn: 'span 2' }}>选择插件
                <Select
                  showSearch
                  value={pluginId || undefined}
                  onChange={(v) => selectPlugin(v ?? '')}
                  onDropdownVisibleChange={handlePluginDropdownOpen}
                  onSearch={handlePluginSearch}
                  onPopupScroll={handlePluginPopupScroll}
                  filterOption={false}
                  notFoundContent={pluginsLoading ? <Spin size="small" /> : '无匹配插件'}
                  placeholder="-- 选择插件 --"
                  style={{ width: '100%' }}
                  options={plugins.map((p) => ({ value: String(p.id), label: p.label }))}
                />
              </label>
              <label>CVE<Input value={formCVE} onChange={(e) => setFormCVE(e.target.value)} /></label>
              <label style={{ gridColumn: 'span 2' }}>标题<Input value={formTitle} onChange={(e) => setFormTitle(e.target.value)} /></label>
              <label>类型
                <Select value={formType} onChange={(v) => setFormType(v)} style={{ width: '100%' }}
                  options={PLUGIN_TYPE_CHOICES.map((c) => ({ value: c.v, label: c.l }))}
                />
              </label>
              <label>语言
                <Select value={pocLang} onChange={(v) => setPocLang(v)} style={{ width: '100%' }}
                  options={[{ value: 1, label: 'Python3' }, { value: 2, label: 'Nuclei YAML' }]}
                />
              </label>
              <label>日期<Input value={formTime} onChange={(e) => setFormTime(e.target.value)} /></label>
            </div>
            <div style={{ marginTop: 4 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13, color: 'var(--text-dim)' }}>支持方法</label>
              <Dropdown
                trigger={['click']}
                menu={{
                  items: EXT_CHOICES.map((fn, i) => ({
                    key: String(i + 1),
                    label: (
                      <Checkbox
                        checked={extentions.includes(String(i + 1))}
                        style={{ pointerEvents: 'none' }}
                      >
                        {fn}
                      </Checkbox>
                    ),
                    onClick: () => {
                      const idx = String(i + 1)
                      setExtentions((p) => p.includes(idx) ? p.filter((x) => x !== idx) : [...p, idx])
                    },
                  })),
                }}
              >
                <Button style={{ width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {extentions.length ? extentions.map((i) => EXT_CHOICES[Number(i) - 1]).join(', ') : '选择方法'}
                  </span>
                  <DownOutlined style={{ fontSize: 10, flexShrink: 0, marginLeft: 8 }} />
                </Button>
              </Dropdown>
            </div>
            {pluginId ? (
              <div style={{ marginTop: 12 }}>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 13, color: 'var(--text-dim)' }}>关联指纹</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                  {fingerprints.map((fp) => (
                    <Tag key={fp.id} closable onClose={() => removeFingerprint(fp.id)} color="blue">
                      {fp.product}
                    </Tag>
                  ))}
                  {!fingerprints.length && <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>暂无关联指纹</span>}
                </div>
                <Input
                  value={fpSearch}
                  onChange={(e) => handleFpSearchChange(e.target.value)}
                  onFocus={() => { clearTimeout(fpBlurTimer.current); if (fpSearch.trim()) handleFpSearchChange(fpSearch) }}
                  onBlur={() => { fpBlurTimer.current = setTimeout(() => setFpSearchResults([]), 150) }}
                  placeholder="搜索指纹产品名..."
                  style={{ marginBottom: 4 }}
                />
                {fpSearching ? (
                  <div style={{ padding: '8px 0', textAlign: 'center' }}><Spin size="small" /></div>
                ) : fpSearchResults.length > 0 ? (
                  <div style={{ border: '1px solid var(--border)', borderRadius: 6, maxHeight: 200, overflow: 'auto' }}>
                    {fpSearchResults.map((fp) => (
                      <div
                        key={fp.id}
                        onClick={() => addFingerprint(fp)}
                        style={{ padding: '6px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid var(--border)' }}
                        onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'var(--bg-elevated)' }}
                        onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'transparent' }}
                      >
                        {fp.product}
                      </div>
                    ))}
                  </div>
                ) : fpSearch.trim() ? (
                  <div style={{ padding: 8, fontSize: 12, color: 'var(--text-dim)' }}>无匹配结果</div>
                ) : null}
              </div>
            ) : null}
            {canWrite && <div style={{ marginTop: 12 }}>
              <Button type="primary" onClick={handleSave} loading={saving}>{saving ? '保存中...' : '保存插件'}</Button>
            </div>}
            {message ? (
              <div className={message === '保存成功' ? 'react-shell-panel' : 'react-error-box'} style={{ marginTop: 8, fontSize: 12 }}>
                {message}
              </div>
            ) : null}
          </div>

          {/* Right: Code editor + debug */}
          <div style={{ minWidth: 0 }}>
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', marginBottom: 12 }}>
              <CodeMirror
                value={pocContent}
                onChange={(s) => setPocContent(s)}
                extensions={pocExts}
                height="340px"
                theme="light"
                basicSetup={{ lineNumbers: true, foldGutter: true, autocompletion: false }}
              />
            </div>
            <div style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
                <Input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="目标URL" style={{ flex: '1 1 320px', minWidth: 200 }} />
                <Button type="primary" onClick={handleExecute} loading={executing} disabled={!pluginId || !canWrite}>
                  {executing ? '执行中...' : '执行'}
                </Button>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <Select value={execModel} onChange={(v) => setExecModel(v)} style={{ width: 130 }}
                  options={availableModels.map((m) => ({ value: m, label: m }))}
                />
                <Select value={proxyId} onChange={(v) => setProxyId(v ?? '0')} style={{ width: 190 }}
                  options={[
                    { value: '0', label: '代理：直连' },
                    ...proxies.map((p) => ({ value: String(p.id), label: `${p.proxy_address}:${p.proxy_port} (${p.proxy_type_label})` })),
                  ]}
                />
                <Input value={execCmd} onChange={(e) => setExecCmd(e.target.value)} placeholder="cmd参数(可选)" style={{ width: 270, flex: 1 }} />
                <Input addonBefore="HTTP超时" value={httpTimeout} onChange={(e) => setHttpTimeout(e.target.value)} placeholder="10" style={{ width: 150 }} />
              </div>
            </div>
            <div style={{ marginTop: 8 }}>
              <label style={{ display: 'block', fontSize: 13, color: 'var(--text-dim)', marginBottom: 4 }}>任务自定义参数 (JSON)</label>
              <Input.TextArea rows={2} value={taskArgs} onChange={(e) => setTaskArgs(e.target.value)} placeholder='JSON格式，如 {"callback":"http://x.com"}' />
            </div>
            {execResult ? (
              <div className={execMatched === true ? 'result-matched' : execMatched === false ? 'result-not-matched' : ''} style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
                <div style={{ padding: '6px 12px', background: 'var(--bg-elevated)', fontSize: 12, color: execMatched === true ? '#16a34a' : execMatched === false ? '#dc2626' : 'var(--text-dim)' }}>执行结果{execMatched === true ? ' ： 验证成功' : execMatched === false ? ' — 未命中' : ''}</div>
                <CodeMirror
                  value={execResult}
                  height="200px"
                  theme="light"
                  readOnly
                  basicSetup={{ lineNumbers: true, foldGutter: false, autocompletion: false }}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
