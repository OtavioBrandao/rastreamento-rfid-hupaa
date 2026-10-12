import { useEffect, useRef } from 'react'
import type { BoundZone } from '../../services/mapTopology'
import type { EquipmentItem } from '../../types/dashboard'
import { detectionLabel, isFresh } from '../DashboardParts'

export type ClusterTone = 'recente' | 'atencao'

/** Verde: em trânsito ou detectado recentemente. Amarelo: requer atenção ou está desatualizado. */
export function clusterTone(item: EquipmentItem, now = Date.now()): ClusterTone {
  if (item.status === 'atencao') return 'atencao'
  return item.status === 'disponivel' || isFresh(item.ultima_leitura, now) ? 'recente' : 'atencao'
}

function hash(value: string) {
  let h = 2166136261
  for (let i = 0; i < value.length; i++) h = Math.imul(h ^ value.charCodeAt(i), 16777619)
  return (h >>> 0) / 4294967295
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))

// Distribuição em girassol com rotação por zona: espalha sem sobrepor e não representa
// coordenada física, pois o sistema só conhece a zona de presença.
export function clusterPositions(zoneId: string, ids: string[]) {
  const rotation = hash(zoneId) * Math.PI * 2
  const radius = 36
  return ids.map((id, index) => {
    if (ids.length === 1) return { left: 50, top: 50 }
    const r = radius * Math.sqrt((index + 0.5) / ids.length)
    const theta = index * GOLDEN_ANGLE + rotation + (hash(id) - 0.5) * 0.35
    return { left: 50 + r * Math.cos(theta), top: 50 + r * Math.sin(theta) }
  })
}

function dotSize(count: number) {
  return count <= 6 ? 46 : count <= 15 ? 36 : count <= 35 ? 26 : 18
}

export function ZoneCluster({ zone, items, onSelect, onClose }: {
  zone: BoundZone; items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void; onClose: () => void
}) {
  const panel = useRef<HTMLElement>(null)
  useEffect(() => { panel.current?.focus() }, [zone.id])
  const sorted = [...items].sort((a, b) => a.id - b.id)
  const positions = clusterPositions(zone.id, sorted.map((item) => String(item.id)))
  const size = dotSize(sorted.length)
  const recent = sorted.filter((item) => clusterTone(item) === 'recente').length
  return <div className="zone-cluster-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section ref={panel} tabIndex={-1} className="zone-cluster" role="group" aria-label={`Equipamentos em ${zone.name}`}
      onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}>
      <header className="zone-cluster-heading">
        <div><strong>{zone.name}</strong><small>{sorted.length} equipamento{sorted.length === 1 ? '' : 's'} · posição ilustrativa</small></div>
        <button type="button" className="zone-cluster-close" onClick={onClose} aria-label={`Fechar ${zone.name}`}>×</button>
      </header>
      <div className="zone-cluster-circle" style={{ ['--dot-size' as string]: `${size}px` }}>
        {sorted.map((item, index) => {
          const tone = clusterTone(item)
          const toneLabel = tone === 'recente' ? 'Detectado recentemente' : 'Atenção ou desatualizado'
          return <button key={item.id} type="button" className={`zone-dot zone-dot-${tone}`}
            style={{ left: `${positions[index].left}%`, top: `${positions[index].top}%` }}
            aria-label={`${item.nome}. ${toneLabel}. Abrir detalhes`} onClick={() => onSelect(item)}>
            <span className="marker-tooltip"><strong>{item.nome}</strong><small>{toneLabel} · {detectionLabel(item.ultima_deteccao_em)}</small></span>
          </button>
        })}
        {!sorted.length && <p className="zone-cluster-empty">Nenhum equipamento nesta zona agora.</p>}
      </div>
      <ul className="zone-cluster-legend" aria-label="Legenda">
        <li><span className="zone-dot-swatch zone-dot-recente" aria-hidden="true"/>Recente ({recent})</li>
        <li><span className="zone-dot-swatch zone-dot-atencao" aria-hidden="true"/>Atenção ({sorted.length - recent})</li>
      </ul>
    </section>
  </div>
}
