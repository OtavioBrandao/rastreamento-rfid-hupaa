import { useState, type FormEvent } from 'react'
import { DashboardOverview } from '../components/dashboard/DashboardOverview'
import { getAssets, getOverviewSummary, getRecentActivity, getTypes, getZones } from '../services/dashboard'
import type { AssetFilters, AssetStatus, EquipmentItem } from '../types/dashboard'
import { useLiveQuery } from '../services/live'
import { detectionLabel } from '../components/DashboardParts'

export function DashboardPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [draft, setDraft] = useState({ q: '', epc: '' })
  const [filters, setFilters] = useState<AssetFilters>({ page: 1, page_size: 20, sort: 'prioridade', somente_ativos: true })
  const assets = useLiveQuery(`assets:${JSON.stringify(filters)}`, (signal) => getAssets(filters, signal))
  const options = useLiveQuery('filters', async (signal) => {
    const [types, zones] = await Promise.all([getTypes(signal), getZones(signal)])
    return { types, zones }
  })
  const summaryQuery = useLiveQuery(`summary:${filters.somente_ativos}`, (signal) => getOverviewSummary(signal, filters.somente_ativos))
  const activityQuery = useLiveQuery(`activity:${filters.somente_ativos}`, (signal) => getRecentActivity(signal, filters.somente_ativos))
  const data = assets.data
  const types = options.data?.types ?? []
  const zones = options.data?.zones ?? []
  const summary = summaryQuery.data
  const activity = activityQuery.data
  const filterError = options.error
  const phase = assets.loading ? 'loading' : assets.error ? 'error' : 'loaded'
  const summaryPhase = summaryQuery.error ? 'error' : 'loaded'
  const activityPhase = activityQuery.loading ? 'loading' : activityQuery.error ? 'error' : 'loaded'
  const errorMessage = String(assets.error).includes('422') ? 'Confira o EPC e os filtros informados.' : 'Não foi possível carregar os equipamentos.'
  function changeFilters(next: AssetFilters) { setFilters(next) }
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
      <label>Status<select value={filters.status ?? ''} onChange={(e) => changeFilters({ ...filters, status: (e.target.value || undefined) as AssetStatus | undefined, somente_ativos: e.target.value === 'fora_de_servico' ? false : filters.somente_ativos, page: 1 })}><option value="">Todos</option><option value="disponivel">Em trânsito</option><option value="atencao">Atenção necessária</option><option value="fora_de_servico">Fora de serviço</option><option value="nunca_detectado">Sem zona confirmada</option></select></label>
      <label>Zona<select value={filters.zona ?? ''} onChange={(e) => changeFilters({ ...filters, zona: e.target.value ? Number(e.target.value) : undefined, page: 1 })}><option value="">Todas</option>{zones.map((zone) => <option key={zone.id} value={zone.id}>{zone.nome}</option>)}</select></label>
      <button type="submit">Buscar</button>
    </form>
    <label className="checkbox-label inventory-options"><input type="checkbox" checked={!filters.somente_ativos} onChange={(event) => changeFilters({ ...filters, somente_ativos: !event.target.checked, status: !event.target.checked && filters.status === 'fora_de_servico' ? undefined : filters.status, page: 1 })}/> Mostrar cadastros inativos (ensaios arquivados)</label>
    {filterError && <p role="alert">Não foi possível carregar as opções de tipo e zona. Tentando novamente automaticamente.</p>}
    {summaryPhase === 'error' && <p role="alert">Não foi possível carregar os indicadores. Tentando novamente automaticamente.</p>}
    {phase === 'loading' && <div className="panel table-skeleton" role="status" aria-label="Carregando equipamentos"><span/><span/><span/></div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>{errorMessage}</h2>Tentando novamente automaticamente.</div>}
    {data && <DashboardOverview data={data} summary={summary} onSelect={onSelect} onPage={(page) => changeFilters({ ...filters, page })}/>}
    <section className="panel activity-panel" aria-labelledby="activity-title">
      <div className="panel-heading"><div><p className="eyebrow">HISTÓRICO</p><h2 id="activity-title">Movimentações recentes</h2></div></div>
      {activityPhase === 'loading' && <p role="status">Carregando movimentações...</p>}
      {activityPhase === 'error' && <p role="alert">Não foi possível carregar as movimentações. Tentando novamente automaticamente.</p>}
      {activityPhase === 'loaded' && activity?.length === 0 && <p>Nenhuma movimentação registrada.</p>}
      {activity && activity.length > 0 && <ol className="activity-list">{activity.map((movement) => <li key={movement.id}>
        <strong>{movement.equipamento_nome}</strong> · {movement.zona_origem ?? 'Origem não registrada'} → {movement.zona_destino}
        <small>{detectionLabel(movement.movimentada_em)}{movement.origem_registro === 'correcao_manual' ? ' · Correção manual' : ''}</small>
      </li>)}</ol>}
    </section>
  </>
}
