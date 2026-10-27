import { useEffect, useMemo, useRef, useState } from 'react'
import { hospitalContextAreas } from '../../config/mapaConfig'
import type { BoundZone, MapTopology } from '../../services/mapTopology'
import {
  contornoCobertura, getLayouts, getMonitor, getSessions, moveZoneLabel,
  type LayoutResumo, type Monitor, type SessaoResumo,
} from '../../services/simulacao'
import type { AssetStatus, EquipmentItem } from '../../types/dashboard'
import { detectionLabel, zonaNaoConfirmada } from '../DashboardParts'
import { simboloDoTipo } from '../simulador/EquipIcon'
import type { MapMarker } from './FloorMap'
import { MapaHospital } from './MapaHospital'
import { MapWorkspace, PRIORIDADE_ALERTA, ROTULO_STATUS } from './MapWorkspace'

const LAYOUT_PADRAO = 'Hospital HUPAA (padrão)'
const LAYOUT_MS = 10000
const SESSAO_MS = 5000
const MONITOR_MS = 1500
const PULSO_MS = 3000
/** Uma entrada na área restrita gera UMA notificação; recarregar a página não a repete. */
const VISTOS = 'hu-entradas-restritas-notificadas'
const NOTIFICACAO_MS = 15000
const MAX_EVENTOS = 60

/** Linha do tempo das passagens: horário, frase e cor pelo tipo do que o sistema registrou. */
type Evento = { id: string; em: number; texto: string; tom: 'ok' | 'info' | 'aviso' | 'alerta' }
const TONS: { tom: Evento['tom']; rotulo: string }[] = [
  { tom: 'ok', rotulo: 'Passagem confirmada' }, { tom: 'aviso', rotulo: 'Passagem sem confirmação' },
  { tom: 'info', rotulo: 'Detectado no portal, aguardando confirmação' }, { tom: 'alerta', rotulo: 'Zona restrita' },
]
/** Cores da planta (mapaConfig), como o hospital as lê; o marrom fica de fora. */
const LEGENDA_PLANTA = [
  { cor: '#00E820', nome: 'Circulação vertical' }, { cor: '#12BCE8', nome: 'Sala de aula' },
  { cor: '#67008F', nome: 'Corredores' }, { cor: '#FFCA08', nome: 'Pacientes' }, { cor: '#F31217', nome: 'Serviço' },
]
const hora = (ms: number) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

type Notificacao = { chave: string; texto: string }

/** Preferência de cada navegador (só visual): planta colorida ou simplificada. */
const MODO_PLANTA = 'hu-mapa-planta-simplificada'
function lerModoPlanta() {
  try { return localStorage.getItem(MODO_PLANTA) === '1' } catch { return false }
}

function lerVistos(): Set<string> {
  try { return new Set(JSON.parse(sessionStorage.getItem(VISTOS) ?? '[]') as string[]) } catch { return new Set() }
}
function gravarVistos(vistos: Set<string>) {
  try { sessionStorage.setItem(VISTOS, JSON.stringify([...vistos].slice(-200))) } catch { /* sem armazenamento: só nesta aba */ }
}

/** Escolhe o layout das apresentações: o padrão do HU, senão o salvo mais recente. */
function escolherLayout(lista: LayoutResumo[]) {
  const ativos = lista.filter((item) => !item.arquivado)
  return ativos.find((item) => item.nome === LAYOUT_PADRAO) ?? [...ativos].sort((a, b) => b.id - a.id)[0] ?? null
}

/**
 * Acompanhamento do HU: a planta original do hospital com os limites das zonas e os
 * leitores do layout salvo por cima; equipamentos pela última zona confirmada.
 * As abas de consulta são as mesmas do laboratório EASY.
 */
