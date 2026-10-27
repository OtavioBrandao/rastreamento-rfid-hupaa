import { useRef, useState, type ReactNode } from 'react'
import { hospitalOutlinePath, type MainZone, type MapZone } from '../../config/mapaConfig'
import type { AssetStatus } from '../../types/dashboard'
import { Icon } from '../layout/Icon'
import { EquipIcon, type TipoSimbolo } from '../simulador/EquipIcon'

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
  /** Nome acessível completo quando o tooltip visual é só uma instrução. */
  ariaLabel?: string
  selected?: boolean
  /** Ícone recolhido da zona: quantidade de equipamentos nela. */
  count?: number
  /** Equipamento individual (zona expandida): símbolo do tipo, marcador menor. */
  symbol?: TipoSimbolo
  /** Lido perto da antena, sem transição: marca tracejada, fora da ocupação da zona. */
  nonConfirmed?: boolean
  /** Visada da antena em graus da tela (seta); ausente = sem direção. */
  rotation?: number | null
}

/** Modo simplificado da planta: corredor preto, áreas verdes em cinza, demais em branco. */
const COR_CORREDOR = '#67008F'
const COR_VERDE = '#00E820'
export function corSimplificada(cor: string) {
  const valor = cor.toUpperCase()
  return valor === COR_CORREDOR ? '#111111' : valor === COR_VERDE ? '#9aa0a6' : '#ffffff'
}
/** Arrastar menos que isto (px) ainda é clique: abre a zona. */
const LIMIAR_ARRASTE = 5

