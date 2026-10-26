import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ageLabel } from '../DashboardParts'
import { EquipIcon, simboloDoTipo } from '../simulador/EquipIcon'
import { TimeControls, useSimClock } from '../simulador/RelogioSimulacao'
import { at, PlanLegend, SimPlan } from '../simulador/SimPlan'
import {
  getMonitor, getSession, getSessions,
  type EquipamentoAoVivo, type EstadoAoVivo, type LayoutConfig, type Monitor, type Ponto, type Sessao, type SessaoResumo,
} from '../../services/simulacao'
import type { EquipmentItem } from '../../types/dashboard'

const MONITOR_MS = 1000
const SESSAO_MS = 5000
const PULSO_MS = 2500
const MAX_EVENTOS = 40

/** Cor e prioridade: o primeiro estado que se aplica decide a cor; os demais ficam nos detalhes. */
export const ESTADOS: Record<EstadoAoVivo, { rotulo: string; descricao: string }> = {
  fora_de_servico: { rotulo: 'Fora de serviço', descricao: 'Inativo no cadastro' },
  em_transito: { rotulo: 'Em trânsito', descricao: 'Lido num portal, passagem ainda não confirmada' },
  atencao: { rotulo: 'Atenção', descricao: 'Sem detecção confirmada além do limite' },
  detectado: { rotulo: 'Detectado agora', descricao: 'Lido agora na zona confirmada' },
  confirmado: { rotulo: 'Passagem confirmada', descricao: 'Zona confirmada pelo sistema' },
  sem_confirmacao: { rotulo: 'Sem passagem confirmada', descricao: 'Lido, mas nenhuma zona confirmada' },
  nunca_detectado: { rotulo: 'Nunca detectado', descricao: 'Sem leitura nesta sessão' },
}
const ORDEM = Object.keys(ESTADOS) as EstadoAoVivo[]

type Evento = { id: string; em: number; texto: string; tom: 'info' | 'ok' | 'aviso' | 'alerta' }

const hora = (ms: number) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const nomeDe = (item: EquipamentoAoVivo) => item.equipamento?.nome ?? `Tag …${item.epc.slice(-4)} (não cadastrada)`

/** Distribuição em girassol dentro da área da zona: não indica posição física. */
function dentroDaZona(layout: LayoutConfig, chave: string, indice: number, total: number): Ponto | null {
  const area = layout.zonas.find((zona) => zona.chave === chave)?.area
  if (!area) return null
  const cx = area.x + area.largura / 2, cy = area.y + area.altura / 2
  if (total === 1) return { x: cx, y: cy }
  const r = Math.sqrt((indice + 0.5) / total)
  const theta = indice * Math.PI * (3 - Math.sqrt(5))
  return { x: cx + area.largura * 0.36 * r * Math.cos(theta), y: cy + area.altura * 0.36 * r * Math.sin(theta) }
}

function perto(ponto: Ponto, indice: number): Ponto {
  const angulo = indice * 2.4 + 0.6
  return { x: ponto.x + Math.cos(angulo) * 1.8, y: ponto.y + Math.sin(angulo) * 3.2 }
}

