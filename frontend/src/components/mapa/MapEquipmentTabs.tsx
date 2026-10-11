import { useState, type KeyboardEvent } from 'react'
import { belongsToZone, type BoundPortal, type BoundZone } from '../../services/mapTopology'
import type { EquipmentItem } from '../../types/dashboard'
import { AssetStatusBadge, LocationBadge, PresenceBadge, detectionLabel } from '../DashboardParts'
import { MapReferences } from './MapReferences'
import { RegisteredDetections } from './RegisteredDetections'

const tabs = [
  { id: 'registered', label: 'Equipamentos cadastrados' },
  { id: 'rooms', label: 'Ativos nas salas' },
  { id: 'topology', label: 'Zonas e portais' },
  { id: 'unconfirmed', label: 'Sem zona confirmada' },
  { id: 'other', label: 'Outras zonas' },
] as const
type TabId = typeof tabs[number]['id']

function EquipmentTable({ items, onSelect, emptyMessage }: {
  items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void; emptyMessage: string
}) {
  return items.length ? <div className="table-wrap"><table className="equipment-table">
    <thead><tr><th>Equipamento</th><th>Status</th><th>Última zona confirmada</th><th>Última detecção / leitura</th></tr></thead>
    <tbody>{items.map((item) => <tr key={item.id}>
      <td data-label="Equipamento"><button className="table-item-button" type="button" onClick={() => onSelect(item)}>{item.nome}<small>{item.identificador_interno} · {item.epc ?? 'Sem EPC'}</small></button></td>
      <td data-label="Status"><AssetStatusBadge item={item}/></td>
      <td data-label="Última zona"><div>{item.ultima_zona?.caminho ?? 'Nenhuma passagem confirmada'}<LocationBadge item={item}/></div></td>
      <td data-label="Detecção / leitura"><div>{detectionLabel(item.ultima_deteccao_em)}<PresenceBadge reading={item.ultima_leitura}/></div></td>
    </tr>)}</tbody>
  </table></div> : <p className="map-table-empty">{emptyMessage}</p>
}

export function MapEquipmentTabs({ mode, zones, portals, items, onSelect, selectedZone, onZone, onCollapse }: {
  mode: 'hospital' | 'lab'; zones: BoundZone[]; portals: BoundPortal[]; items: EquipmentItem[]
  onSelect: (item: EquipmentItem) => void; selectedZone?: BoundZone
  onZone: (id: string) => void; onCollapse: () => void
}) {
  const [tab, setTab] = useState<TabId>('registered')
  const positioned = items.filter((item) => zones.some((zone) => belongsToZone(item, zone)))
  const unconfirmed = items.filter((item) => !item.ultima_zona)
  const other = items.filter((item) => item.ultima_zona && !positioned.includes(item))
  const tabId = (id: string) => `map-${mode}-tab-${id}`
  const panelId = (id: string) => `map-${mode}-panel-${id}`
  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : undefined
    if (next === undefined) return
    event.preventDefault()
    setTab(tabs[next].id)
    document.getElementById(tabId(tabs[next].id))?.focus()
  }
  return <div className="map-equipment-browser">
    {/* O resumo continua montado e atualizando mesmo durante a inspeção de uma zona. */}
    <div hidden={!!selectedZone}>
      <div className="map-data-tabs" role="tablist" aria-label="Informações do mapa">
        {tabs.map((entry, index) => <button key={entry.id} type="button" role="tab" id={tabId(entry.id)}
          aria-selected={tab === entry.id} aria-controls={panelId(entry.id)} tabIndex={tab === entry.id ? 0 : -1}
          onClick={() => setTab(entry.id)} onKeyDown={(event) => navigate(event, index)}>{entry.label}</button>)}
      </div>
      {tabs.map((entry) => <div key={entry.id} id={panelId(entry.id)} role="tabpanel" aria-labelledby={tabId(entry.id)} hidden={tab !== entry.id} tabIndex={0}>
        {entry.id === 'registered' ? <RegisteredDetections items={items} onSelect={onSelect}/>
          : entry.id === 'topology' ? <MapReferences zones={zones} portals={portals} items={items} selectedZone="" onZone={onZone}/>
          : <section className="panel inventory-panel"><div className="panel-heading"><h2>{entry.label}</h2></div>
            <EquipmentTable items={entry.id === 'rooms' ? positioned : entry.id === 'unconfirmed' ? unconfirmed : other}
              onSelect={onSelect} emptyMessage={entry.id === 'rooms' ? 'Nenhum equipamento com zona mapeada nesta planta.' : 'Nenhum ativo nesta condição.'}/>
          </section>}
      </div>)}
    </div>
    {selectedZone && <section className="panel inventory-panel" aria-label={`Ativos na zona ${selectedZone.name}`} onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); onCollapse() } }}>
      <div className="panel-heading"><div><p className="eyebrow">ZONA SELECIONADA</p><h2>Equipamentos em {selectedZone.name}</h2></div><button type="button" className="text-button" onClick={onCollapse}>Voltar à visão geral</button></div>
      <EquipmentTable items={items.filter((item) => belongsToZone(item, selectedZone))} onSelect={onSelect} emptyMessage="Nenhum equipamento nesta zona."/>
    </section>}
  </div>
}
