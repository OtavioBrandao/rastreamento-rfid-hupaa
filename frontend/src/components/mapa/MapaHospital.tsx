import { useState } from 'react'
import { hospitalContextAreas, hospitalMainZones } from '../../config/mapaConfig'
import { getDemoMapEquipment } from '../../services/dashboard'
import type { EquipmentItem, OperationalStatus } from '../../types/dashboard'
import { Icon } from '../layout/Icon'
import { FloorMap, type MapMarker } from './FloorMap'

const statusNames: Record<OperationalStatus, string> = { available: 'Disponível', attention: 'Atenção necessária', offline: 'Offline', critical: 'Fora de serviço' }

export function MapaHospital({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [showContext, setShowContext] = useState(true)
  const [showEquipment, setShowEquipment] = useState(false)
  const [query, setQuery] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  const [zone, setZone] = useState('')
  const mapped = getDemoMapEquipment().filter((item) => item.mapZoneId && item.mapX !== null && item.mapY !== null)
  const departments = Array.from(new Set(mapped.map((item) => item.department))).sort()
  const matches = (item: EquipmentItem) => (!query || `${item.name} ${item.assetNumber} ${item.zone ?? ''}`.toLocaleLowerCase('pt-BR').includes(query.toLocaleLowerCase('pt-BR'))) && (!department || item.department === department) && (!status || item.operationalStatus === status) && (!zone || item.mapZoneId === zone)
  const activeFilter = Boolean(query || department || status || zone)
  const markers: MapMarker[] = showEquipment ? mapped.map((item) => ({ id: item.id, kind: 'equipment', x: item.mapX!, y: item.mapY!, label: item.name, detail: `${item.assetNumber} · ${statusNames[item.operationalStatus]}`, status: item.operationalStatus, dimmed: activeFilter && !matches(item) })) : []
  function select(marker: MapMarker) { const item = mapped.find((candidate) => candidate.id === marker.id); if (item) onSelect(item) }
  return <div className="map-layout">
    <div className="map-main">
      <section className="panel map-control-panel"><div className="map-control-heading"><div><p className="eyebrow">2º PAVIMENTO · HUPAA</p><h2>Planta de referência</h2></div><span className="map-count">3 zonas principais</span></div>
        <p className="map-help">O contorno segue o desenho fornecido. As três zonas são provisórias; as cores mostram usos da planta e a circulação para planejar os portais depois.</p>
        <div className="layer-controls" aria-label="Camadas do mapa"><label><input type="checkbox" checked={showContext} onChange={(e) => setShowContext(e.target.checked)}/> Mostrar cores da planta</label><label><input type="checkbox" checked={showEquipment} onChange={(e) => setShowEquipment(e.target.checked)}/> Mostrar equipamentos fictícios</label></div>
      </section>
      <FloorMap mode="hospital" zones={hospitalContextAreas} mainZones={hospitalMainZones} selectedZoneId={zone} showZones={showContext} markers={markers} onMarkerClick={select} onZoneClick={setZone}/>
      <p className="map-footnote">Zonas, posições de equipamentos e limites de detecção ainda dependem de validação física. Nenhum portal foi posicionado nesta planta.</p>
    </div>
    <aside className="map-sidebar">
      <section className="panel sector-panel" aria-labelledby="sector-title"><div className="panel-heading"><div><p className="eyebrow">ESTRUTURA PRELIMINAR</p><h2 id="sector-title">Zonas principais</h2></div><span className="sector-total">03</span></div><p className="map-help">Selecione uma zona para destacar os exemplos de equipamento vinculados a ela.</p><div className="sector-list">{hospitalMainZones.map((mainZone) => <button key={mainZone.id} type="button" aria-pressed={zone === mainZone.id} onClick={() => setZone(zone === mainZone.id ? '' : mainZone.id)}><span>{mainZone.name}</span><small>{mainZone.description}</small></button>)}</div></section>
      <section className="panel legend-panel" aria-labelledby="legend-title"><div className="panel-heading"><div><p className="eyebrow">LEITURA DA PLANTA</p><h2 id="legend-title">Legenda de contexto</h2></div><Icon name="layers"/></div><p className="map-help">Estas cores descrevem espaços e circulação. Elas não definem as três zonas principais nem indicam status de equipamento.</p><ul>{hospitalContextAreas.map((area) => <li key={area.id}><span className="legend-swatch" style={{ backgroundColor: area.color }}/>{area.name}</li>)}</ul></section>
      <section className="panel filter-panel" aria-labelledby="filter-title"><div className="panel-heading"><div><p className="eyebrow">DADOS FICTÍCIOS</p><h2 id="filter-title">Equipamentos</h2></div><Icon name="search"/></div><p className="map-help">{mapped.filter(matches).length} de {mapped.length} exemplos associados à planta. Ative a camada para vê-los.</p><label>Nome, patrimônio ou última área<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar exemplos"/></label><label>Departamento<select value={department} onChange={(e) => setDepartment(e.target.value)}><option value="">Todos</option>{departments.map((value) => <option key={value}>{value}</option>)}</select></label><label>Condição<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Todas</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Zona principal<select value={zone} onChange={(e) => setZone(e.target.value)}><option value="">Todas</option>{hospitalMainZones.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>{activeFilter && <button className="text-button" type="button" onClick={() => { setQuery(''); setDepartment(''); setStatus(''); setZone('') }}>Limpar filtros</button>}</section>
    </aside>
  </div>
}
