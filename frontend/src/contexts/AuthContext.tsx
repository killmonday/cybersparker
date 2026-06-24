import React, { createContext, useContext, useState, useEffect } from 'react'
import { Spin } from 'antd'

interface AuthState {
  authenticated: boolean
  username: string
  role: 'super_admin' | 'admin' | 'user'
}

const AuthContext = createContext<AuthState>({ authenticated: false, username: '', role: 'user' })

export const useAuth = () => useContext(AuthContext)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<AuthState>({ authenticated: false, username: '', role: 'user' })
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    fetch('/api/v1/auth/session', { credentials: 'same-origin' })
      .then(async (r) => {
        if (r.status === 200) {
          const data = await r.json()
          if (data.authenticated) {
            setState({
              authenticated: true,
              username: data.user?.username || '',
              role: data.user?.role || 'user',
            })
            return
          }
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

  if (!state.authenticated) {
    const next = window.location.pathname + window.location.search
    window.location.href = '/login?next=' + encodeURIComponent(next)
    return null
  }

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>
}
