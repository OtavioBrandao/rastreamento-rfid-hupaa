import { hospitalOutlinePath, type MainZone, type MapZone } from '../../config/mapaConfig'
import type { AssetStatus } from '../../types/dashboard'
import { Icon } from '../layout/Icon'

export interface MapMarker {
  id: string
  kind: 'equipment' | 'antenna' | 'reader' | 'portal'
  portalId?: number
  x: number
  y: number
  label: string
  detail: string
  status?: AssetStatus
  dimmed?: boolean
  pulse?: boolean
  pulseKey?: number
}

export function FloorMap({ mode, zones = [], mainZones = [], selectedZoneId = '', showZones = true, markers, onMarkerClick, onZoneClick }: { mode: 'hospital' | 'lab'; zones?: MapZone[]; mainZones?: MainZone[]; selectedZoneId?: string; showZones?: boolean; markers: MapMarker[]; onMarkerClick: (marker: MapMarker) => void; onZoneClick?: (id: string) => void }) {
  const position = (x: number, y: number) => mode === 'hospital'
    ? { left: `${((x + 1.5) / 103) * 100}%`, top: `${((y + 2) / 104) * 100}%` }
    : { left: `${x}%`, top: `${y}%` }

  return <div className={`floor-map floor-map-${mode}`}>
    <svg className="floor-background" viewBox={mode === 'hospital' ? '-1.5 -2 103 104' : '0 0 100 100'} preserveAspectRatio="none" role="img" aria-label={mode === 'hospital' ? 'Esquema do segundo pavimento do HUPAA' : 'Esquema das salas A e B do laboratório EASY'}>
      {mode === 'hospital' ? <>
        <defs><clipPath id="hospital-plan-clip"><path d={hospitalOutlinePath}/></clipPath></defs>
        <rect x="0" y="0" width="100" height="100" fill="#fff"/>
        <g clipPath="url(#hospital-plan-clip)">
          <path d={hospitalOutlinePath} fill="#fff"/>
          <g opacity={showZones ? 1 : 0.08}>{zones.map((area) => <path key={area.id} d={area.path} fill={area.color}/>)}</g>
        </g>
        <path d={hospitalOutlinePath} fill="none" stroke="#1d2329" strokeWidth="1.05" strokeLinejoin="round"/>
      </> : <>
        <rect x="1" y="5" width="98" height="90" rx="1" fill="#fff" stroke="#263a41" strokeWidth="1"/>
        <path d="M50 5 V65 M1 65 H13 M24 65 H88 M94 65 H99" fill="none" stroke="#263a41" strokeWidth="0.9"/>
        <path d="M9 13 V55 M41 13 V55 M59 13 V55 M91 13 V55" stroke="#b6c9c9" strokeWidth="2" strokeLinecap="round"/>
        <rect x="3" y="74" width="7" height="17" rx="1" fill="#eef3f3" stroke="#aebdbf" strokeWidth="0.5"/>
        <rect x="89" y="69" width="7" height="12" rx="1" fill="#eef3f3" stroke="#aebdbf" strokeWidth="0.5"/>
        <text x="25" y="38" className="room-label">SALA A</text><text x="75" y="38" className="room-label">SALA B</text><text x="50" y="88" className="corridor-label">ÁREA COMUM / PORTAL DE TESTES</text>
      </>}
    </svg>
    {mode === 'hospital' && <div className="sector-layer" aria-label="Três zonas principais provisórias">{mainZones.map((zone) => <button key={zone.id} type="button" className={`sector-pin ${selectedZoneId === zone.id ? 'sector-pin-selected' : ''}`} style={position(zone.x, zone.y)} aria-label={`${zone.name}: ${zone.description}`} aria-pressed={selectedZoneId === zone.id} onClick={() => onZoneClick?.(selectedZoneId === zone.id ? '' : zone.id)}>{zone.name}</button>)}</div>}
    <div className="marker-layer">{markers.map((marker) => <button key={`${marker.id}-${marker.pulseKey ?? 0}`} type="button" data-portal-id={marker.portalId} className={`map-marker marker-${marker.kind} ${marker.status ? `marker-${marker.status}` : ''} ${marker.dimmed ? 'marker-dimmed' : ''} ${marker.pulse ? 'marker-pulse' : ''}`} style={position(marker.x, marker.y)} aria-label={`${marker.label}. ${marker.detail}`} title={`${marker.label} — ${marker.detail}`} onClick={() => onMarkerClick(marker)}><Icon name={marker.kind} size={20}/><span className="marker-tooltip"><strong>{marker.label}</strong><small>{marker.detail}</small></span></button>)}</div>
  </div>
}
