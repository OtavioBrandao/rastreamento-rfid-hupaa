import { useEffect, useState, type FormEvent } from 'react'
import { DashboardOverview } from '../components/dashboard/DashboardOverview'
import { getAssets, getOverviewSummary, getRecentActivity, getTypes, getZones } from '../services/dashboard'
import type { ActivityItem, AssetFilters, AssetPage, AssetStatus, EquipmentItem, FilterOption, OverviewSummary } from '../types/dashboard'
import { detectionLabel } from '../components/DashboardParts'

export function DashboardPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [draft, setDraft] = useState({ q: '', epc: '' })
  const [filters, setFilters] = useState<AssetFilters>({ page: 1, page_size: 20 })
  const [data, setData] = useState<AssetPage | null>(null)
  const [types, setTypes] = useState<FilterOption[]>([])
  const [zones, setZones] = useState<FilterOption[]>([])
  const [summary, setSummary] = useState<OverviewSummary | null>(null)
  const [summaryPhase, setSummaryPhase] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [activity, setActivity] = useState<ActivityItem[] | null>(null)
  const [activityPhase, setActivityPhase] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [filterError, setFilterError] = useState(false)
  const [phase, setPhase] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('Não foi possível carregar os equipamentos.')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setTypes([]); setZones([]); setFilterError(false)
    setSummary(null); setSummaryPhase('loading')
    setActivity(null); setActivityPhase('loading')
    Promise.all([getTypes(controller.signal), getZones(controller.signal)]).then(([t, z]) => {
      if (!controller.signal.aborted) { setTypes(t); setZones(z) }
    }).catch(() => { if (!controller.signal.aborted) setFilterError(true) })
    getOverviewSummary(controller.signal).then((result) => {
      if (!controller.signal.aborted) { setSummary(result); setSummaryPhase('loaded') }
    }).catch(() => { if (!controller.signal.aborted) { setSummary(null); setSummaryPhase('error') } })
    getRecentActivity(controller.signal).then((result) => {
      if (!controller.signal.aborted) { setActivity(result); setActivityPhase('loaded') }
    }).catch(() => { if (!controller.signal.aborted) { setActivity(null); setActivityPhase('error') } })
    return () => controller.abort()
  }, [retry])
  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setPhase('loading')
    getAssets(filters, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setData(result); setPhase('loaded') }
    })
      .catch((error) => { if (!controller.signal.aborted) {
        setData(null)
        setErrorMessage(String(error.message).includes('422') ? 'Confira o EPC e os filtros informados.' : 'Não foi possível carregar os equipamentos.')
        setPhase('error')
      } })
    return () => controller.abort()
  }, [filters, retry])
  function changeFilters(next: AssetFilters) {
    setData(null)
    setPhase('loading')
    setFilters(next)
  }
  function retryAll() {
    setData(null); setPhase('loading')
    setSummary(null); setSummaryPhase('loading')
    setActivity(null); setActivityPhase('loading')
    setRetry((value) => value + 1)
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    changeFilters({ ...filters, q: draft.q.trim() || undefined, epc: draft.epc.trim() || undefined, page: 1 })
  }
  return <>
    <div className="page-heading"><div><p className="eyebrow">PAINEL OPERACIONAL / HUPAA</p><h1>Visão geral dos equipamentos</h1><p className="lead">Consulte a última zona detectada. A localização é aproximada.</p></div></div>
    <form className="panel asset-filters" role="search" onSubmit={submit}>
      <label>Nome ou patrimônio<input type="search" maxLength={120} value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })}/></label>
      <label>EPC<input type="search" maxLength={32} value={draft.epc} onChange={(e) => setDraft({ ...draft, epc: e.target.value })} placeholder="EPC exato"/></label>
      <label>Tipo<select value={filters.tipo ?? ''} onChange={(e) => changeFilters({ ...filters, tipo: e.target.value ? Number(e.target.value) : undefined, page: 1 })}><option value="">Todos</option>{types.map((type) => <option key={type.id} value={type.id}>{type.nome}</option>)}</select></label>
      <label>Status<select value={filters.status ?? ''} onChange={(e) => changeFilters({ ...filters, status: (e.target.value || undefined) as AssetStatus | undefined, page: 1 })}><option value="">Todos</option><option value="disponivel">Disponível</option><option value="atencao">Atenção necessária</option><option value="fora_de_servico">Fora de serviço</option><option value="nunca_detectado">Nunca detectado</option></select></label>
      <label>Zona<select value={filters.zona ?? ''} onChange={(e) => changeFilters({ ...filters, zona: e.target.value ? Number(e.target.value) : undefined, page: 1 })}><option value="">Todas</option>{zones.map((zone) => <option key={zone.id} value={zone.id}>{zone.nome}</option>)}</select></label>
      <button type="submit">Buscar</button>
    </form>
    {filterError && <p role="alert">Não foi possível carregar as opções de tipo e zona. <button type="button" onClick={retryAll}>Tentar novamente</button></p>}
    {summaryPhase === 'error' && <p role="alert">Não foi possível carregar os indicadores. <button type="button" onClick={retryAll}>Tentar novamente</button></p>}
    {phase === 'loading' && <div className="panel table-skeleton" role="status" aria-label="Carregando equipamentos"><span/><span/><span/></div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>{errorMessage}</h2><button type="button" onClick={retryAll}>Tentar novamente</button></div>}
    {phase === 'loaded' && data && <DashboardOverview data={data} summary={summary} onSelect={onSelect} onPage={(page) => changeFilters({ ...filters, page })}/>}
    <section className="panel activity-panel" aria-labelledby="activity-title">
      <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2 id="activity-title">Movimentações recentes</h2></div></div>
      {activityPhase === 'loading' && <p role="status">Carregando movimentações...</p>}
      {activityPhase === 'error' && <p role="alert">Não foi possível carregar as movimentações. <button type="button" onClick={retryAll}>Tentar novamente</button></p>}
      {activityPhase === 'loaded' && activity?.length === 0 && <p>Nenhuma movimentação registrada.</p>}
      {activityPhase === 'loaded' && activity && activity.length > 0 && <ol className="activity-list">{activity.map((movement) => <li key={movement.id}>
        <strong>{movement.equipamento_nome}</strong> · {movement.zona_origem ?? 'Origem não registrada'} → {movement.zona_destino}
        <small>{detectionLabel(movement.movimentada_em)}{movement.origem_registro === 'correcao_manual' ? ' · Correção manual' : ''}</small>
      </li>)}</ol>}
    </section>
  </>
}
