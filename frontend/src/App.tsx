import { useEffect, useState } from 'react'
import { AppShell } from './components/AppShell'
import { EquipmentDrawer } from './components/equipamento/EquipmentDrawer'
import { DashboardPage } from './pages/DashboardPage'
import { MapPage } from './pages/MapPage'
import type { EquipmentItem } from './types/dashboard'
import { LiveProvider } from './services/live'

function currentPage(): 'dashboard' | 'map' {
  return window.location.hash === '#/mapa' ? 'map' : 'dashboard'
}

function Application() {
  const [page, setPage] = useState(currentPage)
  const [selected, setSelected] = useState<EquipmentItem | null>(null)
  useEffect(() => {
    const onHashChange = () => setPage(currentPage())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  return <AppShell page={page}>{page === 'map' ? <MapPage onSelect={setSelected} /> : <DashboardPage onSelect={setSelected} />}<EquipmentDrawer item={selected} onClose={() => setSelected(null)}/></AppShell>
}

export default function App() { return <LiveProvider><Application/></LiveProvider> }
