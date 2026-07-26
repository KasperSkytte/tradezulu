import { createContext, use, useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, api } from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (username: string, password: string, remember: boolean) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await api.get<User>('/auth/me'))
    } catch (error) {
      if (error instanceof ApiError && error.isAuthError) setUser(null)
      else throw error
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // A 401 from anywhere in the app means the session died; drop back to login.
  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('tz:unauthorized', onUnauthorized)
    return () => window.removeEventListener('tz:unauthorized', onUnauthorized)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login: async (username, password, remember) => {
        setUser(await api.post<User>('/auth/login', { username, password, remember }))
      },
      logout: async () => {
        await api.post('/auth/logout')
        setUser(null)
      },
      refresh,
    }),
    [user, loading, refresh],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthState {
  const context = use(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
