import type { PointerEvent as ReactPointerEvent } from 'react'
import { nomeDirecao, type AntenaLayout, type LeitorLayout, type Ponto, type PortalLayout } from '../../services/simulacao'
import { at } from './SimPlan'

type Tipo = 'leitor' | 'antena' | 'portal'

/** Ponto pequeno na planta; detalhes no tooltip (hover ou foco). A área de clique é maior que o desenho. */
export function Marcador({ tipo, posicao, titulo, linhas, rotulo, selecionado, lendo, restrito, orientacao, estatico, onPointerDown, onClick }: {
  tipo: Tipo; posicao: Ponto; titulo: string; linhas: string[]; rotulo?: string | null
  selecionado?: boolean; lendo?: boolean; restrito?: boolean; orientacao?: number | null; estatico?: boolean
  onPointerDown?: (event: ReactPointerEvent) => void; onClick?: () => void
}) {
  const classes = ['sim-dot', `sim-dot-${tipo}`, selecionado && 'selected', lendo && 'reading', restrito && 'restrita', estatico && 'static'].filter(Boolean).join(' ')
  const descricao = [titulo, ...linhas].join(' · ')
  const conteudo = <>
    <span className="sim-dot-shape" aria-hidden="true">
      {tipo === 'antena' && orientacao !== null && orientacao !== undefined && <span className="sim-dot-arrow" style={{ transform: `rotate(${orientacao}deg)` }}/>}
    </span>
    {rotulo && <span className="sim-dot-label" aria-hidden="true">{rotulo}</span>}
    <span className="sim-tip" role="tooltip"><strong>{titulo}</strong>{linhas.map((linha) => <span key={linha}>{linha}</span>)}</span>
  </>
  if (estatico) return <span className={classes} style={at(posicao)} tabIndex={0} aria-label={descricao}>{conteudo}</span>
  return <button type="button" className={classes} style={at(posicao)} aria-label={descricao} aria-pressed={selecionado}
    onPointerDown={onPointerDown} onClick={onClick}>{conteudo}</button>
}

const MODELO: Record<string, string> = { EZ700: 'Identix EZ700', DR_MAX: 'Identix DR Max (virtual)' }

export function linhasLeitor(leitor: LeitorLayout) {
  return [`${MODELO[leitor.modelo] ?? leitor.modelo} · ${leitor.reader_id}`, `${leitor.antenas.length} antena(s)`,
    ...(leitor.alerta_area_restrita ? ['Alerta de área restrita'] : [])]
}

export function linhasAntena(leitor: LeitorLayout, antena: AntenaLayout, portais: PortalLayout[]) {
  const portal = portais.find((item) => item.chave === antena.portal)
  return [`${leitor.nome} (${MODELO[leitor.modelo] ?? leitor.modelo}) · porta ${antena.porta}`,
    `Visada: ${nomeDirecao(antena.orientacao)}`,
    `Alcance ${antena.alcance}${antena.orientacao !== null && antena.orientacao !== undefined ? ` na frente, ${Math.round(antena.alcance * (antena.fator_traseiro ?? 0.35) * 10) / 10} atrás` : ''}`,
    portal ? `Portal ${portal.nome} · lado ${(antena.lado ?? '?').toUpperCase()}` : 'Sem portal (presença na zona)']
}