export function FloorMap({ mode, zones = [], mainZones = [], selectedZoneId = '', showZones = true, markers, onMarkerClick, onZoneClick, onBackgroundClick, overlay, svgExtras, simplified = false, onZoneLabelMove }: {
  mode: 'hospital' | 'lab'; zones?: MapZone[]; mainZones?: MainZone[]; selectedZoneId?: string; showZones?: boolean; markers: MapMarker[]
  onMarkerClick: (marker: MapMarker) => void; onZoneClick?: (id: string) => void; onBackgroundClick?: () => void; overlay?: ReactNode
  /** Desenho extra no sistema de coordenadas da planta (0–100): limites de zonas, cobertura. */
  svgExtras?: ReactNode
  /** Planta sem as cores de uso das áreas (ver `corSimplificada`). */
  simplified?: boolean
  /** Com esta função, o nome da zona pode ser arrastado; recebe a posição na planta (0–100). */
  onZoneLabelMove?: (id: string, x: number, y: number) => void
}) {
  const position = (x: number, y: number) => mode === 'hospital'
    ? { left: `${((x + 1.5) / 103) * 100}%`, top: `${((y + 2) / 104) * 100}%` }
    : { left: `${x}%`, top: `${y}%` }
  const mapRef = useRef<HTMLDivElement>(null)
  const arraste = useRef<{ id: string; px: number; py: number; moveu: boolean; x: number; y: number } | null>(null)
  const ignorarClique = useRef(false)
  const [arrastando, setArrastando] = useState<{ id: string; x: number; y: number } | null>(null)
  const naPlanta = (clientX: number, clientY: number) => {
    const rect = mapRef.current!.getBoundingClientRect()
    const limitar = (valor: number) => Math.round(Math.min(100, Math.max(0, valor)) * 100) / 100
    return { x: limitar(((clientX - rect.left) / rect.width) * 103 - 1.5), y: limitar(((clientY - rect.top) / rect.height) * 104 - 2) }
  }

  return <div ref={mapRef} className={`floor-map floor-map-${mode}${simplified ? ' floor-map-simplificado' : ''}`} onClick={(event) => { if (event.target === event.currentTarget || (event.target as Element).closest('.floor-background')) onBackgroundClick?.() }}>
    <svg className="floor-background" viewBox={mode === 'hospital' ? '-1.5 -2 103 104' : '0 0 100 100'} preserveAspectRatio="none" role="img" aria-label={mode === 'hospital' ? 'Esquema do segundo pavimento do HUPAA' : 'Esquema das salas A e B do laboratório EASY'}>
      {mode === 'hospital' ? <>
        <defs><clipPath id="hospital-plan-clip"><path d={hospitalOutlinePath}/></clipPath></defs>
        <rect x="0" y="0" width="100" height="100" fill="#fff"/>
        <g clipPath="url(#hospital-plan-clip)">
          <path d={hospitalOutlinePath} fill="#fff"/>
          <g opacity={showZones ? 1 : 0.08}>{zones.map((area) => <path key={area.id} d={area.path} fill={simplified ? corSimplificada(area.color) : area.color}/>)}</g>
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
      {svgExtras}
    </svg>
    {mode === 'lab' && <div className="room-layer">{mainZones.filter((zone) => zone.area).map((zone) => <button key={zone.id} type="button" className={`room-hit ${selectedZoneId === zone.id ? 'room-hit-selected' : ''}`} style={{ left: `${zone.area!.x}%`, top: `${zone.area!.y}%`, width: `${zone.area!.width}%`, height: `${zone.area!.height}%` }} aria-label={`${zone.name}: clique para ver os equipamentos`} title="Clique para ver os equipamentos" aria-pressed={selectedZoneId === zone.id} onClick={() => onZoneClick?.(zone.id)}/>)}</div>}
    {mode === 'hospital' && <div className="sector-layer" aria-label="Zonas do HU">{mainZones.map((zone) => {
      const lugar = arrastando?.id === zone.id ? arrastando : zone
      return <button key={zone.id} type="button" className={`sector-pin ${selectedZoneId === zone.id ? 'sector-pin-selected' : ''}${onZoneLabelMove ? ' sector-pin-movel' : ''}${arrastando?.id === zone.id ? ' sector-pin-arrastando' : ''}`}
        style={position(lugar.x, lugar.y)} aria-label={`${zone.name}: ${zone.description}`} title={onZoneLabelMove ? 'Clique para ver os equipamentos; arraste para mover o nome' : 'Clique para ver os equipamentos'} aria-pressed={selectedZoneId === zone.id}
        onPointerDown={onZoneLabelMove ? (event) => {
          arraste.current = { id: zone.id, px: event.clientX, py: event.clientY, moveu: false, x: zone.x, y: zone.y }
          event.currentTarget.setPointerCapture?.(event.pointerId)
        } : undefined}
        onPointerMove={onZoneLabelMove ? (event) => {
          const atual = arraste.current
          if (!atual || atual.id !== zone.id) return
          if (!atual.moveu && Math.hypot(event.clientX - atual.px, event.clientY - atual.py) < LIMIAR_ARRASTE) return
          atual.moveu = true
          Object.assign(atual, naPlanta(event.clientX, event.clientY))
          setArrastando({ id: zone.id, x: atual.x, y: atual.y })
        } : undefined}
        onPointerUp={onZoneLabelMove ? () => {
          const atual = arraste.current
          arraste.current = null
          setArrastando(null)
          if (atual?.moveu) { ignorarClique.current = true; onZoneLabelMove(zone.id, atual.x, atual.y) }
        } : undefined}
        onPointerCancel={() => { arraste.current = null; setArrastando(null) }}
        onClick={(event) => {
          // Soltar depois de arrastar não é clique: não expande a zona.
          if (ignorarClique.current) { ignorarClique.current = false; event.preventDefault(); return }
          onZoneClick?.(zone.id)
        }}>{zone.name}</button>
    })}</div>}
    <div className="marker-layer">{markers.map((marker) => <button key={`${marker.id}-${marker.pulseKey ?? 0}`} type="button" data-portal-id={marker.portalId} data-zone-member={marker.symbol || marker.count !== undefined ? '' : undefined}
      className={`map-marker marker-${marker.kind} ${marker.status ? `marker-${marker.status}` : ''} ${marker.dimmed ? 'marker-dimmed' : ''} ${marker.pulse ? 'marker-pulse' : ''} ${marker.selected ? 'marker-selected' : ''} ${marker.symbol ? 'marker-individual' : ''} ${marker.count !== undefined ? 'marker-collapsed' : ''} ${marker.nonConfirmed ? 'marker-nao-confirmado' : ''}`}
      style={position(marker.x, marker.y)} aria-label={marker.ariaLabel ?? `${marker.label}. ${marker.detail}`} aria-pressed={marker.selected === undefined ? undefined : marker.selected}
      aria-expanded={marker.count !== undefined ? !!marker.selected : undefined} onClick={(event) => { event.stopPropagation(); onMarkerClick(marker) }}>
      {marker.symbol ? <EquipIcon tipo={marker.symbol} size={13}/>
        : <span className="marker-icon" style={marker.rotation === null || marker.rotation === undefined ? undefined : { transform: `rotate(${marker.rotation}deg)` }}><Icon name={marker.kind} size={20}/></span>}
      {marker.count !== undefined && <span className="marker-count" aria-hidden="true">{marker.count}</span>}
      <span className="marker-tooltip"><strong>{marker.label}</strong>{marker.detail && <small>{marker.detail}</small>}</span></button>)}</div>
    {overlay}
  </div>
}
