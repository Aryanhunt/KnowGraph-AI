/**
 * AppLayout — sidebar + topbar + content shell.
 *
 * Shell classes match the improve-UI prototype (.workspace-app /
 * .workspace-main). Owns global concerns (health polling) and nothing else;
 * each page fills the <Outlet />. Authenticated pages sit under this layout;
 * auth pages (login, register) render bare.
 */

import { useCallback } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { systemApi } from '../services'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import Sidebar from '../components/Sidebar'
import { useLoad } from '../hooks/useApi'

export default function AppLayout() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const loadHealth = useCallback(async () => {
    const { data } = await systemApi.health()
    return data
  }, [])

  const { data: health } = useLoad(loadHealth, [])

  return (
    <div className="workspace-app">
      <Sidebar user={user} />
      <div className="workspace-main">
        <Navbar health={health} onSearch={() => navigate('/search')} />
        <Outlet context={{ health }} />
      </div>
    </div>
  )
}
