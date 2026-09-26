import { useEffect, useState, type FormEvent } from 'react'
import { DashboardOverview } from '../components/dashboard/DashboardOverview'
import { getAssets, getOverviewSummary, getTypes, getZones } from '../services/dashboard'
import type { AssetFilters, AssetPage, AssetStatus, EquipmentItem, FilterOption, OverviewSummary } from '../types/dashboard'

export function DashboardPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [draft, setDraft] = useState({ q: '', epc: '' })
  const [filters, setFilters] = useState<AssetFilters>({ page: 1, page_size: 20 })
  const [data, setData] = useState<AssetPage | null>(null)
  const [types, setTypes] = useState<FilterOption[]>([])
  const [zones, setZones] = useState<FilterOption[]>([])
  const [summary, setSummary] = useState<OverviewSummary | null>(null)
  const [filterError, setFilterError] = useState(false)
  const [phase, setPhase] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('Não foi possível carregar os equipamentos.')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([getTypes(controller.signal), getZones(controller.signal)]).then(([t, z]) => {
      setTypes(t); setZones(z); setFilterError(false)
    }).catch((error) => { if (error.name !== 'AbortError') setFilterError(true) })
    getOverviewSummary(controller.signal).then(setSummary).catch(() => setSummary(null))
    return () => controller.abort()
  }, [retry])
  useEffect(() => {
    const controller = new AbortController()
    setPhase('loading')
    getAssets(filters, controller.signal).then((result) => { setData(result); setPhase('loaded') })
      .catch((error) => { if (error.name !== 'AbortError') {
        setErrorMessage(String(error.message).includes('422') ? 'Confira o EPC e os filtros informados.' : 'Não foi possível carregar os equipamentos.')
        setPhase('error')
      } })
    return () => controller.abort()
  }, [filters, retry])
  function submit(event: FormEvent) {
    event.preventDefault()
    setFilters((old) => ({ ...old, q: draft.q.trim() || undefined, epc: draft.epc.trim() || undefined, page: 1 }))
  }
  return <>
    <div className="page-heading"><div><p className="eyebrow">PAINEL OPERACIONAL / HUPAA</p><h1>Visão geral dos equipamentos</h1><p className="lead">Consulte a última zona detectada. A localização é aproximada.</p></div></div>
    <form className="panel asset-filters" role="search" onSubmit={submit}>
      <label>Nome ou patrimônio<input type="search" maxLength={120} value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })}/></label>
      <label>EPC<input type="search" maxLength={32} value={draft.epc} onChange={(e) => setDraft({ ...draft, epc: e.target.value })} placeholder="EPC exato"/></label>
      <label>Tipo<select value={filters.tipo ?? ''} onChange={(e) => setFilters({ ...filters, tipo: e.target.value ? Number(e.target.value) : undefined, page: 1 })}><option value="">Todos</option>{types.map((type) => <option key={type.id} value={type.id}>{type.nome}</option>)}</select></label>
      <label>Status<select value={filters.status ?? ''} onChange={(e) => setFilters({ ...filters, status: (e.target.value || undefined) as AssetStatus | undefined, page: 1 })}><option value="">Todos</option><option value="disponivel">Disponível</option><option value="atencao">Atenção necessária</option><option value="fora_de_servico">Fora de serviço</option><option value="nunca_detectado">Nunca detectado</option></select></label>
      <label>Zona<select value={filters.zona ?? ''} onChange={(e) => setFilters({ ...filters, zona: e.target.value ? Number(e.target.value) : undefined, page: 1 })}><option value="">Todas</option>{zones.map((zone) => <option key={zone.id} value={zone.id}>{zone.nome}</option>)}</select></label>
      <button type="submit">Buscar</button>
    </form>
    {filterError && <p role="alert">Não foi possível carregar as opções de tipo e zona. Tente novamente.</p>}
    {phase === 'loading' && <div className="panel table-skeleton" role="status" aria-label="Carregando equipamentos"><span/><span/><span/></div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>{errorMessage}</h2><button type="button" onClick={() => setRetry((value) => value + 1)}>Tentar novamente</button></div>}
    {phase === 'loaded' && data && <DashboardOverview data={data} summary={summary} onSelect={onSelect} onPage={(page) => setFilters({ ...filters, page })}/>}
  </>
}
