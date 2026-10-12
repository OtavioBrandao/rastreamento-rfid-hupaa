import { useState, type KeyboardEvent } from 'react'
import { belongsToZone, type BoundPortal, type BoundZone } from '../../services/mapTopology'
import type { EquipmentItem } from '../../types/dashboard'
import { LocationBadge, PresenceBadge, StatusBadge, detectionLabel } from '../DashboardParts'
import { MapReferences } from './MapReferences'
import { RegisteredDetections } from './RegisteredDetections'
import { clusterTone } from './ZoneCluster'

const tabs = [
  { id: 'detectados', label: 'Equipamentos detectados' },
  { id: 'salas', label: 'Ativos nas salas' },
  { id: 'zonas', label: 'Zonas e portais' },
  { id: 'sem-zona', label: 'Sem zona confirmada' },
  { id: 'outras', label: 'Outras zonas' },
] as const
type TabId = typeof tabs[number]['id']

// Na zona selecionada, quem está em trânsito vem antes de quem pode estar com a localização desatualizada.
export function zonePriority(items: EquipmentItem[], now = Date.now()) {
  const rank = (item: EquipmentItem) => item.localizacao_desatualizada ? 2 : clusterTone(item, now) === 'recente' ? 0 : 1
  return [...items].sort((a, b) => rank(a) - rank(b) || a.nome.localeCompare(b.nome, 'pt-BR'))
}

function EquipmentTable({ items, onSelect, empty }: { items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void; empty: string }) {
  return items.length ? <div className="table-wrap"><table className="equipment-table">
    <thead><tr><th>Equipamento</th><th>Status</th><th>Última zona confirmada</th><th>Última detecção / leitura</th></tr></thead>
    <tbody>{items.map((item) => <tr key={item.id}>
      <td><button className="table-item-button" type="button" onClick={() => onSelect(item)}>{item.nome}<small>{item.epc ?? 'Sem EPC associado'}</small></button></td>
      <td><StatusBadge status={item.status}/></td>
      <td>{item.ultima_zona?.caminho ?? 'Nenhuma passagem confirmada'}<LocationBadge item={item}/></td>
      <td>{detectionLabel(item.ultima_deteccao_em)}<PresenceBadge reading={item.ultima_leitura}/></td>
    </tr>)}</tbody>
  </table></div> : <p className="map-table-empty">{empty}</p>
}

/**
 * Abas abaixo da planta. Os painéis ficam montados (apenas ocultos) para preservar
 * consultas ao vivo e o estado de cada aba ao alternar ou ao inspecionar uma zona.
 */
export function MapDataTabs({ mode, zones, portals, items, onSelect, selectedZone, onZone, onCloseZone }: {
  mode: 'hospital' | 'lab'; zones: BoundZone[]; portals: BoundPortal[]; items: EquipmentItem[]
  onSelect: (item: EquipmentItem) => void; selectedZone?: BoundZone
  onZone: (id: string) => void; onCloseZone: () => void
}) {
  const [tab, setTab] = useState<TabId>('detectados')
  const positioned = items.filter((item) => zones.some((zone) => belongsToZone(item, zone)))
  const never = items.filter((item) => item.status === 'nunca_detectado')
  const other = items.filter((item) => item.status !== 'nunca_detectado' && !positioned.includes(item))
  const counts: Partial<Record<TabId, number>> = { salas: positioned.length, 'sem-zona': never.length, outras: other.length }
  const tabId = (id: TabId) => `map-${mode}-tab-${id}`
  const panelId = (id: TabId) => `map-${mode}-panel-${id}`
  function keyNav(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : undefined
    if (next === undefined) return
    event.preventDefault()
    setTab(tabs[next].id)
    document.getElementById(tabId(tabs[next].id))?.focus()
  }
  const zoneItems = selectedZone ? zonePriority(items.filter((item) => belongsToZone(item, selectedZone))) : []
  return <div className="map-data">
    <div className="map-data-tabs-wrap" hidden={!!selectedZone}>
      <div className="map-data-tabs" role="tablist" aria-label="Dados da planta">
        {tabs.map((entry, index) => <button key={entry.id} id={tabId(entry.id)} type="button" role="tab"
          aria-selected={tab === entry.id} aria-controls={panelId(entry.id)} tabIndex={tab === entry.id ? 0 : -1}
          onClick={() => setTab(entry.id)} onKeyDown={(event) => keyNav(event, index)}>
          {entry.label}{counts[entry.id] !== undefined && <span className="tab-count">{counts[entry.id]}</span>}
        </button>)}
      </div>
      {tabs.map((entry) => <div key={entry.id} id={panelId(entry.id)} role="tabpanel" aria-labelledby={tabId(entry.id)} hidden={tab !== entry.id} className="map-data-panel">
        {entry.id === 'detectados' ? <RegisteredDetections items={items} onSelect={onSelect}/>
          : entry.id === 'zonas' ? <MapReferences zones={zones} portals={portals} items={items} selectedZone={selectedZone?.id ?? ''} onZone={onZone}/>
          : <section className="panel inventory-panel" aria-label={entry.label}><div className="panel-heading"><h2>{entry.label}</h2></div>
            <EquipmentTable items={entry.id === 'salas' ? positioned : entry.id === 'sem-zona' ? never : other} onSelect={onSelect}
              empty={entry.id === 'salas' ? 'Nenhum equipamento com zona mapeada nesta planta.' : 'Nenhum ativo nesta condição.'}/>
          </section>}
      </div>)}
    </div>
    {selectedZone && <section className="panel inventory-panel zone-table" aria-label={`Equipamentos em ${selectedZone.name}`}>
      <div className="panel-heading"><div><p className="eyebrow">ZONA SELECIONADA</p><h2>Equipamentos em {selectedZone.name}</h2></div>
        <button type="button" className="zone-table-close" onClick={onCloseZone}>Fechar zona e voltar às abas</button></div>
      <EquipmentTable items={zoneItems} onSelect={onSelect} empty="Nenhum equipamento nesta zona agora."/>
    </section>}
  </div>
}
