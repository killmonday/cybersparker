import React, { useState, useEffect } from 'react'
import { Spin } from 'antd'

export const AuthGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [checking, setChecking] = useState(true)
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    fetch('/api/v1/auth/session', { credentials: 'same-origin' })
      .then(async (r) => {
        if (r.status === 200) {
          const data = await r.json()
          if (data.authenticated) { setAuthed(true); return }
        }
      })
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [])

  if (checking) {
    return (
      <div style={{
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        height: '100vh', background: '#f6f8fb',
      }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!authed) {
    const next = window.location.pathname + window.location.search
    window.location.href = '/login?next=' + encodeURIComponent(next)
    return null
  }

  return <>{children}</>
}
