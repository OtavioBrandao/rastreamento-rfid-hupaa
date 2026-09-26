import { useEffect, useState, type FormEvent } from 'react'
import { MapaHospital } from '../components/mapa/MapaHospital'
import { MapaLaboratorio } from '../components/mapa/MapaLaboratorio'
import { getAllAssets } from '../services/dashboard'
import type { EquipmentItem } from '../types/dashboard'

export function MapPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [mode, setMode] = useState<'hospital' | 'lab'>('hospital')
  const [draftEpc, setDraftEpc] = useState('')
  const [epc, setEpc] = useState('')
  const [items, setItems] = useState<EquipmentItem[]>([])
  const [phase, setPhase] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [errorMessage, setErrorMessage] = useState('Não foi possível carregar o mapa.')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setPhase('loading')
    getAllAssets(epc ? { epc } : {}, controller.signal).then((result) => { setItems(result); setPhase('loaded') })
      .catch((error) => { if (error.name !== 'AbortError') {
        setErrorMessage(String(error.message).includes('422') ? 'Confira o EPC informado.' : 'Não foi possível carregar o mapa.')
        setPhase('error')
      } })
    return () => controller.abort()
  }, [epc, retry])
  function submit(event: FormEvent) { event.preventDefault(); setEpc(draftEpc.trim()) }
  return <div className="map-page">
    <div className="page-heading"><div><p className="eyebrow">VISUALIZAÇÃO ESPACIAL</p><h1>Mapa / Planta</h1><p className="lead">Última zona conhecida, sem posição exata do equipamento.</p></div></div>
    <form className="panel asset-filters" role="search" onSubmit={submit}><label>Consultar EPC<input type="search" maxLength={32} value={draftEpc} onChange={(e) => setDraftEpc(e.target.value)} placeholder="EPC exato"/></label><button type="submit">Buscar tag</button>{epc && <button type="button" onClick={() => { setEpc(''); setDraftEpc('') }}>Limpar</button>}</form>
    <div className="map-tabs" role="tablist" aria-label="Modo do mapa"><button id="tab-hospital" type="button" role="tab" aria-selected={mode === 'hospital'} aria-controls="panel-hospital" onClick={() => setMode('hospital')}>Mapa do Hospital (HUPAA)</button><button id="tab-lab" type="button" role="tab" aria-selected={mode === 'lab'} aria-controls="panel-lab" onClick={() => setMode('lab')}>Laboratório de Testes (EASY)</button></div>
    {phase === 'loading' && <div className="panel map-skeleton" role="status" aria-label="Carregando mapa"><span/><span/></div>}
    {phase === 'error' && <div className="state-panel error-panel" role="alert"><h2>{errorMessage}</h2><button type="button" onClick={() => setRetry((value) => value + 1)}>Tentar novamente</button></div>}
    {phase === 'loaded' && <>{epc && items.length === 0 && <p role="status">Nenhum ativo associado a este EPC.</p>}{mode === 'hospital' ? <div id="panel-hospital" role="tabpanel" aria-labelledby="tab-hospital"><MapaHospital items={items} onSelect={onSelect}/></div> : <div id="panel-lab" role="tabpanel" aria-labelledby="tab-lab"><MapaLaboratorio items={items} onSelect={onSelect}/></div>}</>}
  </div>
}
