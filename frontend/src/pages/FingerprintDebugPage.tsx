import React, { useState, useEffect } from 'react'
import { Input, Button, Select, Checkbox, Tag, Tabs, Modal, message } from 'antd'
import CodeMirror from '@uiw/react-codemirror'
import { get, post, ApiError } from '../api'
import { useAuth } from '../contexts/AuthContext'

type ProxyOption = { id: number; proxy: string }
type FingerprintOption = { id: number; product: string; condition: string }

type FingerprintMatchResult = {
  status: boolean
  error?: string
  response_headers?: string
  response_data?: string
  matched_text?: string
  matched_fingerprints?: Array<{ name: string; condition: string; matched_text: string }>
  favicon?: string | null
  favicon_md5?: string | null
  favicon_mmh3?: string | null
  cert_org?: string | null
  cert_org_unit?: string | null
  cert_common_name?: string | null
  cert_serial?: string | null
  uri_path?: string
  redirect_url?: string | null
  regular_error?: string
  redirect_status_code?: number
  redirect_response_headers?: string
  redirect_response_data?: string
  redirect_matched_text?: string
  redirect_matched_fingerprints?: Array<{ name: string; condition: string; matched_text: string }>
  redirect_regular_error?: string
  first_status_code?: number
  first_status?: boolean
  first_response_headers?: string
  first_response_data?: string
  first_matched_text?: string
  first_matched_fingerprints?: Array<{ name: string; condition: string; matched_text: string }>
  first_regular_error?: string
  redirect_status?: boolean
}

type PanelData = {
  status?: boolean
  response_headers?: string
  response_data?: string
  matched_text?: string
  matched_fingerprints?: Array<{ name: string; condition: string; matched_text: string }>
  regular_error?: string
  label: string
}

const FieldNames = ['title', 'body', 'header', 'cert', 'cert_org', 'cert_org_unit', 'cert_common_name', 'cert_serial', 'favicon', 'favicon_md5', 'favicon_mmh3', 'uri_path']