export function MapaHUAoVivo({ topology, items, onSelect }: { topology: MapTopology; items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void }) {
  const [layout, setLayout] = useState<LayoutResumo | null | undefined>(undefined)
  const [sessao, setSessao] = useState<SessaoResumo | null>(null)
  const [monitor, setMonitor] = useState<Monitor | null>(null)
  const [cobertura, setCobertura] = useState(false)
  const [simplificada, setSimplificada] = useState(lerModoPlanta)
  const [erroRotulo, setErroRotulo] = useState<string | null>(null)
  const [notificacoes, setNotificacoes] = useState<Notificacao[]>([])
  const primeira = useRef(true)
  const [eventos, setEventos] = useState<Evento[]>([])
  const anterior = useRef<{ estados: Map<string, string>; passagens: Set<number>; entradas: Set<string> } | null>(null)

  useEffect(() => {
    let vivo = true
    const buscar = () => getLayouts('hupaa').then((lista) => { if (vivo) setLayout(escolherLayout(lista)) }).catch(() => { if (vivo) setLayout((velho) => velho ?? null) })
    buscar()
    const timer = window.setInterval(buscar, LAYOUT_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [])
  useEffect(() => {
    if (!layout) return
    let vivo = true
    const buscar = () => getSessions().then((lista) => { if (vivo) setSessao(lista.find((item) => item.layout_id === layout.id) ?? null) }).catch(() => undefined)
    buscar()
    const timer = window.setInterval(buscar, SESSAO_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [layout])
  const codigo = sessao?.codigo
  useEffect(() => {
    if (!codigo) { setMonitor(null); return }
    let vivo = true
    const buscar = () => getMonitor(codigo).then((dados) => { if (vivo) setMonitor(dados) }).catch(() => undefined)
    buscar()
    const timer = window.setInterval(buscar, MONITOR_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [codigo])

  const config = layout?.configuracao
  const restritas = useMemo(() => new Set(config?.zonas.filter((z) => z.restrita).map((z) => z.nome) ?? []), [config])

  // Passagens detalhadas: diferenças entre consultas do que o pipeline gravou (nada vem do simulador).
  useEffect(() => {
    if (!monitor) return
    const antes = anterior.current
    const estados = new Map((monitor.equipamentos ?? []).map((item) => [item.epc, item.estado]))
    const passagensVistas = new Set(monitor.passagens.map((item) => item.id))
    const entradas = new Set((monitor.alertas_restritos ?? []).map((a) => `${a.epc}|${a.entrada_em ?? a.primeira_leitura_em}`))
    anterior.current = { estados, passagens: passagensVistas, entradas }
    const novos: Evento[] = []
    for (const p of [...monitor.passagens.filter((item) => !antes?.passagens.has(item.id))].reverse()) {
      const nome = p.equipamento ?? `Tag …${p.epc.slice(-4)} (não cadastrada)`
      novos.push(p.direcao_status === 'confirmed'
        ? { id: `p${p.id}`, em: Date.parse(p.detectada_em), tom: 'ok', texto: `${nome} saiu da ${p.zona_origem} e entrou na ${p.zona_destino} pelo portal “${p.portal}” — passagem confirmada` }
        : { id: `p${p.id}`, em: Date.parse(p.detectada_em), tom: 'aviso', texto: `${nome} foi lido no portal “${p.portal}”, mas a passagem não foi confirmada (leituras insuficientes para saber a zona)` })
    }
    const agoraMs = Date.parse(monitor.gerado_em)
    if (antes) for (const item of monitor.equipamentos ?? []) {
      if (antes.estados.get(item.epc) === item.estado || item.estado !== 'em_transito') continue
      const nome = item.equipamento?.nome ?? `Tag …${item.epc.slice(-4)}`
      const portal = config?.portais.find((p) => p.chave === item.portal)?.nome ?? 'portal'
      novos.push({ id: `t${item.epc}${agoraMs}`, em: agoraMs, tom: 'info', texto: `${nome} detectado no portal “${portal}”, aguardando a confirmação da passagem` })
    }
    for (const alerta of monitor.alertas_restritos ?? []) {
      const chave = `${alerta.epc}|${alerta.entrada_em ?? alerta.primeira_leitura_em}`
      if (antes?.entradas.has(chave)) continue
      const em = Date.parse(alerta.entrada_em ?? alerta.primeira_leitura_em)
      novos.push({ id: `r${chave}`, em, tom: 'alerta', texto: `${alerta.equipamento?.nome ?? `Tag …${alerta.epc.slice(-4)}`} entrou na zona restrita (${alerta.zona}) — portal de zona restrita` })
    }
    if (novos.length) setEventos((velhos) => [...novos, ...velhos].sort((a, b) => b.em - a.em).slice(0, MAX_EVENTOS))
  }, [monitor, config])

  // Notificação da entrada confirmada na zona restrita: uma por entrada, nunca contínua.
  useEffect(() => {
    if (!monitor) return
    const vistos = lerVistos()
    const agora = Date.parse(monitor.gerado_em)
    const novas: Notificacao[] = []
    const recentes = new Map<string, number>()
    for (const alerta of monitor.alertas_restritos ?? []) {
      const entrada = alerta.entrada_em ?? alerta.primeira_leitura_em
      const chave = `${alerta.epc}|${entrada}`
      recentes.set(alerta.epc, Math.max(recentes.get(alerta.epc) ?? 0, Date.parse(entrada)))
      if (vistos.has(chave)) continue
      vistos.add(chave)
      // Ao abrir a tela, só avisa o que acabou de acontecer.
      if (!primeira.current || agora - Date.parse(entrada) < 20000)
        novas.push({ chave, texto: `${alerta.equipamento?.nome ?? `Tag …${alerta.epc.slice(-4)} (não cadastrada)`} entrou na área restrita (${alerta.zona}) às ${new Date(entrada).toLocaleTimeString('pt-BR')}` })
    }
    for (const passagem of monitor.passagens) {
      if (passagem.direcao_status !== 'confirmed' || !passagem.zona_destino || !restritas.has(passagem.zona_destino)) continue
      const chave = `passagem|${passagem.id}`
      if (vistos.has(chave)) continue
      vistos.add(chave)
      const quando = Date.parse(passagem.detectada_em)
      if (Math.abs((recentes.get(passagem.epc) ?? -Infinity) - quando) < 60000) continue  // o alerta já avisou esta entrada
      if (!primeira.current || agora - quando < 20000)
        novas.push({ chave, texto: `${passagem.equipamento ?? `Tag …${passagem.epc.slice(-4)}`} entrou em ${passagem.zona_destino} (passagem confirmada às ${new Date(quando).toLocaleTimeString('pt-BR')})` })
    }
    primeira.current = false
    gravarVistos(vistos)
    if (!novas.length) return
    setNotificacoes((velhas) => [...novas, ...velhas].slice(0, 4))
    const timer = window.setTimeout(() => setNotificacoes((velhas) => velhas.filter((n) => !novas.includes(n))), NOTIFICACAO_MS)
    return () => window.clearTimeout(timer)
  }, [monitor, restritas])

  if (layout === undefined) return <div className="panel map-skeleton" role="status" aria-label="Carregando mapa do HU"><span/><span/></div>
  const zonasIds = layout?.zonas_ids ?? {}
  const zones: BoundZone[] = config ? config.zonas.flatMap((zona) => zona.area && zonasIds[zona.chave] ? [{
    id: zona.chave, name: zona.nome, zoneId: zonasIds[zona.chave], porId: true,
    x: zona.rotulo?.x ?? zona.area.x + 3, y: zona.rotulo?.y ?? zona.area.y + 2.5, description: zona.restrita ? 'Zona restrita' : 'Zona do HU',
    area: { x: zona.area.x, y: zona.area.y, width: zona.area.largura, height: zona.area.altura },
  }] : []) : []
  // Sem layout salvo e aplicado, vale a planta de referência com as zonas do seed.
  if (!config || !zones.length) return <MapaHospital topology={topology} items={items} onSelect={onSelect}/>

  const agora = monitor ? Date.parse(monitor.gerado_em) : Date.now()
  const lendo = new Map<string, number>()
  for (const leitura of monitor?.leituras ?? []) if (leitura.antena && agora - Date.parse(leitura.lido_em) <= PULSO_MS) lendo.set(leitura.antena, Math.max(lendo.get(leitura.antena) ?? 0, leitura.id))
  const markers: MapMarker[] = config.leitores.flatMap((leitor) => [
    ...(leitor.posicao ? [{ id: `leitor-${leitor.chave}`, kind: 'reader' as const, ...leitor.posicao, label: leitor.nome,
      detail: `${leitor.modelo === 'DR_MAX' ? 'Identix DR Max' : 'Identix EZ700'}${leitor.alerta_area_restrita ? ' · leitor da zona restrita' : ''} · posição aproximada` }] : []),
    ...leitor.antenas.flatMap((antena) => antena.posicao ? [{ id: `antena-${antena.chave}`, kind: 'antenna' as const, ...antena.posicao,
      label: `${leitor.nome} · ${antena.nome}`, detail: `Porta ${antena.porta}${antena.portal ? ` · ${config.portais.find((p) => p.chave === antena.portal)?.nome ?? ''} lado ${antena.lado?.toUpperCase()}` : ''}${lendo.has(antena.chave) ? ' · lendo agora' : ''}`,
      pulse: lendo.has(antena.chave), pulseKey: lendo.get(antena.chave) }] : []),
  ])
  const naRestrita = (monitor?.alertas_restritos ?? []).filter((alerta) => alerta.recente)
  // Zona não confirmada: lido perto de uma antena, sem transição. Fica junto da antena,
  // com marca própria, e não conta como ocupação de zona.
  const antenaPorLeitura = new Map(config.leitores.flatMap((leitor) => leitor.antenas.map((antena) => [`${leitor.reader_id}|${antena.porta}`, antena])))
  const naoConfirmados: MapMarker[] = items.filter((item) => !item.ultima_zona && item.ultima_leitura?.leitor).flatMap((item, indice) => {
    const antena = antenaPorLeitura.get(`${item.ultima_leitura!.leitor}|${item.ultima_leitura!.porta}`)
    if (!antena?.posicao) return []
    const angulo = indice * 2.4 + 0.8
    return [{ id: `eq-${item.id}`, kind: 'equipment' as const, x: antena.posicao.x + Math.cos(angulo) * 2.2, y: antena.posicao.y + Math.sin(angulo) * 4,
      symbol: simboloDoTipo(item.tipo, item.nome), label: item.nome, detail: zonaNaoConfirmada(item) ?? 'Zona não confirmada',
      ariaLabel: `${item.nome}: zona não confirmada, visto perto da antena. Abrir detalhes`, nonConfirmed: true }]
  })
  const svgExtras = <>
    {cobertura && config.leitores.flatMap((leitor) => leitor.antenas).map((antena) => antena.posicao && <path key={`cob-${antena.chave}`} className="hu-cobertura" d={contornoCobertura(antena, config.proporcao)}/>)}
    {/* Contorno claro por baixo e tracejado escuro por cima: a zona aparece sobre qualquer cor da planta. */}
    {config.zonas.map((zona) => zona.area && <g key={`lim-${zona.chave}`}>
      <rect className={`hu-zona-fundo${zona.restrita ? ' restrita' : ''}${zona.restrita && naRestrita.length ? ' alerta' : ''}`} x={zona.area.x} y={zona.area.y} width={zona.area.largura} height={zona.area.altura}/>
      <rect className="hu-limite-halo" x={zona.area.x} y={zona.area.y} width={zona.area.largura} height={zona.area.altura}/>
      <rect className={`hu-limite${zona.restrita ? ' restrita' : ''}`} x={zona.area.x} y={zona.area.y} width={zona.area.largura} height={zona.area.altura}/>
    </g>)}
  </>
  // Nome da zona arrastado: grava no layout compartilhado (banco); a área não muda.
  const moverRotulo = (chave: string, x: number, y: number) => {
    if (!layout) return
    setErroRotulo(null)
    setLayout({ ...layout, configuracao: { ...layout.configuracao, zonas: layout.configuracao.zonas.map((zona) => zona.chave === chave ? { ...zona, rotulo: { x, y } } : zona) } })
    moveZoneLabel(layout.id, chave, { x, y }).then((salvo) => setLayout(salvo)).catch(() => {
      setErroRotulo('Não foi possível salvar a posição do nome da zona. A posição anterior foi mantida.')
      setLayout(layout)
    })
  }
  const alternarPlanta = (valor: boolean) => {
    setSimplificada(valor)
    try { localStorage.setItem(MODO_PLANTA, valor ? '1' : '0') } catch { /* sem armazenamento: vale nesta visita */ }
  }
  const contagem = (status: AssetStatus) => items.filter((item) => item.status === status && zones.some((z) => item.ultima_zona?.id === z.zoneId)).length

  return <div className="map-main hu-tracking">
    {notificacoes.length > 0 && <div className="hu-toasts" role="alert">{notificacoes.map((n) => <p key={n.chave} className="hu-toast">⚠ {n.texto}
      <button type="button" aria-label="Dispensar notificação" onClick={() => setNotificacoes((velhas) => velhas.filter((v) => v.chave !== n.chave))}>×</button></p>)}</div>}
    {naRestrita.length > 0 && <p className="hu-restrita-agora" role="status"><strong>Atividade suspeita</strong> — na zona restrita agora: {naRestrita.map((a) => a.equipamento?.nome ?? `Tag …${a.epc.slice(-4)}`).join(', ')}</p>}
    {erroRotulo && <p role="alert" className="hu-rotulo-erro">{erroRotulo}</p>}
    <MapWorkspace mode="hospital" zones={zones} portals={[]} items={items} onSelect={onSelect} markers={[...markers, ...naoConfirmados]} areas={hospitalContextAreas} svgExtras={svgExtras}
      simplified={simplificada} onZoneLabelMove={moverRotulo}
      below={<div className="hu-legenda">
        <div className="hu-modo-planta" role="group" aria-label="Aparência da planta">
          <button type="button" aria-pressed={!simplificada} onClick={() => alternarPlanta(false)}>Planta colorida</button>
          <button type="button" aria-pressed={simplificada} onClick={() => alternarPlanta(true)}>Planta simplificada</button>
          <small>Arraste o nome de uma zona para reposicioná-lo; a posição fica salva no layout.</small>
        </div>
        {!simplificada && <ul className="hu-legend" aria-label="Cores da planta do HU">{LEGENDA_PLANTA.map((item) =>
          <li key={item.nome}><span className="hu-planta-cor" style={{ background: item.cor }}/>{item.nome}</li>)}
          <li><span className="hu-planta-cor hu-planta-zona"/>Limite de zona</li><li><span className="map-legend-dot marker-nao-confirmado"/>Zona não confirmada (visto perto da antena)</li><li><span className="hu-planta-cor hu-planta-restrita"/>Zona restrita</li></ul>}
        <ul className="hu-legend" aria-label="Cores dos equipamentos, da maior para a menor prioridade de alerta">{PRIORIDADE_ALERTA.map((status) =>
          <li key={status}><span className={`map-legend-dot marker-${status}`}/>{ROTULO_STATUS[status]} ({contagem(status)})</li>)}</ul>
        <label className="hu-cobertura-toggle"><input type="checkbox" checked={cobertura} onChange={(e) => setCobertura(e.target.checked)}/> Áreas de cobertura
          <small>Indicação visual aproximada do alcance das antenas; não é medição física.</small></label>
      </div>}
      extraTabs={[{ id: 'passagens', label: 'Passagens detalhadas', count: eventos.length, content: <section className="panel inventory-panel" aria-label="Passagens detalhadas">
        <div className="panel-heading"><h2>Passagens detalhadas</h2></div>
        <ul className="hu-legend" aria-label="Cores das passagens">{TONS.map((t) => <li key={t.tom}><span className={`hu-ev-swatch hu-ev-${t.tom}`}/>{t.rotulo}</li>)}</ul>
        {eventos.length ? <ol className="hu-events" aria-live="polite">{eventos.map((evento) => <li key={evento.id} className={`hu-ev-${evento.tom}`}><time>{hora(evento.em)}</time> {evento.texto}</li>)}</ol>
          : <p className="map-table-empty">{codigo ? `Nenhuma passagem gravada desde ${detectionLabel(new Date(agora).toISOString())}.` : 'Nenhuma simulação do HU em execução.'}</p>}
      </section> }]}/>
  </div>
}
