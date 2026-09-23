import { useCallback, useEffect, useState } from 'react'
import { RecentActivityList, SummaryGrid } from '../components/DashboardParts'
import { SearchBar } from '../components/SearchBar'
import { filterFixtureEquipment, getDashboard, type DemoState } from '../services/dashboard'
import type { DashboardData } from '../types/dashboard'

function demoStateFromUrl(): DemoState {
  const value = new URLSearchParams(window.location.search).get('estado')
  return value === 'erro' ? 'error' : value === 'vazio' ? 'empty' : 'loaded'
}

export function DashboardPage() {
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
      <div><p className="eyebrow">VISÃO GERAL</p><h1>Encontre equipamentos com rapidez.</h1><p className="lead">Consulte a última zona detectada e veja se a informação ainda pode ajudar na busca.</p></div>
      <span className="demo-pill">Ambiente demonstrativo</span>
    </div>
    <section className="search-panel" aria-label="Busca de equipamentos"><SearchBar onSearch={setQuery} /><p>Busque pelo nome, número de patrimônio ou EPC.</p></section>
    {phase === 'loading' && <div className="state-panel" role="status"><span className="loading-dot" aria-hidden="true" />Carregando informações...</div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>Não foi possível carregar as informações.</h2><p>Tente novamente.</p><button type="button" onClick={load}>Tentar novamente</button></div>}
    {phase === 'loaded' && data && <>
      <section className="summary-section" aria-labelledby="summary-title"><div className="section-heading"><div><p className="eyebrow">PANORAMA</p><h2 id="summary-title">Resumo dos equipamentos</h2></div><p>Dados de demonstração</p></div><SummaryGrid summary={data.summary} /></section>
      <section className="activity-section" aria-labelledby="activity-title"><div className="section-heading"><div><p className="eyebrow">CONSULTA RÁPIDA</p><h2 id="activity-title">Equipamentos e últimas detecções</h2></div><p>{query ? `${items.length} resultado${items.length === 1 ? '' : 's'}` : 'Exemplos recentes'}</p></div>
        {items.length ? <RecentActivityList items={items} /> : <div className="empty-panel"><h3>{query ? 'Nenhum equipamento encontrado' : 'Nenhum equipamento cadastrado'}</h3><p>{query ? 'Tente buscar por outro nome, patrimônio ou EPC.' : 'Os equipamentos aparecerão aqui quando houver dados disponíveis.'}</p></div>}
      </section>
    </>}
  </>
}
