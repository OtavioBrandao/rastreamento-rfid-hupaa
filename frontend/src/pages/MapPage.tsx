import { useState } from 'react'
import { MapaHospital } from '../components/mapa/MapaHospital'
import { MapaLaboratorio } from '../components/mapa/MapaLaboratorio'
import type { EquipmentItem } from '../types/dashboard'

export function MapPage({ onSelect }: { onSelect: (item: EquipmentItem) => void }) {
  const [mode, setMode] = useState<'hospital' | 'lab'>('hospital')
  return <div className="map-page">
    <div className="page-heading"><div><p className="eyebrow">VISUALIZAÇÃO ESPACIAL</p><h1>Mapa / Planta</h1><p className="lead">Explore as três zonas principais provisórias do 2º pavimento ou acompanhe os testes no laboratório.</p></div><span className="demo-pill">Ambiente demonstrativo</span></div>
    <div className="map-tabs" role="tablist" aria-label="Modo do mapa"><button id="tab-hospital" type="button" role="tab" aria-selected={mode === 'hospital'} aria-controls="panel-hospital" onClick={() => setMode('hospital')}>Mapa do Hospital (HUPAA)</button><button id="tab-lab" type="button" role="tab" aria-selected={mode === 'lab'} aria-controls="panel-lab" onClick={() => setMode('lab')}>Laboratório de Testes (EASY)</button></div>
    {mode === 'hospital' ? <div id="panel-hospital" role="tabpanel" aria-labelledby="tab-hospital"><MapaHospital onSelect={onSelect}/></div> : <div id="panel-lab" role="tabpanel" aria-labelledby="tab-lab"><MapaLaboratorio/></div>}
  </div>
}