export default function FingerprintDebugPage({ apiUrl: _apiUrl }: { apiUrl: string }) {
  const { role } = useAuth(); const canWrite = role !== 'user';
  const [url, setUrl] = useState('')
  const [rule, setRule] = useState('')
  const [proxy, setProxy] = useState('')
  const [matchAll, setMatchAll] = useState(false)
  const [proxies, setProxies] = useState<ProxyOption[]>([])
  const [fingerprints, setFingerprints] = useState<FingerprintOption[]>([])
  const [fpTotal, setTotal] = useState(0)
  const [fpSearching, setFpSearching] = useState(false)
  const [selectedFpId, setSelectedFpId] = useState<number | null>(null)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<FingerprintMatchResult | null>(null)
  const [ruleError, setRuleError] = useState('')
  const [statusLabel, setStatusLabel] = useState('待发起')

  // ---- 保存为指纹 ----
  const [saveModal, setSaveModal] = useState(false)
  const [saveForm, setSaveForm] = useState({ product: '', condition: '' })
  const [saveFormErrors, setSaveFormErrors] = useState<Record<string, string>>({})
  const [saveSubmitting, setSaveSubmitting] = useState(false)

  function openSaveModal() {
    if (!validateRule(rule)) return
    setSaveForm({ product: '', condition: rule })
    setSaveFormErrors({})
    setSaveModal(true)
  }

  async function submitSave() {
    setSaveSubmitting(true)
    setSaveFormErrors({})
    try {
      await post('/api/v1/fingerprints/create', { product: saveForm.product, condition: saveForm.condition })
      message.success('创建成功')
      setSaveModal(false)
    } catch (err) {
      if (err instanceof ApiError && err.errors) {
        setSaveFormErrors(err.errors)
      } else {
        setSaveFormErrors({ form: err instanceof ApiError ? err.message : '保存失败' })
      }
    } finally {
      setSaveSubmitting(false)
    }
  }

  useEffect(() => {
    get<{ items?: Array<{ id: number; proxy_address: string; proxy_port: number; proxy_type_label: string }> }>('/api/v1/proxies')
      .then((p) => {
        if (p.items) {
          setProxies(p.items.map((i) => ({
            id: i.id,
            proxy: `${i.proxy_type_label}://${i.proxy_address}:${i.proxy_port}`,
          })))
        }
      })
      .catch(() => {})
    get<{ status: boolean; data: FingerprintOption[]; total: number }>('/api/v1/fingerprint-debug/fingerprints')
      .then((p) => { if (p.status) { setFingerprints(p.data); setTotal(p.total ?? p.data.length) } })
      .catch(() => {})
  }, [])

  function handleFingerprintSelect(id: number) {
    setSelectedFpId(id)
    const fp = fingerprints.find((f) => f.id === id)
    if (fp) {
      setRule(fp.condition)
      setRuleError('')
    }
  }

  function handleFpSearch(value: string) {
    setFpSearching(true)
    const url = value.trim()
      ? `/api/v1/fingerprint-debug/fingerprints?search=${encodeURIComponent(value.trim())}`
      : '/api/v1/fingerprint-debug/fingerprints'
    get<{ status: boolean; data: FingerprintOption[] }>(url)
      .then((p) => { if (p.status) setFingerprints(p.data) })
      .catch(() => {})
      .finally(() => setFpSearching(false))
  }

  function validateRule(r: string): boolean {
    if (!r.trim()) {
      setRuleError('请输入指纹规则')
      return false
    }
    const fpMatch = /(cert_common_name|cert_org_unit|cert_serial|cert_org|favicon_mmh3|favicon_md5|cert|favicon|uri_path|title|body|header)(=|~=|!=)/.test(r)
    if (!fpMatch) {
      setRuleError('格式错误。正确格式: title|body|header|cert|cert_org|cert_org_unit|cert_common_name|cert_serial|favicon|favicon_md5|favicon_mmh3|uri_path="xxx"')
      return false
    }
    setRuleError('')
    return true
  }

  async function runMate() {
    if (!validateRule(rule)) return
    setRunning(true); setResult(null)
    setStatusLabel('匹配中...')
    try {
      const p = await post<FingerprintMatchResult>('/api/v1/fingerprint-debug/mate', { url, regex: rule, proxy, match_all_fingerprints: matchAll })
      setResult(p)
      if (p.error) {
        setStatusLabel('请求失败')
      } else if (p.regular_error) {
        setStatusLabel('规则错误')
      } else if (p.status) {
        setStatusLabel('命中成功')
      } else {
        setStatusLabel('未命中')
      }
    } catch {
      setStatusLabel('请求失败')
    } finally {
      setRunning(false)
    }
  }

  function onRuleChange(v: string) { setRule(v); if (ruleError && v) validateRule(v) }

  const fpOptions = fingerprints.map((f) => ({
    value: f.id,
    label: `${f.product} — ${f.condition.length > 80 ? f.condition.slice(0, 80) + '...' : f.condition}`,
  }))

  function renderPanel(d: PanelData) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: '3fr 1fr', gap: 12, width: '100%' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ marginBottom: 8, fontWeight: 600 }}>匹配结果</div>
          <div className="react-section" style={{ marginBottom: 12 }}>
            {d.regular_error ? (
              <div>
                <strong style={{ color: 'var(--warning)' }}>无效的正则表达式</strong>
              </div>
            ) : d.status ? (
              <div>
                <strong style={{ color: 'var(--success)' }}>匹配成功</strong>
                {d.matched_text ? <div style={{ marginTop: 4, fontSize: 13 }}>命中: {d.matched_text}</div> : null}
              </div>
            ) : (
              <div>
                <strong style={{ color: 'var(--danger)' }}>匹配失败</strong>
                <div style={{ marginTop: 4, fontSize: 13, color: 'var(--text-dim)' }}>
                  {matchAll ? '当前规则未命中，可参考下方命中指纹继续调整。' : '目标可正常响应，但规则未命中。'}
                </div>
              </div>
            )}
          </div>
          <div style={{ marginBottom: 8, fontWeight: 600 }}>响应正文</div>
          <pre style={{
            margin: 0, padding: 12, maxHeight: 400, overflow: 'auto',
            fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-caption)',
            lineHeight: 1.7, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
            color: 'var(--text)', background: 'var(--bg-elevated)',
            borderRadius: 8, border: '1px solid var(--border)',
            marginBottom: 12,
          }}>
            {d.response_data ? d.response_data.slice(0, 8000) : '(无响应正文)'}
          </pre>
          {d.matched_fingerprints && d.matched_fingerprints.length > 0 ? (
            <div>
              <div style={{ marginBottom: 8, fontWeight: 600 }}>命中指纹 ({d.matched_fingerprints.length})</div>
              <div style={{ maxHeight: 240, overflow: 'auto' }}>
                {d.matched_fingerprints.map((f, i) => (
                  <div key={i} className="react-section" style={{ padding: '8px 12px', marginBottom: 4, fontSize: 13, cursor: 'pointer' }}
                    onClick={() => { setRule(f.condition); setRuleError(''); }}
                    title="点击回填此规则"
                  >
                    <strong>{f.name}</strong>
                    <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 2, fontFamily: 'var(--font-mono)' }}>{f.condition}</div>
                    {f.matched_text ? <div style={{ fontSize: 12, marginTop: 2, color: 'var(--success)' }}>命中: {f.matched_text}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ marginBottom: 8, fontWeight: 600 }}>响应头</div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', marginBottom: 12 }}>
            <CodeMirror
              value={d.response_headers || ''}
              height="160px"
              theme="light"
              readOnly
              basicSetup={{ lineNumbers: false, foldGutter: false, autocompletion: false }}
            />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="react-shell-page">
      <div className="react-shell-card react-list-card">
        <div className="react-list-header">
          <div>
            <h2>指纹调试</h2>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Tag color={statusLabel === '命中成功' ? 'green' : statusLabel === '未命中' || statusLabel === '请求失败' ? 'red' : statusLabel === '匹配中...' ? 'blue' : 'default'}>
              {statusLabel}
            </Tag>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{(fpTotal || fingerprints.length).toLocaleString()} 条指纹</span>
                      </div>
        </div>

        {/* Input Row */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="目标 URL" style={{ width: 260 }} onPressEnter={runMate} />
          <Select
            value={proxy || undefined}
            onChange={(v) => setProxy(v || '')}
            placeholder="不使用代理"
            allowClear
            style={{ minWidth: 180 }}
            options={proxies.map((p) => ({ value: p.proxy, label: p.proxy }))}
          />
          <Checkbox checked={matchAll} onChange={(e) => setMatchAll(e.target.checked)} style={{ whiteSpace: 'nowrap', lineHeight: '32px' }}>
            全库匹配
          </Checkbox>
          <Button type="primary" onClick={runMate} loading={running}>
            {running ? '匹配中...' : '匹配'}
          </Button>
          {canWrite && <Button onClick={openSaveModal}>保存</Button>}
        </div>

        {/* Fingerprint Picker */}
        <div className="react-section" style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 8, fontWeight: 600, fontSize: 'var(--fs-caption)', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            已有指纹筛选
            <small style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--text-muted)', fontWeight: 400, marginLeft: 8 }}>
              可检索产品名或条件片段，选中后自动回填到规则输入框
            </small>
          </div>
          <Select
              value={selectedFpId}
              onChange={(v) => handleFingerprintSelect(v)}
              placeholder={`请选择已有指纹 (共 ${fingerprints.length} 条) — 输入关键字搜索`}
              showSearch
              filterOption={false}
              onSearch={handleFpSearch}
              loading={fpSearching}
              options={fpOptions}
              style={{ width: '100%' }}
            />
        </div>

        {/* Rule Input */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 4, fontSize: 'var(--fs-caption)', color: 'var(--text-dim)' }}>
            指纹规则
            <small style={{ color: 'var(--text-muted)', marginLeft: 8 }}>支持 =（包含）、~=（正则）、!=（排除）</small>
          </div>
          <div style={{ marginBottom: 6, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            可用字段：{(FieldNames).join('、')}
          </div>
          <Input
            value={rule}
            onChange={(e) => onRuleChange(e.target.value)}
            placeholder='title="admin" || body~="nginx" || header="Server: nginx"'
            style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}
            onPressEnter={runMate}
          />
        </div>
        {ruleError ? <div className="react-error-box" style={{ marginBottom: 12 }}>{ruleError}</div> : null}

        {result ? (
          <>
            {(() => {
              const hasRedirect = !!result.first_response_headers || !!result.redirect_response_data

              if (hasRedirect) {
                const tab1Data: PanelData = result.first_response_headers ? {
                  status: result.first_status,
                  response_headers: result.first_response_headers,
                  response_data: result.first_response_data,
                  matched_text: result.first_matched_text,
                  matched_fingerprints: result.first_matched_fingerprints,
                  regular_error: result.first_regular_error,
                  label: '初次响应',
                } : {
                  status: result.status,
                  response_headers: result.response_headers,
                  response_data: result.response_data,
                  matched_text: result.matched_text,
                  matched_fingerprints: result.matched_fingerprints,
                  regular_error: result.regular_error,
                  label: '请求响应',
                }

                const tab1Label = result.first_response_headers
                  ? `初次响应${result.first_status_code ? ` (HTTP ${result.first_status_code})` : ''}`
                  : '请求响应'

                const tab2Data: PanelData = result.redirect_response_data ? {
                  status: result.redirect_status,
                  response_headers: result.redirect_response_headers,
                  response_data: result.redirect_response_data,
                  matched_text: result.redirect_matched_text,
                  matched_fingerprints: result.redirect_matched_fingerprints,
                  regular_error: result.redirect_regular_error,
                  label: 'JS跳转目标',
                } : {
                  status: result.status,
                  response_headers: result.response_headers,
                  response_data: result.response_data,
                  matched_text: result.matched_text,
                  matched_fingerprints: result.matched_fingerprints,
                  regular_error: result.regular_error,
                  label: '跳转目标',
                }

                const tab2Label = result.redirect_response_data ? 'JS跳转目标' : '跳转目标'

                return (
                  <>
                    <Tabs
                      items={[
                        { key: 'first', label: tab1Label, children: renderPanel(tab1Data) },
                        { key: 'final', label: tab2Label, children: renderPanel(tab2Data) },
                      ]}
                    />
                    <div style={{ marginTop: 12 }}>
                      <div style={{ marginBottom: 8, fontWeight: 600 }}>资产特征</div>
                      <div className="react-section" style={{ fontSize: 13 }}>
                        {(result.favicon || result.favicon_md5) ? (
                          <div style={{ marginBottom: 12 }}>
                            <strong>网站图标</strong><br />
                            {result.favicon ? <img src={result.favicon} style={{ width: 32, height: 32, margin: '6px 0', borderRadius: 4, border: '1px solid var(--border)' }} alt="" /> : null}
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, wordBreak: 'break-all' }}>{result.favicon_md5 || '-'}</div>
                            {result.favicon_mmh3 ? <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>mmh3: {result.favicon_mmh3}</div> : null}
                          </div>
                        ) : (
                          <div style={{ marginBottom: 12, color: 'var(--text-dim)' }}>无图标</div>
                        )}
                        {(result.cert_org || result.cert_common_name || result.cert_serial) ? (
                          <div style={{ marginBottom: 12 }}>
                            <strong>HTTPS 证书</strong>
                            <table style={{ fontSize: 12, marginTop: 6, borderCollapse: 'collapse' }}>
                              <tbody>
                                {result.cert_org ? <tr><td style={{ color: 'var(--text-dim)', paddingRight: 10 }}>组织</td><td style={{ fontFamily: 'var(--font-mono)' }}>{result.cert_org}</td></tr> : null}
                                {result.cert_org_unit ? <tr><td style={{ color: 'var(--text-dim)', paddingRight: 10 }}>部门</td><td style={{ fontFamily: 'var(--font-mono)' }}>{result.cert_org_unit}</td></tr> : null}
                                {result.cert_common_name ? <tr><td style={{ color: 'var(--text-dim)', paddingRight: 10 }}>CN</td><td style={{ fontFamily: 'var(--font-mono)' }}>{result.cert_common_name}</td></tr> : null}
                                {result.cert_serial ? <tr><td style={{ color: 'var(--text-dim)', paddingRight: 10 }}>序列号</td><td style={{ fontFamily: 'var(--font-mono)' }}>{result.cert_serial}</td></tr> : null}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <div style={{ marginBottom: 12, color: 'var(--text-dim)' }}>无证书（非HTTPS或获取失败）</div>
                        )}
                        <div>
                          <strong>URI路径</strong><br />
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{result.uri_path || '/'}</span>
                          {result.redirect_url ? <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>JS跳转: {result.redirect_url}</div> : null}
                        </div>
                      </div>
                    </div>
                  </>
                )
              }

              return renderPanel({
                status: result.status,
                response_headers: result.response_headers,
                response_data: result.response_data,
                matched_text: result.matched_text,
                matched_fingerprints: result.matched_fingerprints,
                regular_error: result.regular_error,
                label: '匹配结果',
              })
            })()}
          </>
        ) : (
          <div className="react-shell-panel"><span>输入目标 URL 和指纹规则，点击"匹配"开始。支持 Enter 快捷键。</span></div>
        )}

        <Modal
          title="保存指纹"
          open={saveModal}
          onCancel={() => setSaveModal(false)}
          footer={null}
          destroyOnClose
          width={720}
        >
          <div className="react-form-grid" style={{ marginTop: 8 }}>
            <label>
              产品
              <Input
                value={saveForm.product}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSaveForm((f) => ({ ...f, product: e.target.value }))}
                placeholder="例如：通达OA"
              />
              {saveFormErrors.product ? <span className="react-error-text">{saveFormErrors.product}</span> : null}
            </label>
            <label style={{ gridColumn: '1 / -1' }}>
              匹配条件
              <Input.TextArea
                value={saveForm.condition}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setSaveForm((f) => ({ ...f, condition: e.target.value }))}
                rows={4}
              />
              {saveFormErrors.condition ? <span className="react-error-text">{saveFormErrors.condition}</span> : null}
            </label>
          </div>
          {saveFormErrors.form ? <div className="react-error-box" style={{ marginTop: 12 }}>{saveFormErrors.form}</div> : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
            <Button onClick={() => setSaveModal(false)}>取消</Button>
            <Button type="primary" onClick={submitSave} loading={saveSubmitting}>
              {saveSubmitting ? '提交中...' : '保存'}
            </Button>
          </div>
        </Modal>
      </div>
    </div>
  )
}
