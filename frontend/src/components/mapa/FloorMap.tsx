import type { MapZone } from '../../config/mapaConfig'
import type { OperationalStatus } from '../../types/dashboard'
import { Icon } from '../layout/Icon'

export interface MapMarker {
  id: string
  kind: 'equipment' | 'antenna' | 'reader'
  x: number
  y: number
  label: string
  detail: string
  status?: OperationalStatus
  dimmed?: boolean
  pulse?: boolean
}

export function FloorMap({ mode, zones = [], showZones = true, markers, onMarkerClick }: { mode: 'hospital' | 'lab'; zones?: MapZone[]; showZones?: boolean; markers: MapMarker[]; onMarkerClick: (marker: MapMarker) => void }) {
  return <div className={`floor-map floor-map-${mode}`}>
    <svg className="floor-background" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={mode === 'hospital' ? 'Esquema do segundo pavimento do HUPAA' : 'Esquema das salas A e B do laboratório EASY'}>
      {mode === 'hospital' ? <>
        <rect x="0" y="0" width="100" height="100" fill="#f8faf9"/>
        <g opacity={showZones ? 1 : 0.12}>{zones.map((zone) => <path key={zone.id} d={zone.path} fill={zone.color} stroke="#fff" strokeWidth="0.45"/>)}</g>
        <path d="M8 8 H92 V56 H61 V94 H8 V74 H3 V38 H8 Z" fill="none" stroke="#415d62" strokeWidth="0.8"/>
        <text x="12" y="23">2º PAVIMENTO · HUPAA</text><text x="66" y="89">ESQUEMA DE ZONAS</text>
      </> : <>
        <rect x="1" y="5" width="98" height="90" rx="1" fill="#fff" stroke="#263a41" strokeWidth="1"/>
        <path d="M50 5 V65 M1 65 H13 M24 65 H88 M94 65 H99" fill="none" stroke="#263a41" strokeWidth="0.9"/>
        <path d="M9 13 V55 M41 13 V55 M59 13 V55 M91 13 V55" stroke="#b6c9c9" strokeWidth="2" strokeLinecap="round"/>
        <rect x="3" y="74" width="7" height="17" rx="1" fill="#eef3f3" stroke="#aebdbf" strokeWidth="0.5"/>
        <rect x="89" y="69" width="7" height="12" rx="1" fill="#eef3f3" stroke="#aebdbf" strokeWidth="0.5"/>
        <text x="25" y="38" className="room-label">SALA A</text><text x="75" y="38" className="room-label">SALA B</text><text x="50" y="88" className="corridor-label">ÁREA COMUM / PORTAL DE TESTES</text>
      </>}
    </svg>
    <div className="marker-layer">{markers.map((marker) => <button key={marker.id} type="button" className={`map-marker marker-${marker.kind} ${marker.status ? `marker-${marker.status}` : ''} ${marker.dimmed ? 'marker-dimmed' : ''} ${marker.pulse ? 'marker-pulse' : ''}`} style={{ left: `${marker.x}%`, top: `${marker.y}%` }} aria-label={`${marker.label}. ${marker.detail}`} title={`${marker.label} — ${marker.detail}`} onClick={() => onMarkerClick(marker)}><Icon name={marker.kind} size={20}/><span className="marker-tooltip"><strong>{marker.label}</strong><small>{marker.detail}</small></span></button>)}</div>
  </div>
}
