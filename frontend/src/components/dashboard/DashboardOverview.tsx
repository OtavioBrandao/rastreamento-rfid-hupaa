import type { DashboardData, EquipmentItem, OperationalStatus } from '../../types/dashboard'
import { StatusBadge } from '../DashboardParts'
import { OperationalBadge } from '../equipamento/EquipmentDrawer'
import { Icon } from '../layout/Icon'

const kpiOrder: { status: OperationalStatus; label: string }[] = [
  { status: 'available', label: 'Disponíveis' }, { status: 'attention', label: 'Atenção necessária' },
  { status: 'offline', label: 'Offline' }, { status: 'critical', label: 'Fora de serviço' },
]

export function DashboardOverview({ data, items, query, onSelect }: { data: DashboardData; items: EquipmentItem[]; query: string; onSelect: (item: EquipmentItem) => void }) {
  const counts = Object.fromEntries(kpiOrder.map(({ status }) => [status, data.equipment.filter((item) => item.operationalStatus === status).length]))
  const groups = Array.from(new Set(items.map((item) => item.department))).map((department) => {
    const members = items.filter((item) => item.department === department)
    return { department, total: members.length, available: members.filter((item) => item.operationalStatus === 'available').length }
  })
  const attention = data.equipment.filter((item) => item.operationalStatus === 'attention' || item.operationalStatus === 'critical')
  const activity = data.equipment.flatMap((item) => item.readings.map((reading) => ({ item, reading }))).sort((a, b) => b.reading.timestamp.localeCompare(a.reading.timestamp, 'pt-BR')).slice(0, 5)
  // TODO(API): substituir série sintética por endpoint agregado de 30 dias.
  const trend = [65, 66, 64, 68, 70, 69, 71, 73, 72, 75, 73, 74, 76, 79, 77, 78, 80, 77, 81, 82, 80, 83, 82, 84, 83, 85, 84, 86, 85, 86]
  const points = trend.map((value, index) => `${(index / 29) * 300},${100 - value}`).join(' ')
  return <>
    <section aria-labelledby="summary-title" className="summary-section">
      <div className="section-heading"><div><p className="eyebrow">PANORAMA</p><h2 id="summary-title">Situação dos equipamentos</h2></div><p>Dados de demonstração</p></div>
      <div className="kpi-grid">
        <article className="kpi-card kpi-total"><span>Total de equipamentos</span><strong>{data.equipment.length}</strong><small>Cadastrados na amostra</small></article>
        {kpiOrder.map(({ status, label }) => <article className={`kpi-card kpi-${status}`} key={status}><span>{label}</span><strong>{counts[status]}</strong><small><OperationalBadge status={status}/></small></article>)}
      </div>
      <p className="recency-summary">Última detecção: {data.summary.recent} recente · {data.summary.outdated} desatualizadas · {data.summary.never} sem leitura.</p>
    </section>

    <div className="overview-grid">
      <section className="panel inventory-panel" aria-labelledby="inventory-title"><div className="panel-heading"><div><p className="eyebrow">INVENTÁRIO</p><h2 id="inventory-title">Equipamentos por área</h2></div><span>{items.length} itens</span></div>
        {items.length ? <><div className="department-list">{groups.map((group) => <div className="department-row" key={group.department}><div><strong>{group.department}</strong><span>{group.available} disponíveis de {group.total}</span></div><div className="availability-track" role="meter" aria-label={`Disponibilidade em ${group.department}`} aria-valuenow={group.available} aria-valuemin={0} aria-valuemax={group.total}><span style={{ width: `${(group.available / group.total) * 100}%` }}/></div></div>)}</div>
          <div className="table-wrap"><table className="equipment-table"><thead><tr><th>Equipamento</th><th>Departamento / zona</th><th>Condição</th><th>Última detecção</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} onClick={() => onSelect(item)}><td data-label="Equipamento"><button className="table-item-button" type="button" onClick={(event) => { event.stopPropagation(); onSelect(item) }}>{item.name}<small>{item.assetNumber}</small></button></td><td data-label="Departamento / zona"><strong>{item.department}</strong><small>{item.zone ?? 'Nenhuma localização registrada'}</small></td><td data-label="Condição"><OperationalBadge status={item.operationalStatus}/></td><td data-label="Última detecção"><StatusBadge status={item.status}/><small>{item.detectedAgo ?? 'Sem registro'}</small></td></tr>)}</tbody></table></div></> : <div className="empty-panel"><h3>{query ? 'Nenhum equipamento encontrado' : 'Nenhum equipamento cadastrado'}</h3><p>{query ? 'Tente buscar por outro nome, patrimônio ou EPC.' : 'Os equipamentos aparecerão aqui quando houver dados disponíveis.'}</p></div>}
      </section>
      <div className="overview-side">
        <section className="panel attention-panel" aria-labelledby="attention-title"><div className="panel-heading"><div><p className="eyebrow">PRIORIDADE</p><h2 id="attention-title">Precisam de atenção</h2></div><Icon name="alert"/></div>{attention.length ? <ul>{attention.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}><span><strong>{item.name}</strong><small>{item.department} · {item.assetNumber}</small></span><Icon name="arrow" size={16}/></button></li>)}</ul> : <p className="muted">Nenhum equipamento sinalizado.</p>}</section>
        <section className="panel trend-panel" aria-labelledby="trend-title"><div className="panel-heading"><div><p className="eyebrow">ÚLTIMOS 30 DIAS</p><h2 id="trend-title">Disponibilidade</h2></div><span className="demo-tag">série sintética</span></div><div className="trend-value">86% <small>no fim da série</small></div><svg role="img" aria-label="Tendência sintética de disponibilidade crescente de 65% a 86% em 30 dias" viewBox="0 0 300 45" preserveAspectRatio="none"><path d="M0 38H300" stroke="#dce7e4"/><polyline points={points} fill="none" stroke="var(--teal)" strokeWidth="2.5" vectorEffect="non-scaling-stroke"/></svg><div className="trend-axis"><span>30 dias atrás</span><span>Hoje</span></div></section>
        <section className="panel recent-panel" aria-labelledby="recent-title"><div className="panel-heading"><div><p className="eyebrow">LEITURAS</p><h2 id="recent-title">Atividade recente</h2></div><Icon name="clock"/></div>{activity.length ? <ol>{activity.map(({ item, reading }) => <li key={`${item.id}-${reading.timestamp}`}><span className="activity-timeline-dot"/><div><button type="button" onClick={() => onSelect(item)}>{item.name}</button><p>{reading.portal} · {reading.timestamp}</p></div></li>)}</ol> : <p className="muted">Nenhuma leitura registrada.</p>}</section>
      </div>
    </div>
  </>
}
