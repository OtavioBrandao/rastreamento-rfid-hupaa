import { useState } from 'react'
import { hospitalContextAreas, hospitalMainZones } from '../../config/mapaConfig'
import type { EquipmentItem } from '../../types/dashboard'
import { StatusBadge } from '../DashboardParts'
import { FloorMap, type MapMarker } from './FloorMap'

export function MapaHospital({ items, onSelect }: { items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void }) {
  const [showEquipment, setShowEquipment] = useState(true)
  const [selectedZone, setSelectedZone] = useState('')
  const never = items.filter((item) => item.status === 'nunca_detectado')
  const positioned = items.filter((item) => hospitalMainZones.some((zone) => zone.id === item.ultima_zona?.referencia_planta))
  const unmapped = items.filter((item) => item.status !== 'nunca_detectado' && !positioned.includes(item))
  // A referência identifica a zona no esquema; o centro da zona não é uma posição medida.
  const markers: MapMarker[] = showEquipment ? hospitalMainZones.flatMap((zone) => {
    const members = positioned.filter((item) => item.ultima_zona?.referencia_planta === zone.id)
    const count = members.length
    return count ? [{ id: zone.id, kind: 'equipment' as const, x: zone.x, y: zone.y,
      label: `${count} equipamento${count === 1 ? '' : 's'}`, detail: `Última zona: ${zone.name}`,
      status: members.some((item) => item.status === 'atencao') ? 'atencao' as const : members[0].status }] : []
  }) : []
  return <div className="map-layout">
    <div className="map-main">
      <section className="panel map-control-panel"><h2>Planta de referência · HUPAA</h2><p className="map-help">Marcadores agregados no centro da zona, sem indicação de posição exata.</p><label><input type="checkbox" checked={showEquipment} onChange={(e) => setShowEquipment(e.target.checked)}/> Mostrar equipamentos</label></section>
      <FloorMap mode="hospital" zones={hospitalContextAreas} mainZones={hospitalMainZones} selectedZoneId={selectedZone} markers={markers} onMarkerClick={(marker) => setSelectedZone(marker.id)} onZoneClick={setSelectedZone}/>
      <p className="map-footnote">Somente zonas cadastradas com referência de planta zona-1, zona-2 ou zona-3 aparecem no esquema.</p>
    </div>
    <aside className="map-sidebar">
      <section className="panel"><h2>Equipamentos por última zona</h2>{selectedZone && <button type="button" className="text-button" onClick={() => setSelectedZone('')}>Mostrar todas as zonas</button>}{positioned.length ? <ul className="asset-list">{positioned.filter((item) => !selectedZone || item.ultima_zona?.referencia_planta === selectedZone).map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.ultima_zona?.nome}</small><StatusBadge status={item.status}/></li>)}</ul> : <p>Nenhum equipamento com zona mapeada.</p>}</section>
      <section className="panel"><h2>Ainda não detectados</h2>{never.length ? <ul className="asset-list">{never.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC associado'}</small></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel"><h2>Fora desta planta ou sem referência</h2>{unmapped.length ? <ul className="asset-list">{unmapped.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.ultima_zona?.nome ?? 'Sem zona cadastrada'}</small></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
    </aside>
  </div>
}
