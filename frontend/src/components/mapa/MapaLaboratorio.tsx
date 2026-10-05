import { useLiveRefresh } from '../../services/live'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { labInfrastructure, labMainZones, labPortals } from '../../config/mapaConfig'
import { getLabReadings, type LabReading } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { LocationBadge, PresenceBadge, StatusBadge, detectionLabel } from '../DashboardParts'
import { MapReferences } from './MapReferences'
import { bindZones, bindPortals, belongsToZone, type MapTopology } from '../../services/mapTopology'
import { FloorMap, type MapMarker } from './FloorMap'

export function MapaLaboratorio({ topology, items, epc, onSelect, footer }: { topology: MapTopology; items: EquipmentItem[]; epc: string; onSelect: (item: EquipmentItem) => void; footer?: ReactNode }) {
  const { version, begin } = useLiveRefresh()
  const boundZones = bindZones(labMainZones, topology.zones)
  const portals = bindPortals(labPortals, topology, boundZones)
  const [selectedZone, setSelectedZone] = useState('')
  const [readings, setReadings] = useState<LabReading[]>([])
  const [activeAntenna, setActiveAntenna] = useState<{ id: string; readingId: number } | null>(null)
  const [readError, setReadError] = useState(false)
  const [loadingReadings, setLoadingReadings] = useState(true)
  const timer = useRef<number | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let finish: (() => void) | undefined
    let cursor = 0
    let busy = false
    const pending: LabReading[] = []
    setReadings([])
    setLoadingReadings(true)
    const pulseInterval = window.setInterval(() => {
      const next = pending.shift()
      if (!next) return
      const id = next.antena_porta === 1 ? 'ANT-A' : next.antena_porta === 2 ? 'ANT-B' : null
      if (!id) return
      setActiveAntenna({ id, readingId: next.id })
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setActiveAntenna(null), 900)
    }, 80)
    async function refresh() {
      if (busy) return
      busy = true
      finish = begin()
      try {
        const result = await getLabReadings(cursor, epc, controller.signal)
        if (controller.signal.aborted) return
        cursor = result.next_id
        if (result.items.length) {
          setReadings((old) => [...result.items.slice().reverse(), ...old].slice(0, 20))
          pending.push(...result.items)
        }
        setReadError(false)
      } catch (error) {
        if (!controller.signal.aborted) setReadError(true)
      } finally {
        if (!controller.signal.aborted) setLoadingReadings(false)
        finish?.()
        busy = false
      }
    }
    void refresh()
    const interval = window.setInterval(() => { void refresh() }, 1000)
    return () => { controller.abort(); finish?.(); window.clearInterval(interval); window.clearInterval(pulseInterval); if (timer.current !== null) window.clearTimeout(timer.current) }
  }, [epc, version, begin])
  const never = items.filter((item) => item.status === 'nunca_detectado')
  const positioned = items.filter((item) => boundZones.some((zone) => belongsToZone(item, zone)))
  const unmapped = items.filter((item) => item.status !== 'nunca_detectado' && !positioned.includes(item))
  const markers: MapMarker[] = [
    ...labInfrastructure.map((entry) => ({ id: entry.id, kind: entry.type, x: entry.x, y: entry.y, label: entry.label, detail: entry.room, pulse: activeAntenna?.id === entry.id, pulseKey: activeAntenna?.id === entry.id ? activeAntenna.readingId : undefined })),
    ...boundZones.flatMap((zone) => {
      const members = positioned.filter((item) => belongsToZone(item, zone))
      const count = members.length
      return count ? [{ id: zone.id, kind: 'equipment' as const, x: zone.x, y: zone.y,
        label: `${count} equipamento${count === 1 ? '' : 's'}`, detail: `Última zona: ${zone.name}`,
        status: members.some((item) => item.status === 'atencao') ? 'atencao' as const : members[0].status }] : []
    }),
  ]
  return <div className="map-layout lab-layout">
    <div className="map-main"><section className="panel map-control-panel"><h2>Laboratório de Testes · EASY</h2><p className="map-help">O pulso mostra cada leitura recebida pela antena. O marcador do equipamento mostra a última zona confirmada por passagem; pode atualizar depois do pulso.</p></section><FloorMap mode="lab" markers={[...markers, ...portals.map((portal) => ({ id: portal.id, portalId: portal.portalId, kind: 'portal' as const, x: portal.x, y: portal.y, label: `${portal.name} · Portal #${portal.portalId}`, detail: portal.detail }))]} onMarkerClick={(marker) => { if (marker.kind === 'equipment') setSelectedZone(marker.id) }}/>
    {footer}
    </div>
    <aside className="map-sidebar">
      <MapReferences zones={boundZones} portals={portals} items={items} selectedZone={selectedZone} onZone={setSelectedZone}/>
      <section className="panel"><h2>Ativos nas salas</h2>{selectedZone && <button type="button" className="text-button" onClick={() => setSelectedZone('')}>Mostrar todas as salas</button>}{positioned.length ? <ul className="asset-list">{positioned.filter((item) => !selectedZone || item.ultima_zona?.referencia_planta === selectedZone).map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC'} · {item.ultima_zona?.caminho}</small><StatusBadge status={item.status}/><LocationBadge item={item}/></li>)}</ul> : <p>Nenhum ativo com zona de laboratório mapeada.</p>}</section>
      <section className="panel"><h2>Sem zona confirmada</h2>{never.length ? <ul className="asset-list">{never.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC'}</small><PresenceBadge reading={item.ultima_leitura}/></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel"><h2>Outras zonas</h2>{unmapped.length ? <ul className="asset-list">{unmapped.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.ultima_zona?.caminho ?? 'Sem zona'}</small><StatusBadge status={item.status}/><LocationBadge item={item}/></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel lab-log" aria-label="Leituras das antenas"><h2>Leituras das antenas</h2>{loadingReadings && <p role="status">Carregando leituras...</p>}{readError && <p role="alert">Não foi possível atualizar as leituras. Tentando novamente...</p>}{readings.length ? <ol>{readings.map((reading) => <li key={reading.id}><strong>{reading.epc}</strong><p>Antena {reading.antena_porta === 1 ? 'A' : reading.antena_porta === 2 ? 'B' : reading.antena_porta} · {detectionLabel(reading.recebido_em)}</p></li>)}</ol> : !loadingReadings && <p>Nenhuma leitura recente para este filtro.</p>}</section>
    </aside>
  </div>
}
