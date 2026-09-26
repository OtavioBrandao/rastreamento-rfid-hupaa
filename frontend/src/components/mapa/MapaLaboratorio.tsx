import { useEffect, useRef, useState } from 'react'
import { labInfrastructure } from '../../config/mapaConfig'
import type { EquipmentItem } from '../../types/dashboard'
import { StatusBadge } from '../DashboardParts'
import { FloorMap, type MapMarker } from './FloorMap'

const labZones = [
  { ref: 'sala-a', name: 'Sala A', x: 25, y: 38 },
  { ref: 'sala-b', name: 'Sala B', x: 75, y: 38 },
]

export function MapaLaboratorio({ items, onSelect }: { items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void }) {
  const [selectedZone, setSelectedZone] = useState('')
  const [readings, setReadings] = useState<{ id: number; epc: string; room: string; timestamp: string }[]>([])
  const [activeAntenna, setActiveAntenna] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const serial = useRef(0)
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current) }, [])
  function simulate(antennaId: string) {
    const antenna = labInfrastructure.find((entry) => entry.id === antennaId)
    if (!antenna) return
    const id = ++serial.current
    setReadings((old) => [{ id, epc: `E2000017221101441890A00${id % 10}`, room: antenna.room,
      timestamp: new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date()) }, ...old].slice(0, 20))
    setActiveAntenna(antennaId)
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setActiveAntenna(null), 1700)
  }
  const never = items.filter((item) => item.status === 'nunca_detectado')
  const positioned = items.filter((item) => labZones.some((zone) => zone.ref === item.ultima_zona?.referencia_planta))
  const unmapped = items.filter((item) => item.status !== 'nunca_detectado' && !positioned.includes(item))
  const markers: MapMarker[] = [
    ...labInfrastructure.map((entry) => ({ id: entry.id, kind: entry.type, x: entry.x, y: entry.y, label: entry.label, detail: entry.room, pulse: activeAntenna === entry.id })),
    ...labZones.flatMap((zone) => {
      const members = positioned.filter((item) => item.ultima_zona?.referencia_planta === zone.ref)
      const count = members.length
      return count ? [{ id: zone.ref, kind: 'equipment' as const, x: zone.x, y: zone.y,
        label: `${count} equipamento${count === 1 ? '' : 's'}`, detail: `Última zona: ${zone.name}`,
        status: members.some((item) => item.status === 'atencao') ? 'atencao' as const : members[0].status }] : []
    }),
  ]
  return <div className="map-layout lab-layout">
    <div className="map-main"><section className="panel map-control-panel"><h2>Laboratório de Testes · EASY</h2><p className="map-help">A consulta EPC acima usa a API real. Marcadores de equipamento indicam apenas a zona cadastrada; antenas e leitor continuam no esquema de referência.</p></section><FloorMap mode="lab" markers={markers} onMarkerClick={(marker) => { if (marker.kind === 'equipment') setSelectedZone(marker.id) }}/>
      <div className="lab-actions"><div><strong>Simular detecção</strong><p>Leituras abaixo são exemplos locais e não alteram a API.</p></div><button type="button" onClick={() => simulate('ANT-A')}>Leitura simulada na Sala A</button><button type="button" onClick={() => simulate('ANT-B')}>Leitura simulada na Sala B</button></div>
    </div>
    <aside className="map-sidebar">
      <section className="panel"><h2>Ativos nas salas</h2>{selectedZone && <button type="button" className="text-button" onClick={() => setSelectedZone('')}>Mostrar todas as salas</button>}{positioned.length ? <ul className="asset-list">{positioned.filter((item) => !selectedZone || item.ultima_zona?.referencia_planta === selectedZone).map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC'} · {item.ultima_zona?.nome}</small><StatusBadge status={item.status}/></li>)}</ul> : <p>Nenhum ativo com zona de laboratório mapeada.</p>}</section>
      <section className="panel"><h2>Ainda não detectados</h2>{never.length ? <ul className="asset-list">{never.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.epc ?? 'Sem EPC'}</small></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel"><h2>Outras zonas</h2>{unmapped.length ? <ul className="asset-list">{unmapped.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item)}>{item.nome}</button><small>{item.ultima_zona?.nome ?? 'Sem zona'}</small></li>)}</ul> : <p>Nenhum ativo nesta condição.</p>}</section>
      <section className="panel lab-log" aria-label="Log simulado de leituras"><h2>Log simulado de leituras</h2>{readings.length ? <ol>{readings.map((reading) => <li key={reading.id}><strong>{reading.epc}</strong><p>{reading.room} · {reading.timestamp}</p></li>)}</ol> : <p>Nenhuma leitura simulada nesta sessão.</p>}</section>
    </aside>
  </div>
}
