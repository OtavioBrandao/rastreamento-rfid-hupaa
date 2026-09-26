import { useState } from 'react'
import { hospitalAntennas, hospitalZones } from '../../config/mapaConfig'
import { getDemoMapEquipment } from '../../services/dashboard'
import type { EquipmentItem, OperationalStatus } from '../../types/dashboard'
import { Icon } from '../layout/Icon'
import { FloorMap, type MapMarker } from './FloorMap'

const statusNames: Record<OperationalStatus, string> = { available: 'Disponível', attention: 'Atenção necessária', offline: 'Offline', critical: 'Fora de serviço' }

export function MapaHospital({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [showZones, setShowZones] = useState(true)
  const [showEquipment, setShowEquipment] = useState(true)
  const [showAntennas, setShowAntennas] = useState(false)
  const [query, setQuery] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  const [zone, setZone] = useState('')
  const mapped = getDemoMapEquipment().filter((item) => item.mapZoneId && item.mapX !== null && item.mapY !== null)
  const departments = Array.from(new Set(mapped.map((item) => item.department))).sort()
  const matches = (item: EquipmentItem) => (!query || `${item.name} ${item.assetNumber} ${item.zone ?? ''}`.toLocaleLowerCase('pt-BR').includes(query.toLocaleLowerCase('pt-BR'))) && (!department || item.department === department) && (!status || item.operationalStatus === status) && (!zone || item.mapZoneId === zone)
  const activeFilter = Boolean(query || department || status || zone)
  const equipmentMarkers: MapMarker[] = showEquipment ? mapped.map((item) => ({ id: item.id, kind: 'equipment', x: item.mapX!, y: item.mapY!, label: item.name, detail: `${item.assetNumber} · ${statusNames[item.operationalStatus]}`, status: item.operationalStatus, dimmed: activeFilter && !matches(item) })) : []
  const antennaMarkers: MapMarker[] = showAntennas ? hospitalAntennas.map((antenna) => ({ id: antenna.id, kind: 'antenna', x: antenna.x, y: antenna.y, label: antenna.label, detail: 'Posição ilustrativa da infraestrutura' })) : []
  function select(marker: MapMarker) { if (marker.kind === 'equipment') { const item = mapped.find((candidate) => candidate.id === marker.id); if (item) onSelect(item) } }
  return <div className="map-layout">
    <div className="map-main">
      <div className="panel map-control-panel"><div className="map-control-heading"><div><p className="eyebrow">2º PAVIMENTO · HUPAA</p><h2>Última zona conhecida</h2></div><span className="map-count">{mapped.filter(matches).length} de {mapped.length} na planta</span></div>
        <p className="map-help">Posições ilustrativas dentro da última zona detectada. Não representam rastreamento contínuo.</p>
        <div className="layer-controls" aria-label="Camadas do mapa"><label><input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)}/> Mostrar zonas</label><label><input type="checkbox" checked={showEquipment} onChange={(e) => setShowEquipment(e.target.checked)}/> Mostrar equipamentos</label><label><input type="checkbox" checked={showAntennas} onChange={(e) => setShowAntennas(e.target.checked)}/> Mostrar antenas</label></div>
      </div>
      <FloorMap mode="hospital" zones={hospitalZones} showZones={showZones} markers={[...equipmentMarkers, ...antennaMarkers]} onMarkerClick={select}/>
      <p className="map-footnote">A planta é esquemática. Equipamentos sem detecção ou em outros andares aparecem no Dashboard.</p>
    </div>
    <aside className="map-sidebar"><section className="panel filter-panel" aria-labelledby="filter-title"><div className="panel-heading"><div><p className="eyebrow">EXPLORAR</p><h2 id="filter-title">Filtrar equipamentos</h2></div><Icon name="search"/></div><label>Nome, patrimônio ou zona<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar na planta"/></label><label>Departamento<select value={department} onChange={(e) => setDepartment(e.target.value)}><option value="">Todos</option>{departments.map((value) => <option key={value}>{value}</option>)}</select></label><label>Condição<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Todas</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Zona<select value={zone} onChange={(e) => setZone(e.target.value)}><option value="">Todas</option>{hospitalZones.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>{activeFilter && <button className="text-button" type="button" onClick={() => { setQuery(''); setDepartment(''); setStatus(''); setZone('') }}>Limpar filtros</button>}</section>
      <section className="panel legend-panel" aria-labelledby="legend-title"><div className="panel-heading"><div><p className="eyebrow">REFERÊNCIA</p><h2 id="legend-title">Legenda</h2></div><Icon name="layers"/></div><h3>Zonas</h3><ul>{hospitalZones.map((zone) => <li key={zone.id}><span className="legend-swatch" style={{ backgroundColor: zone.color }}/>{zone.name}</li>)}</ul><h3>Equipamentos e infraestrutura</h3><ul>{Object.entries(statusNames).map(([key, label]) => <li key={key}><span className={`legend-status legend-${key}`}><Icon name="equipment" size={13}/></span>{label}</li>)}<li><span className="legend-status legend-antenna"><Icon name="antenna" size={13}/></span>Antena RFID</li></ul></section>
    </aside>
  </div>
}
