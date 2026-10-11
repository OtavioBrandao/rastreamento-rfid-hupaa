import { useState } from 'react'
import { hospitalContextAreas, hospitalMainZones, hospitalPortals } from '../../config/mapaConfig'
import type { EquipmentItem } from '../../types/dashboard'
import { bindZones, bindPortals, type MapTopology } from '../../services/mapTopology'
import { MapWorkspace } from './MapWorkspace'

export function MapaHospital({ topology, items, onSelect }: { topology: MapTopology; items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void }) {
  const [showEquipment, setShowEquipment] = useState(true)
  const boundZones = bindZones(hospitalMainZones, topology.zones)
  const portals = bindPortals(hospitalPortals, topology, boundZones)
  return <div className="map-layout"><div className="map-main">
    <section className="panel map-control-panel"><h2>Planta de referência · HUPAA</h2><p className="map-help">Clique em uma zona para ver os equipamentos. A última zona conhecida não indica posição exata.</p><label><input type="checkbox" checked={showEquipment} onChange={(e) => setShowEquipment(e.target.checked)}/> Mostrar equipamentos</label></section>
    <MapWorkspace mode="hospital" zones={boundZones} portals={portals} items={items} onSelect={onSelect} areas={hospitalContextAreas} showEquipment={showEquipment}/>
  </div></div>
}
