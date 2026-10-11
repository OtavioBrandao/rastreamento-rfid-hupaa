import { useLiveRefresh } from '../../services/live'
import { useEffect, useRef, useState } from 'react'
import { labInfrastructure, labMainZones, labPortals } from '../../config/mapaConfig'
import { getLabReadings, type LabReading } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { bindZones, bindPortals, type MapTopology } from '../../services/mapTopology'
import { MapWorkspace } from './MapWorkspace'

export function MapaLaboratorio({ topology, items, epc, onSelect }: { topology: MapTopology; items: EquipmentItem[]; epc: string; onSelect: (item: EquipmentItem) => void }) {
  const { version, begin } = useLiveRefresh()
  const boundZones = bindZones(labMainZones, topology.zones)
  const portals = bindPortals(labPortals, topology, boundZones)
  const [activeAntenna, setActiveAntenna] = useState<{ id: string; readingId: number } | null>(null)
  const [readError, setReadError] = useState(false)
  const timer = useRef<number | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let finish: (() => void) | undefined
    let cursor = 0
    let busy = false
    const pending: LabReading[] = []
    setActiveAntenna(null)
    setReadError(false)
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
          pending.push(...result.items)
        }
        setReadError(false)
      } catch (error) {
        if (!controller.signal.aborted) setReadError(true)
      } finally {
        finish?.()
        busy = false
      }
    }
    void refresh()
    const interval = window.setInterval(() => { void refresh() }, 1000)
    return () => { controller.abort(); finish?.(); window.clearInterval(interval); window.clearInterval(pulseInterval); if (timer.current !== null) window.clearTimeout(timer.current) }
  }, [epc, version, begin])
  const markers = labInfrastructure.map((entry) => ({ id: entry.id, kind: entry.type, x: entry.x, y: entry.y, label: entry.label, detail: entry.room, pulse: activeAntenna?.id === entry.id, pulseKey: activeAntenna?.id === entry.id ? activeAntenna.readingId : undefined }))
  return <div className="map-layout lab-layout"><div className="map-main">
    <section className="panel map-control-panel"><h2>Laboratório de Testes · EASY</h2><p className="map-help">O pulso mostra cada leitura recebida pela antena. Clique em uma sala para ver os equipamentos com última zona confirmada por passagem.</p>{readError && <p role="alert">Não foi possível atualizar o pulso das antenas. Tentando novamente...</p>}</section>
    <MapWorkspace mode="lab" zones={boundZones} portals={portals} items={items} onSelect={onSelect} markers={markers}/>
  </div></div>
}
