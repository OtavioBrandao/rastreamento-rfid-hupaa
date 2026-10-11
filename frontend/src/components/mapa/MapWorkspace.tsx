import { useEffect, useRef, useState } from 'react'
import type { MapZone } from '../../config/mapaConfig'
import { belongsToZone, type BoundPortal, type BoundZone } from '../../services/mapTopology'
import type { EquipmentItem } from '../../types/dashboard'
import { AssetStatusBadge } from '../DashboardParts'
import { Icon } from '../layout/Icon'
import { FloorMap, type MapMarker } from './FloorMap'
import { MapEquipmentTabs } from './MapEquipmentTabs'

/** Seleção compartilhada pelo desenho e pela tabela; os pontos não são posições físicas. */
export function MapWorkspace({ mode, zones, portals, items, onSelect, markers = [], areas = [], showEquipment = true }: {
  mode: 'hospital' | 'lab'; zones: BoundZone[]; portals: BoundPortal[]
  items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void
  markers?: MapMarker[]; areas?: MapZone[]; showEquipment?: boolean
}) {
  const [selectedZoneId, setSelectedZoneId] = useState('')
  const returnFocus = useRef<HTMLElement | null>(null)
  const wasSelected = useRef(false)
  const selectedZone = zones.find((zone) => zone.id === selectedZoneId)
  // Não manter uma seleção invisível se a topologia deixar de ser verificável.
  useEffect(() => {
    if (selectedZoneId && !selectedZone) setSelectedZoneId('')
    if (wasSelected.current && !selectedZone && returnFocus.current?.isConnected) returnFocus.current.focus()
    wasSelected.current = !!selectedZone
  }, [selectedZoneId, selectedZone])
  const members = selectedZone ? items.filter((item) => belongsToZone(item, selectedZone)) : []
  const toggleZone = (id: string) => {
    if (id && id !== selectedZoneId) returnFocus.current = document.activeElement as HTMLElement
    setSelectedZoneId((old) => old === id ? '' : id)
  }
  const collapse = () => setSelectedZoneId('')
  const equipmentMarkers: MapMarker[] = showEquipment ? zones.flatMap((zone) => {
    const assets = items.filter((item) => belongsToZone(item, zone))
    return assets.length ? [{ id: zone.id, kind: 'equipment', x: zone.x, y: zone.y,
      label: zone.name, detail: 'Clique para ver os equipamentos', expanded: selectedZone?.id === zone.id,
      status: assets.some((item) => item.status === 'atencao') ? 'atencao' : assets[0].status }] : []
  }) : []

  return <>
    <FloorMap mode={mode} zones={areas} mainZones={zones} selectedZoneId={selectedZone?.id}
      markers={[...markers, ...equipmentMarkers, ...portals.map((portal) => ({
        id: portal.id, portalId: portal.portalId, kind: 'portal' as const, x: portal.x, y: portal.y,
        label: `${portal.name} · Portal #${portal.portalId}`, detail: portal.detail,
      }))]}
      onMarkerClick={(marker) => { if (marker.kind === 'equipment') toggleZone(marker.id) }}
      onZoneClick={toggleZone}
      expandedZone={selectedZone && showEquipment ? { x: selectedZone.x, y: selectedZone.y, content:
        <section aria-label={`Equipamentos em ${selectedZone.name}`} onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); collapse() } }}>
          <div className="zone-popover-heading"><strong>{selectedZone.name}</strong><button type="button" className="text-button" onClick={collapse} aria-label={`Recolher ${selectedZone.name}`}>Recolher</button></div>
          <p>{members.length} equipamento(s) · Posição ilustrativa</p>
          <div className="zone-equipment-dots">{members.map((item) =>
            <button key={item.id} type="button" className={`zone-equipment-dot marker-${item.status}`} onClick={() => onSelect(item)}>
              <span className="zone-dot-icon"><Icon name="equipment" size={19}/></span>
              <span className="zone-dot-name">{item.nome}</span><span className="zone-dot-status"><AssetStatusBadge item={item}/></span>
            </button>
          )}</div>
          {!members.length && <p>Nenhum equipamento nesta zona.</p>}
        </section>,
      } : undefined}/>
    <p className="map-footnote">A distribuição das bolinhas é ilustrativa. Consulte a última zona confirmada e o histórico de cada equipamento.</p>
    <MapEquipmentTabs mode={mode} zones={zones} portals={portals} items={items} onSelect={onSelect}
      selectedZone={selectedZone} onZone={toggleZone} onCollapse={collapse}/>
  </>
}
