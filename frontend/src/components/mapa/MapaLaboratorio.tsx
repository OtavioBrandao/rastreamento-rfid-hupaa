import { useEffect, useRef, useState } from 'react'
import { labInfrastructure } from '../../config/mapaConfig'
import { getLabReadings, type LabReading } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { StatusBadge } from '../DashboardParts'
import { FloorMap, type MapMarker } from './FloorMap'

const labZones = [
  { ref: 'sala-a', name: 'Sala A', x: 25, y: 38 },
  { ref: 'sala-b', name: 'Sala B', x: 75, y: 38 },
]

export function MapaLaboratorio({ items, epc, onSelect }: { items: EquipmentItem[]; epc: string; onSelect: (item: EquipmentItem) => void }) {
  const [selectedZone, setSelectedZone] = useState('')
  const [readings, setReadings] = useState<LabReading[]>([])
  const [activeAntenna, setActiveAntenna] = useState<{ id: string; readingId: number } | null>(null)
  const [readError, setReadError] = useState(false)
  const [loadingReadings, setLoadingReadings] = useState(true)
  const timer = useRef<number | null>(null)
  useEffect(() => {
    const controller = new AbortController()
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
        busy = false
      }
    }
    void refresh()
    const interval = window.setInterval(() => { void refresh() }, 1000)
    return () => { controller.abort(); window.clearInterval(interval); window.clearInterval(pulseInterval); if (timer.current !== null) window.clearTimeout(timer.current) }
  }, [epc])
  const never = items.filter((item) => item.status === 'nunca_detectado')
  const positioned = items.filter((item) => labZones.some((zone) => zone.ref === item.ultima_zona?.referencia_planta))
  const unmapped = items.filter((item) => item.status !== 'nunca_detectado' && !positioned.includes(item))
  const markers: MapMarker[] = [
    ...labInfrastructure.map((entry) => ({ id: entry.id, kind: entry.type, x: entry.x, y: entry.y, label: entry.label, detail: entry.room, pulse: activeAntenna?.id === entry.id, pulseKey: activeAntenna?.id === entry.id ? activeAntenna.readingId : undefined })),
    ...labZones.flatMap((zone) => {
      const members = positioned.filter((item) => item.ultima_zona?.referencia_planta === zone.ref)
      const count = members.length
      return count ? [{ id: zone.ref, kind: 'equipment' as const, x: zone.x, y: zone.y,
        label: `${count} equipamento${count === 1 ? '' : 's'}`, detail: `Última zona: ${zone.name}`,
        status: members.some((item) => item.status === 'atencao') ? 'atencao' as const : members[0].status }] : []
    }),
  ]
  return <div className="map-layout lab-layout">
    <div className="map-main"><section className="panel map-control-panel"><h2>Laboratório de Testes · EASY</h2><p className="map-help">O pulso mostra cada leitura recebida pela antena. O marcador do equipamento mostra a última zona confirmada por passagem; pode atualizar depois do pulso.</p></section><FloorMap mode="lab" markers={markers} onMarkerClick={(marker) => { if (marker.kind === 'equipment') setSelectedZone(marker.id) }}/>
    </div>
    <aside className="map-sidebar">
      <section className="panel"><h2>Ativos nas salas</h2>{selectedZone && <button type="button" className="text-button" onClick={() => setSelectedZone('')}>Mostrar todas as salas</button>}{positioned.length ? <ul className="asset-list">{positioned.filter((item) => !selectedZone || item.ultima_zona?.referencia_planta === selectedZone).map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC'} · {item.ultima_zona?.nome}</small><StatusBadge status={item.status}/></li>)}</ul> : <p>Nenhum ativo com zona de laboratório mapeada.</p>}</section>
      <section className="panel"><h2>Ainda não detectados</h2>{never.length ? <ul className="asset-list">{never.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC'}</small></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel"><h2>Outras zonas</h2>{unmapped.length ? <ul className="asset-list">{unmapped.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.ultima_zona?.nome ?? 'Sem zona'}</small></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel lab-log" aria-label="Leituras das antenas"><h2>Leituras das antenas</h2>{loadingReadings && <p role="status">Carregando leituras...</p>}{readError && <p role="alert">Não foi possível atualizar as leituras. Tentando novamente...</p>}{readings.length ? <ol>{readings.map((reading) => <li key={reading.id}><strong>{reading.epc}</strong><p>Antena {reading.antena_porta === 1 ? 'A' : reading.antena_porta === 2 ? 'B' : reading.antena_porta} · {new Date(reading.recebido_em).toLocaleString('pt-BR')}</p></li>)}</ol> : !loadingReadings && <p>Nenhuma leitura recente para este filtro.</p>}</section>
    </aside>
  </div>
}
