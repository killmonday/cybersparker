import React, { useState, useEffect } from 'react'
import { get } from '../api'
import type { DashboardData } from '../types/result'

// Runtime data shape: top_exp is Array<[string, number]>, exp_types items have .name not .type_str
type RuntimeDashboardData = Omit<DashboardData, 'top_exp' | 'exp_types'> & {
  top_exp: Array<[string, number]>
  exp_types: Array<{ name: string; count: number }>
}

export default function DashboardPage({ apiUrl }: { apiUrl: string }) {
  const [data, setData] = useState<RuntimeDashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    get<RuntimeDashboardData>(apiUrl).then(setData)
      .finally(() => setLoading(false))
  }, [apiUrl])

  if (loading) return (
    <div className="react-shell-page">
      <div className="react-section">
        <div className="react-shell-panel"><span>加载中...</span></div>
      </div>
    </div>
  )

  const maxExp = data?.top_exp?.length ? Math.max(...data.top_exp.map(([, c]) => c), 1) : 1
  const maxType = data?.exp_types?.length ? Math.max(...data.exp_types.map((t) => t.count), 1) : 1

  return (
    <div className="react-shell-page">
      <div className="react-list-header" style={{ marginBottom: 16 }}>
        <div>
          <h2>仪表盘</h2>
        </div>
              </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {data?.cards.map((card) => (
          <div key={card.name} className="react-section" style={{ textAlign: 'center', padding: 24 }}>
            <div style={{ fontSize: 32, fontWeight: 700, color: 'var(--text)' }}>{card.count.toLocaleString()}</div>
            <div style={{ color: 'var(--text-dim)', marginTop: 4 }}>{card.name}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="react-section" style={{ padding: 20 }}>
          <h3 style={{ margin: '0 0 16px' }}>插件结果 TOP15</h3>
          {data?.top_exp?.map(([name, count]) => (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <div
                style={{ width: 200, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}
                title={name}
              >
                {name}
              </div>
              <div style={{ flex: 1, background: 'var(--bg-elevated)', borderRadius: 4, height: 18, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${(count / maxExp) * 100}%`,
                    height: '100%',
                    background: 'linear-gradient(135deg, var(--brand), var(--info))',
                    borderRadius: 4,
                    minWidth: 2,
                  }}
                />
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, width: 50, textAlign: 'right' }}>{count}</div>
            </div>
          ))}
        </div>

        <div className="react-section" style={{ padding: 20 }}>
          <h3 style={{ margin: '0 0 16px' }}>插件类型分布</h3>
          {data?.exp_types?.map((t) => (
            <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <div
                style={{ width: 160, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}
                title={t.name}
              >
                {t.name}
              </div>
              <div style={{ flex: 1, background: 'var(--bg-elevated)', borderRadius: 4, height: 18, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${(t.count / maxType) * 100}%`,
                    height: '100%',
                    background: 'linear-gradient(135deg, var(--warning), var(--danger))',
                    borderRadius: 4,
                    minWidth: 2,
                  }}
                />
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, width: 40, textAlign: 'right' }}>{t.count}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
