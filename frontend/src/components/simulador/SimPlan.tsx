import { forwardRef, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { hospitalContextAreas, hospitalOutlinePath } from '../../config/mapaConfig'
import type { LayoutConfig, Ponto } from '../../services/simulacao'

/** Converte a posição do ponteiro em coordenadas normalizadas 0–100 da planta. */
export function pointFromEvent(element: HTMLElement | null, event: { clientX: number; clientY: number }): Ponto {
  const rect = element?.getBoundingClientRect()
  if (!rect || !rect.width || !rect.height) return { x: 50, y: 50 }
  const clamp = (value: number) => Math.round(Math.min(100, Math.max(0, value)) * 10) / 10
  return { x: clamp(((event.clientX - rect.left) / rect.width) * 100), y: clamp(((event.clientY - rect.top) / rect.height) * 100) }
}

export const at = (point: Ponto) => ({ left: `${point.x}%`, top: `${point.y}%` })

export interface PlanOptions {
  /** Destaques por chave de antena (tag lida agora). */
  activeAntennas?: Set<string>
  selected?: string | null
  showCoverage?: boolean
  showHardware?: boolean
}

/** Planta de fundo + zonas + alcance; marcadores e itens entram como filhos. */
export const SimPlan = forwardRef<HTMLDivElement, {
  layout: LayoutConfig
  options?: PlanOptions
  children?: ReactNode
  onPointerDown?: (event: ReactPointerEvent<HTMLDivElement>) => void
  onPointerMove?: (event: ReactPointerEvent<HTMLDivElement>) => void
  onPointerUp?: (event: ReactPointerEvent<HTMLDivElement>) => void
  className?: string
  label: string
}>(function SimPlan({ layout, options = {}, children, onPointerDown, onPointerMove, onPointerUp, className = '', label }, ref) {
  const { activeAntennas, selected, showCoverage = true, showHardware = true } = options
  const p = layout.proporcao
  return <div ref={ref} className={`sim-plan sim-plan-${layout.cenario} ${className}`} style={{ aspectRatio: String(p) }}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
    <svg className="sim-plan-bg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={label}>
      {layout.cenario === 'hupaa' ? <>
        <defs><clipPath id="sim-hospital-clip"><path d={hospitalOutlinePath}/></clipPath></defs>
        <rect x="0" y="0" width="100" height="100" fill="#fbfcfd"/>
        <g clipPath="url(#sim-hospital-clip)"><path d={hospitalOutlinePath} fill="#fff"/>
          <g opacity="0.16">{hospitalContextAreas.map((area) => <path key={area.id} d={area.path} fill={area.color}/>)}</g></g>
        <path d={hospitalOutlinePath} fill="none" stroke="#1d2329" strokeWidth="0.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round"/>
      </> : <>
        <rect x="1" y="5" width="98" height="90" rx="1" fill="#fff" stroke="#263a41" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
        <path d="M50 5 V65 M1 65 H13 M24 65 H88 M94 65 H99" fill="none" stroke="#263a41" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
        <path d="M9 13 V55 M41 13 V55 M59 13 V55 M91 13 V55" stroke="#b6c9c9" strokeWidth="5" vectorEffect="non-scaling-stroke" strokeLinecap="round"/>
      </>}
      {layout.zonas.map((zona) => zona.area && <rect key={zona.chave} x={zona.area.x} y={zona.area.y} width={zona.area.largura} height={zona.area.altura}
        fill={zona.cor} fillOpacity={selected === zona.chave ? 0.28 : 0.14} stroke={zona.cor} strokeWidth={selected === zona.chave ? 3 : 1.5}
        strokeDasharray={zona.restrita ? '6 4' : undefined} vectorEffect="non-scaling-stroke"/>)}
      {showHardware && layout.leitores.map((leitor) => leitor.posicao && leitor.antenas.map((antena) => antena.posicao &&
        <line key={`cabo-${antena.chave}`} x1={leitor.posicao!.x} y1={leitor.posicao!.y} x2={antena.posicao.x} y2={antena.posicao.y}
          stroke="#365fc4" strokeOpacity="0.35" strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke"/>))}
      {showCoverage && layout.leitores.flatMap((leitor) => leitor.antenas).map((antena) => antena.posicao &&
        <ellipse key={`alcance-${antena.chave}`} className={activeAntennas?.has(antena.chave) ? 'sim-coverage sim-coverage-active' : 'sim-coverage'}
          cx={antena.posicao.x} cy={antena.posicao.y} rx={antena.alcance} ry={antena.alcance * p} vectorEffect="non-scaling-stroke"/>)}
    </svg>
    {layout.zonas.map((zona) => zona.area && <span key={`rotulo-${zona.chave}`} className="sim-zone-label" style={{ ...at({ x: zona.area.x, y: zona.area.y }), color: zona.cor }}>{zona.nome}{zona.restrita ? ' · restrita' : ''}</span>)}
    {children}
  </div>
})
