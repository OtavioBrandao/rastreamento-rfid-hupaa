import { useEffect, useRef, useState } from 'react'
import { labInfrastructure } from '../../config/mapaConfig'
import { Icon } from '../layout/Icon'
import { FloorMap, type MapMarker } from './FloorMap'

interface LabReading { id: number; epc: string; antenna: string; room: string; timestamp: string }
const demoEpcs = ['E2000017221101441890A001', 'E2000017221101441890A002', 'E2000017221101441890A003']

export function MapaLaboratorio() {
  const [readings, setReadings] = useState<LabReading[]>([])
  const [activeAntenna, setActiveAntenna] = useState<string | null>(null)
  const [selected, setSelected] = useState<MapMarker | null>(null)
  const timer = useRef<number | null>(null)
  const serial = useRef(0)
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current) }, [])
  // TODO(API): conectar ao stream de leituras após o backend definir endpoint,
  // autenticação e contrato de eventos. Este botão só gera amostras locais.
  function simulate(antennaId: string) {
    const antenna = labInfrastructure.find((entry) => entry.id === antennaId)
    if (!antenna) return
    const id = ++serial.current
    setReadings((current) => [{ id, epc: demoEpcs[(id - 1) % demoEpcs.length], antenna: antenna.label, room: antenna.room, timestamp: new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date()) }, ...current].slice(0, 20))
    setActiveAntenna(antennaId)
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setActiveAntenna(null), 1700)
  }
  const markers: MapMarker[] = labInfrastructure.map((entry) => ({ id: entry.id, kind: entry.type, x: entry.x, y: entry.y, label: entry.label, detail: entry.room, pulse: activeAntenna === entry.id }))
  return <div className="map-layout lab-layout">
    <div className="map-main"><div className="panel map-control-panel"><div className="map-control-heading"><div><p className="eyebrow">AMBIENTE DE TESTES · EASY</p><h2>Salas A e B</h2></div><span className="demo-tag">simulação local</span></div><p className="map-help">Antenas em vermelho; leitor em azul. O esquema mostra posições percentuais configuráveis.</p></div>
      <FloorMap mode="lab" markers={markers} onMarkerClick={setSelected}/>
      <div className="lab-actions"><div><strong>Simular detecção</strong><p>Use os botões para conferir o feedback visual antes da integração com o leitor físico.</p></div><button type="button" onClick={() => simulate('ANT-A')}><Icon name="antenna"/> Leitura na Sala A</button><button type="button" onClick={() => simulate('ANT-B')}><Icon name="antenna"/> Leitura na Sala B</button></div>
      {selected && <p className="map-footnote" role="status">{selected.label}: {selected.detail}. {selected.kind === 'reader' ? 'Leitor central da divisória.' : 'Use o botão de simulação para gerar uma leitura.'}</p>}
    </div>
    <aside className="map-sidebar"><section className="panel lab-log" aria-labelledby="lab-log-title"><div className="panel-heading"><div><p className="eyebrow">CALIBRAÇÃO</p><h2 id="lab-log-title">Log de leituras</h2></div><span className="log-count">{readings.length}</span></div><p className="map-help">Eventos demonstrativos, mais recentes primeiro. Compare a sala inferida com a posição física da tag.</p>{readings.length ? <ol aria-live="polite">{readings.map((reading) => <li key={reading.id}><div><span className="reading-antenna-icon"><Icon name="antenna" size={16}/></span><strong>{reading.antenna}</strong><time>{reading.timestamp}</time></div><dl><dt>EPC</dt><dd>{reading.epc}</dd><dt>Sala inferida</dt><dd>{reading.room}</dd></dl></li>)}</ol> : <div className="log-empty"><Icon name="antenna" size={26}/><strong>Aguardando simulação</strong><p>Acione uma das antenas para visualizar EPC, sala e horário da detecção.</p></div>}</section><section className="panel lab-legend"><h3>Infraestrutura</h3><p><span className="legend-status legend-antenna"><Icon name="antenna" size={15}/></span> Antena (vermelho)</p><p><span className="legend-status legend-reader"><Icon name="reader" size={15}/></span> Leitor (azul)</p></section></aside>
  </div>
}
