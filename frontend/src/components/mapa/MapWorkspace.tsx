import { useState } from 'react'
import type { MapZone } from '../../config/mapaConfig'
import { belongsToZone, type BoundPortal, type BoundZone } from '../../services/mapTopology'
import type { EquipmentItem } from '../../types/dashboard'
import { FloorMap, type MapMarker } from './FloorMap'
import { MapDataTabs } from './MapDataTabs'
import { ZoneCluster } from './ZoneCluster'

/** Planta + abas compartilhando a zona selecionada. Os pontos não são posições físicas. */
export function MapWorkspace({ mode, zones, portals, items, onSelect, markers = [], areas = [], showEquipment = true }: {
  mode: 'hospital' | 'lab'; zones: BoundZone[]; portals: BoundPortal[]; items: EquipmentItem[]
  onSelect: (item: EquipmentItem) => void; markers?: MapMarker[]; areas?: MapZone[]; showEquipment?: boolean
}) {
  const [selectedId, setSelectedId] = useState('')
  // Se a topologia deixar de validar a zona, a seleção some junto com ela.
  const selectedZone = zones.find((zone) => zone.id === selectedId)
  const toggle = (id: string) => setSelectedId((old) => old === id ? '' : id)
  const close = () => setSelectedId('')
  const equipmentMarkers: MapMarker[] = showEquipment ? zones.flatMap((zone) => {
    const members = items.filter((item) => belongsToZone(item, zone))
    const count = members.length
    return count ? [{ id: zone.id, kind: 'equipment' as const, x: zone.x, y: zone.y,
      label: 'Clique para ver os equipamentos', detail: '', selected: selectedZone?.id === zone.id,
      ariaLabel: `${count} equipamento${count === 1 ? '' : 's'} em ${zone.name}. Clique para ver os equipamentos`,
      status: members.some((item) => item.status === 'atencao') ? 'atencao' as const : members[0].status }] : []
  }) : []
  const portalMarkers: MapMarker[] = portals.map((portal) => ({ id: portal.id, portalId: portal.portalId, kind: 'portal', x: portal.x, y: portal.y,
    label: `${portal.name} · Portal #${portal.portalId}`, detail: portal.detail }))
  return <>
    <FloorMap mode={mode} zones={areas} mainZones={zones} selectedZoneId={selectedZone?.id}
      markers={[...markers, ...equipmentMarkers, ...portalMarkers]}
      onMarkerClick={(marker) => { if (marker.kind === 'equipment') toggle(marker.id) }} onZoneClick={toggle}
      overlay={selectedZone && <ZoneCluster zone={selectedZone} items={items.filter((item) => belongsToZone(item, selectedZone))} onSelect={onSelect} onClose={close}/>}/>
    <p className="map-footnote">Marcadores agregados por zona de presença. A distribuição das bolinhas é ilustrativa, não indica posição exata.</p>
    <MapDataTabs mode={mode} zones={zones} portals={portals} items={items} onSelect={onSelect} selectedZone={selectedZone} onZone={toggle} onCloseZone={close}/>
  </>
}
