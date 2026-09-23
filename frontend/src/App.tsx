import { useEffect, useState } from 'react'
import { AppShell } from './components/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { MapPage } from './pages/MapPage'

function currentPage(): 'dashboard' | 'map' {
  return window.location.hash === '#/mapa' ? 'map' : 'dashboard'
}

export default function App() {
  const [page, setPage] = useState(currentPage)
  useEffect(() => {
    const onHashChange = () => setPage(currentPage())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  return <AppShell page={page}>{page === 'map' ? <MapPage /> : <DashboardPage />}</AppShell>
}
