/**
 * Authentication context.
 *
 * Single source of truth for "who is signed in". Everything else (route guards,
 * the navbar, per-user API calls) reads from here. The token is persisted in
 * localStorage by the API layer; this provider only keeps the user object and
 * exposes login/register/logout.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authApi, getToken, setToken } from '../services'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(true)

  // Restore the session on first paint: a stored token is verified against the
  // API (so an expired token does not leave a half-signed-in UI).
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!getToken()) {
        setBooting(false)
        return
      }
      try {
        const { data } = await authApi.me()
        if (!cancelled) setUser(data)
      } catch {
        setToken(null)
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setBooting(false)
      }
    }
    restore()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (credentials) => {
    const { data } = await authApi.login(credentials)
    setToken(data.token)
    setUser(data.user)
    return data.user
  }, [])

  const register = useCallback(async (payload) => {
    const { data } = await authApi.register(payload)
    setToken(data.token)
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, booting, login, register, logout, isAuthenticated: Boolean(user) }),
    [user, booting, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}

export default AuthContext