/** Mapa operacional do HU: a planta e os leitores/antenas da configuração salva, com o que o sistema confirmou. */
export function MapaHUAoVivo({ items, onSelect, canControlTime, fallback }: {
  items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void; canControlTime: boolean; fallback: ReactNode
}) {
  const clock = useSimClock()
  const [resumo, setResumo] = useState<SessaoResumo | null | undefined>(undefined)
  const [sessao, setSessao] = useState<Sessao | null>(null)
  const [monitor, setMonitor] = useState<Monitor | null>(null)
  const [falha, setFalha] = useState(false)
  const [zona, setZona] = useState<string | null>(null)
  const [cobertura, setCobertura] = useState(false)
  const [eventos, setEventos] = useState<Evento[]>([])
  const anterior = useRef<{ estados: Map<string, EquipamentoAoVivo>; passagens: Set<number>; alertas: Set<string> } | null>(null)

  useEffect(() => {
    let vivo = true
    const buscar = () => getSessions().then((lista) => {
      if (!vivo) return
      const hu = lista.filter((item) => item.cenario === 'hupaa').sort((a, b) => b.iniciada_em.localeCompare(a.iniciada_em))[0] ?? null
      setResumo(hu)
    }).catch(() => { if (vivo) setResumo(null) })
    buscar()
    const timer = window.setInterval(buscar, SESSAO_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [])

  const codigo = resumo?.codigo
  useEffect(() => {
    if (!codigo) { setSessao(null); setMonitor(null); anterior.current = null; return }
    let vivo = true
    getSession(codigo).then((dados) => { if (vivo && !('inalterada' in dados)) setSessao(dados) }).catch(() => undefined)
    const buscar = () => getMonitor(codigo).then((dados) => { if (vivo) { setMonitor(dados); setFalha(false) } }).catch(() => { if (vivo) setFalha(true) })
    buscar()
    const timer = window.setInterval(buscar, MONITOR_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [codigo, resumo?.versao])

  const layout = sessao?.layout
  const nomeZona = useMemo(() => new Map(layout?.zonas.map((z) => [z.chave, z.nome]) ?? []), [layout])
  const nomePortal = useMemo(() => new Map(layout?.portais.map((p) => [p.chave, p.nome]) ?? []), [layout])

  // Linha do tempo: diferenças entre consultas sucessivas do que o pipeline gravou.
  useEffect(() => {
    if (!monitor) return
    const estados = new Map((monitor.equipamentos ?? []).map((item) => [item.epc, item]))
    const passagens = new Set(monitor.passagens.map((item) => item.id))
    const alertas = new Set((monitor.alertas_restritos ?? []).filter((item) => item.recente).map((item) => `${item.epc}-${item.antena}`))
    const antes = anterior.current
    anterior.current = { estados, passagens, alertas }
    const agora = Date.parse(monitor.gerado_em)
    const novos: Evento[] = []
    const passagensNovas = antes ? monitor.passagens.filter((p) => !antes.passagens.has(p.id)) : monitor.passagens.slice(0, 8)
    for (const p of [...passagensNovas].reverse()) {
      const nome = p.equipamento ?? `Tag …${p.epc.slice(-4)}`
      novos.push(p.direcao_status === 'confirmed'
        ? { id: `p${p.id}`, em: Date.parse(p.detectada_em), tom: 'ok', texto: `${nome}: saiu de ${p.zona_origem} e entrou em ${p.zona_destino} (${p.portal}) · passagem confirmada` }
        : { id: `p${p.id}`, em: Date.parse(p.detectada_em), tom: 'aviso', texto: `${nome}: passagem em ${p.portal} sem direção confirmada` })
    }
    if (antes) {
      for (const [epc, item] of estados) {
        const velho = antes.estados.get(epc)
        if (velho?.estado === item.estado) continue
        const nome = nomeDe(item)
        if (item.estado === 'em_transito') novos.push({ id: `t${epc}${agora}`, em: agora, tom: 'info', texto: `${nome}: detectado no portal ${nomePortal.get(item.portal ?? '') ?? ''} (${nomeZona.get(item.zona_leitura ?? '') ?? 'lado'}), aguardando confirmação` })
        else if (item.estado === 'atencao') novos.push({ id: `a${epc}${agora}`, em: agora, tom: 'aviso', texto: `${nome}: tempo excessivo sem detecção — atenção` })
        else if (item.estado === 'detectado' && velho && velho.estado !== 'em_transito') novos.push({ id: `d${epc}${agora}`, em: agora, tom: 'info', texto: `${nome}: detectado em ${nomeZona.get(item.zona_leitura ?? '') ?? 'zona'}` })
        else if (item.estado === 'fora_de_servico') novos.push({ id: `f${epc}${agora}`, em: agora, tom: 'aviso', texto: `${nome}: fora de serviço` })
      }
    }
    for (const alerta of monitor.alertas_restritos ?? []) {
      const chave = `${alerta.epc}-${alerta.antena}`
      if (alerta.recente && !antes?.alertas.has(chave)) novos.push({ id: `r${chave}${agora}`, em: Date.parse(alerta.ultima_leitura_em), tom: 'alerta', texto: `ALERTA: ${alerta.equipamento?.nome ?? `Tag …${alerta.epc.slice(-4)}`} na área restrita (${alerta.zona})` })
    }
    if (novos.length) setEventos((velhos) => [...novos.reverse(), ...velhos].slice(0, MAX_EVENTOS))
  }, [monitor, nomeZona, nomePortal])

  const [, tick] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => tick((n) => n + 1), 500); return () => window.clearInterval(timer) }, [])

  if (resumo === undefined) return <div className="panel map-skeleton" role="status" aria-label="Carregando mapa do HU"><span/><span/></div>
  if (!resumo || !layout) return <>{resumo === null && <p className="map-help" role="note">Nenhuma simulação do HU em execução: mostrando a planta de referência. Inicie a simulação no <a href="#/simulador">Simulador</a> para acompanhar o HU ao vivo.</p>}{fallback}</>

  const agora = clock.agora()
  const equipamentos = monitor?.equipamentos ?? []
  const pulsando = new Set((monitor?.leituras ?? []).filter((l) => l.antena && agora - Date.parse(l.lido_em) <= PULSO_MS).map((l) => l.antena!))
  const posicoes = new Map<string, Ponto>()
  const porAncora = new Map<string, EquipamentoAoVivo[]>()
  for (const item of equipamentos) {
    const ancora = (item.estado === 'em_transito' || (item.estado === 'sem_confirmacao' && item.antena)) ? `antena:${item.antena}` : item.zona_confirmada ? `zona:${item.zona_confirmada}` : null
    if (ancora) porAncora.set(ancora, [...(porAncora.get(ancora) ?? []), item])
  }
  const antenas = new Map(layout.leitores.flatMap((leitor) => leitor.antenas.map((antena) => [antena.chave, antena])))
  for (const [ancora, grupo] of porAncora) grupo.forEach((item, indice) => {
    const [tipo, chave] = ancora.split(':')
    const ponto = tipo === 'zona' ? dentroDaZona(layout, chave, indice, grupo.length) : antenas.get(chave)?.posicao ? perto(antenas.get(chave)!.posicao!, indice) : null
    if (ponto) posicoes.set(item.epc, ponto)
  })
  const contagem = (estado: EstadoAoVivo) => equipamentos.filter((item) => item.estado === estado).length
  const daZona = zona ? equipamentos.filter((item) => item.zona_confirmada === zona || item.zona_leitura === zona) : []
  const alertas = (monitor?.alertas_restritos ?? []).filter((a) => a.recente)
  const abrir = (item: EquipamentoAoVivo) => { const alvo = items.find((asset) => asset.id === item.equipamento?.id); if (alvo) onSelect(alvo) }

  return <div className="map-main hu-live">
    <section className="panel map-control-panel hu-live-head">
      <div><h2>HU ao vivo · {layout.zonas.length} zonas · {layout.leitores.length} leitores</h2>
        <p className="map-help">Configuração salva do HU (sessão {resumo.codigo.slice(0, 6)}). Zonas e estados vêm só das leituras gravadas e das passagens confirmadas pelo sistema. Clique numa zona para ver os equipamentos.</p></div>
      <div className="hu-live-tools">
        <TimeControls clock={clock} canEdit={canControlTime}/>
        <label><input type="checkbox" checked={cobertura} onChange={(e) => setCobertura(e.target.checked)}/> Áreas de cobertura</label>
      </div>
      {falha && <p role="alert">Não foi possível atualizar o mapa ao vivo. Tentando novamente…</p>}
      {resumo.estado === 'pausada' && <p className="admin-warning" role="note">Simulação pausada: nenhuma leitura nova até retomar.</p>}
    </section>
    {alertas.length > 0 && <div className="hu-live-alert" role="alert">{alertas.map((a) => <span key={`${a.epc}-${a.antena}`}>⚠ {a.equipamento?.nome ?? `Tag …${a.epc.slice(-4)}`} na área restrita ({a.zona}) · {ageLabel(a.ultima_leitura_em, agora)}</span>)}</div>}
    <div className="hu-live-body">
      <div className="hu-live-plan">
        <SimPlan layout={layout} label="Planta do HU com leitores, antenas e equipamentos confirmados" options={{ showCoverage: cobertura, activeAntennas: pulsando, selected: zona }} className="sim-plan-live">
          {layout.zonas.map((z) => z.area && <button key={`zona-${z.chave}`} type="button" className={`hu-zone-hit ${zona === z.chave ? 'selected' : ''}`}
            style={{ left: `${z.area.x}%`, top: `${z.area.y}%`, width: `${z.area.largura}%`, height: `${z.area.altura}%` }}
            aria-pressed={zona === z.chave} aria-label={`${z.nome}: ver equipamentos`} onClick={() => setZona((velha) => velha === z.chave ? null : z.chave)}/>)}
          {layout.leitores.map((leitor) => <div key={leitor.chave}>
            {leitor.posicao && <span className={`hu-reader ${leitor.alerta_area_restrita ? 'restrito' : ''}`} style={at(leitor.posicao)} tabIndex={0} aria-label={`${leitor.nome} · ${leitor.modelo === 'DR_MAX' ? 'DR Max' : 'EZ700'}`}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="5" width="14" height="10" rx="2"/><path d="M7 10h6"/></svg>
              <span className="marker-tooltip"><strong>{leitor.nome}</strong><small>{leitor.modelo === 'DR_MAX' ? 'Identix DR Max' : 'Identix EZ700'} · {leitor.reader_id}</small></span></span>}
            {leitor.antenas.map((antena) => antena.posicao && <span key={antena.chave} className={`hu-antenna ${pulsando.has(antena.chave) ? 'lendo' : ''}`} style={at(antena.posicao)} tabIndex={0}
              aria-label={`${leitor.nome} / ${antena.nome}${pulsando.has(antena.chave) ? ', lendo agora' : ''}`}>
              <svg viewBox="0 0 20 20" aria-hidden="true" style={{ transform: `rotate(${(antena.orientacao ?? 270) + 90}deg)` }}>{antena.orientacao === null || antena.orientacao === undefined
                ? <circle cx="10" cy="10" r="5"/> : <path d="M10 3 L16 15 L10 12 L4 15 Z"/>}</svg>
              <span className="marker-tooltip"><strong>{antena.nome}</strong><small>{leitor.nome} · porta {antena.porta}{antena.portal ? ` · ${nomePortal.get(antena.portal)} lado ${antena.lado?.toUpperCase()}` : ''}</small></span></span>)}
          </div>)}
          {equipamentos.map((item) => {
            const ponto = posicoes.get(item.epc)
            if (!ponto) return null
            const detalhes = item.condicoes.map((c) => ESTADOS[c].rotulo).join(' · ')
            return <button key={item.epc} type="button" className={`hu-equip hu-${item.estado}`} style={at(ponto)} onClick={() => abrir(item)}
              aria-label={`${nomeDe(item)}: ${detalhes}`}>
              <EquipIcon tipo={simboloDoTipo(item.equipamento?.tipo, item.equipamento?.nome)} size={13}/>
              <span className="marker-tooltip"><strong>{nomeDe(item)}</strong><small>{detalhes}</small>
                <small>{item.zona_confirmada ? `Zona confirmada: ${nomeZona.get(item.zona_confirmada)}` : 'Nenhuma zona confirmada'}{item.ultima_leitura_em ? ` · lido ${ageLabel(item.ultima_leitura_em, agora)}` : ''}</small></span>
            </button>
          })}
        </SimPlan>
        <ul className="hu-legend" aria-label="Estados (do mais prioritário ao menos)">{ORDEM.filter((estado) => estado !== 'nunca_detectado').map((estado) =>
          <li key={estado}><span className={`hu-swatch hu-${estado}`}/>{ESTADOS[estado].rotulo} ({contagem(estado)})</li>)}</ul>
        <PlanLegend/>
      </div>
      <aside className="hu-live-side">
        {zona && <section className="panel" aria-labelledby="hu-zona-titulo"><div className="sim-items-heading"><h2 id="hu-zona-titulo">{nomeZona.get(zona)}</h2>
          <button type="button" className="link-button" onClick={() => setZona(null)}>Fechar</button></div>
          {daZona.length ? <ul className="hu-list">{daZona.map((item) => <li key={item.epc}><span className={`hu-swatch hu-${item.estado}`}/>
            <button type="button" className="link-button" onClick={() => abrir(item)}>{nomeDe(item)}</button>
            <small>{ESTADOS[item.estado].rotulo}{item.zona_confirmada !== zona ? ' · lido aqui, ainda não confirmado' : ''}{item.ultima_deteccao_em ? ` · passagem ${ageLabel(item.ultima_deteccao_em, agora)}` : ''}</small></li>)}</ul>
            : <p className="muted-text">Nenhum equipamento confirmado nesta zona.</p>}
        </section>}
        <section className="panel" aria-labelledby="hu-eventos-titulo"><h2 id="hu-eventos-titulo">Entradas, saídas e detecções</h2>
          {eventos.length ? <ol className="hu-events" aria-live="polite">{eventos.map((evento) => <li key={evento.id} className={`hu-ev-${evento.tom}`}><time>{hora(evento.em)}</time> {evento.texto}</li>)}</ol>
            : <p className="muted-text">Aguardando leituras e passagens do sistema.</p>}
        </section>
        <section className="panel" aria-labelledby="hu-sem-zona"><h2 id="hu-sem-zona">Sem zona no mapa</h2>
          {equipamentos.filter((item) => !posicoes.has(item.epc)).length ? <ul className="hu-list">{equipamentos.filter((item) => !posicoes.has(item.epc)).map((item) =>
            <li key={item.epc}><span className={`hu-swatch hu-${item.estado}`}/>{nomeDe(item)} <small>{ESTADOS[item.estado].rotulo}</small></li>)}</ul>
            : <p className="muted-text">Todos os equipamentos lidos estão no mapa.</p>}
        </section>
      </aside>
    </div>
  </div>
}
