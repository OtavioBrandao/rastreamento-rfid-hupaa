import { useState, type FormEvent } from 'react'
import { MapaHospital } from '../components/mapa/MapaHospital'
import { MapaLaboratorio } from '../components/mapa/MapaLaboratorio'
import { RegisteredDetections } from '../components/mapa/RegisteredDetections'
import { getAllAssets, getMapTopology } from '../services/dashboard'
import { emptyTopology } from '../services/mapTopology'
import { useLiveQuery } from '../services/live'
import type { EquipmentItem } from '../types/dashboard'

export function MapPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [mode, setMode] = useState<'hospital' | 'lab'>('hospital')
  const [draftEpc, setDraftEpc] = useState('')
  const [epc, setEpc] = useState('')
  const assets = useLiveQuery(`map-assets:${epc}`, (signal) => getAllAssets(epc ? { epc } : {}, signal))
  const metadata = useLiveQuery('map-topology', getMapTopology)
  const items = assets.data ?? []
  const topology = metadata.error ? emptyTopology : metadata.data ?? emptyTopology
  const topologyError = metadata.error
  const phase = assets.loading ? 'loading' : !assets.data && assets.error ? 'error' : 'loaded'
  const errorMessage = String(assets.error).includes('422') ? 'Confira o EPC informado.' : 'Não foi possível carregar o mapa.'
  const refreshError = assets.data && assets.error
  const detections = <RegisteredDetections items={items} onSelect={onSelect}/>
  function submit(event: FormEvent) { event.preventDefault(); setEpc(draftEpc.trim()) }
  return <div className="map-page">
    <div className="page-heading"><div><p className="eyebrow">VISUALIZAÇÃO ESPACIAL</p><h1>Mapa / Planta</h1><p className="lead">Última zona conhecida, sem posição exata do equipamento.</p></div></div>
    <form className="panel asset-filters" role="search" onSubmit={submit}><label>Consultar EPC<input type="search" maxLength={32} value={draftEpc} onChange={(e) => setDraftEpc(e.target.value)} placeholder="EPC exato"/></label><button type="submit">Buscar tag</button>{epc && <button type="button" onClick={() => { setEpc(''); setDraftEpc('') }}>Limpar</button>}</form>
    <div className="map-tabs" role="tablist" aria-label="Modo do mapa"><button id="tab-hospital" type="button" role="tab" aria-selected={mode === 'hospital'} aria-controls="panel-hospital" onClick={() => setMode('hospital')}>Mapa do Hospital (HUPAA)</button><button id="tab-lab" type="button" role="tab" aria-selected={mode === 'lab'} aria-controls="panel-lab" onClick={() => setMode('lab')}>Laboratório de Testes (EASY)</button></div>
    {topologyError && <p role="alert">Não foi possível validar as zonas e portais da planta. Consulte a lista textual; tentando novamente...</p>}
    {phase === 'loading' && <div className="panel map-skeleton" role="status" aria-label="Carregando mapa"><span/><span/></div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>{errorMessage}</h2>Tentando novamente automaticamente.</div>}
    {phase === 'loaded' && <>{refreshError && <p role="alert">Não foi possível atualizar as posições. Tentando novamente...</p>}{epc && items.length === 0 && <p role="status">Nenhum ativo associado a este EPC.</p>}{mode === 'hospital' ? <div id="panel-hospital" role="tabpanel" aria-labelledby="tab-hospital"><MapaHospital topology={topology} items={items} onSelect={onSelect} footer={detections}/></div> : <div id="panel-lab" role="tabpanel" aria-labelledby="tab-lab"><MapaLaboratorio topology={topology} items={items} epc={epc} onSelect={onSelect} footer={detections}/></div>}</>}
  </div>
}
