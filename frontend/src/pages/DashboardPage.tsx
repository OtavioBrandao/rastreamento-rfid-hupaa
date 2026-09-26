import { useCallback, useEffect, useState } from 'react'
import { DashboardOverview } from '../components/dashboard/DashboardOverview'
import { SearchBar } from '../components/SearchBar'
import { filterFixtureEquipment, getDashboard, type DemoState } from '../services/dashboard'
import type { DashboardData, EquipmentItem } from '../types/dashboard'

function demoStateFromUrl(): DemoState {
  const value = new URLSearchParams(window.location.search).get('estado')
  return value === 'erro' ? 'error' : value === 'vazio' ? 'empty' : 'loaded'
}

export function DashboardPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [phase, setPhase] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [query, setQuery] = useState('')
  const load = useCallback(() => {
    setData(null)
    setPhase('loading')
    getDashboard(demoStateFromUrl()).then((result) => {
      setData(result)
      setPhase('loaded')
    }).catch(() => {
      setData(null)
      setPhase('error')
    })
  }, [])
  useEffect(() => { load() }, [load])

  const items = data ? filterFixtureEquipment(data.equipment, query) : []
  return <>
    <div className="page-heading">
      <div><p className="eyebrow">PAINEL OPERACIONAL / HUPAA</p><h1>Visão geral dos equipamentos</h1><p className="lead">Consulte a última zona detectada e priorize os equipamentos que precisam de atenção.</p></div>
      <span className="demo-pill">Ambiente demonstrativo</span>
    </div>
    <section className="search-panel" aria-label="Busca de equipamentos"><SearchBar onSearch={setQuery} /><p>Busque pelo nome, número de patrimônio ou EPC.</p></section>
    {phase === 'loading' && <div className="state-panel" role="status"><span className="loading-dot" aria-hidden="true" />Carregando informações...</div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>Não foi possível carregar as informações.</h2><p>Tente novamente.</p><button type="button" onClick={load}>Tentar novamente</button></div>}
    {phase === 'loaded' && data && <DashboardOverview data={data} items={items} query={query} onSelect={onSelect} />}
  </>
}
