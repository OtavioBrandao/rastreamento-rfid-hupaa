import { apiRequest, sendJson } from './api'
import { readJson } from './dashboard'

export type Cenario = 'easy' | 'hupaa'
export type Modelo = 'EZ700' | 'DR_MAX'
export interface Ponto { x: number; y: number }
export interface Area { x: number; y: number; largura: number; altura: number }

export interface ZonaLayout { chave: string; nome: string; cor: string; area: Area | null; referencia_planta: string | null; restrita: boolean }
export interface PortalLayout { chave: string; nome: string; zona_a: string; zona_b: string; posicao: Ponto | null }
/** `orientacao`: visada em graus da tela (0 direita, 90 baixo, 180 esquerda, 270 cima); null = omnidirecional (layout antigo). */
export interface AntenaLayout { chave: string; nome: string; porta: number; posicao: Ponto | null; alcance: number; orientacao?: number | null; fator_traseiro?: number; portal: string | null; lado: 'a' | 'b' | null; zona: string | null }
export interface LeitorLayout { chave: string; nome: string; reader_id: string; modelo: Modelo; posicao: Ponto | null; antenas: AntenaLayout[]; alerta_area_restrita?: boolean }

export const ALCANCE_PADRAO = 4
export const FATOR_TRASEIRO_PADRAO = 0.35
export const DIRECOES: { graus: number; seta: string; nome: string }[] = [
  { graus: 270, seta: '↑', nome: 'Cima' }, { graus: 315, seta: '↗', nome: 'Cima-direita' }, { graus: 0, seta: '→', nome: 'Direita' }, { graus: 45, seta: '↘', nome: 'Baixo-direita' },
  { graus: 90, seta: '↓', nome: 'Baixo' }, { graus: 135, seta: '↙', nome: 'Baixo-esquerda' }, { graus: 180, seta: '←', nome: 'Esquerda' }, { graus: 225, seta: '↖', nome: 'Cima-esquerda' },
]
export function nomeDirecao(graus: number | null | undefined) {
  if (graus === null || graus === undefined) return 'todas as direções'
  const exata = DIRECOES.find((item) => item.graus === Math.round(graus) % 360)
  return exata ? `${exata.seta} ${exata.nome.toLowerCase()} (${exata.graus}°)` : `${Math.round(graus)}°`
}
export interface LayoutConfig {
  cenario: Cenario
  proporcao: number
  destino: { andar: string; setor: string } | null
  zonas: ZonaLayout[]
  portais: PortalLayout[]
  leitores: LeitorLayout[]
}

export interface LayoutResumo {
  id: number
  nome: string
  cenario: Cenario
  configuracao: LayoutConfig
  versao: number
  arquivado: boolean
  aplicado_em: string | null
  updated_at: string
  avisos: string[]
}

export interface PontoTrajeto { x: number; y: number; t: number }
/** Trajeto em execução: `inicio` no relógio da simulação; `t` em segundos desde o início do desenho. */
export interface Trajeto { inicio: string; pontos: PontoTrajeto[]; pausado_em?: string }
export interface ItemVirtual { id: string; nome: string; tipo: string | null; epc: string | null; x: number; y: number; x0: number; y0: number; trajeto?: Trajeto }

export interface MotorEstado {
  ativo: boolean
  lider: boolean
  conectado: boolean
  erro: string | null
  destino: string | null
  pendentes: number
  sessao: { publicadas: number; no_alcance: Record<string, string[]>; ultima_deteccao: Record<string, string>; erro: string | null } | null
}

export interface Sessao {
  codigo: string
  layout_id: number
  cenario: Cenario
  estado: 'em_execucao' | 'pausada' | 'encerrada'
  versao: number
  layout: LayoutConfig
  itens: ItemVirtual[]
  iniciada_em: string
  atualizada_em: string
  encerrada_em: string | null
  motor: MotorEstado | null
}

export interface SessaoResumo { codigo: string; layout_id: number; cenario: Cenario; estado: Sessao['estado']; versao: number; itens: number; iniciada_em: string }

export interface SimConfig {
  habilitado: boolean
  ambiente: string
  motivo: string | null
  periodo_leitura_ms: number
  max_antenas_por_leitor: number
  modelos_leitor: { id: Modelo; nome: string; max_antenas: number; observacao: string }[]
  cenarios: { id: Cenario; nome: string }[]
  motor: MotorEstado | null
}

export interface EquipamentoZona { id: number; nome: string; tipo: string; epc: string | null; ultima_deteccao_em: string | null; estado_recencia: string }
export interface AlertaRestrito { epc: string; zona: string; leitor: string; reader_id: string; antena: string; porta: number; leituras: number; primeira_leitura_em: string; ultima_leitura_em: string; recente: boolean; equipamento: { id: number; nome: string } | null }
export type EstadoAoVivo = 'fora_de_servico' | 'em_transito' | 'atencao' | 'detectado' | 'confirmado' | 'sem_confirmacao' | 'nunca_detectado'
/** Estado de cada tag/equipamento calculado no backend só com o que o pipeline gravou. */
export interface EquipamentoAoVivo {
  epc: string
  equipamento: { id: number; nome: string; tipo: string; status: string } | null
  estado: EstadoAoVivo
  condicoes: EstadoAoVivo[]
  zona_confirmada: string | null
  zona_leitura: string | null
  antena: string | null
  portal: string | null
  area_restrita: boolean
  ultima_leitura_em: string | null
  ultima_deteccao_em: string | null
  recencia: string | null
  ultima_passagem: { status: string | null; portal: string | null; zona_origem: string | null; zona_destino: string | null; detectada_em: string } | null
}
export interface Relogio { agora: string; real: string; fator: number; adiantado_s: number; acelerado: boolean; fatores: number[] }
export interface Monitor {
  gerado_em: string
  equipamentos?: EquipamentoAoVivo[]
  relogio?: Relogio
  alertas_restritos?: AlertaRestrito[]
  leituras_total: number
  leituras: { id: number; epc: string; reader_id: string; porta: number; antena: string | null; lido_em: string; rssi: number | null; equipamento: { id: number; nome: string } | null }[]
  tags: { epc: string; leituras: number; ultima_leitura_em: string; recente: boolean; equipamento: { id: number; nome: string } | null }[]
  passagens: { id: number; epc: string; portal: string; direcao: string | null; direcao_status: string | null; zona_origem: string | null; zona_destino: string | null; detectada_em: string; equipamento: string | null }[]
  zonas: Record<string, EquipamentoZona[]>
  leitores: { chave: string; reader_id: string; modelo: string; status: string; ultimo_contato_em: string | null; leituras_sessao: number }[]
}

export const getSimConfig = (signal?: AbortSignal) => readJson<SimConfig>('/api/simulacao/config', signal)
export const getLayouts = (cenario: Cenario, signal?: AbortSignal) => readJson<LayoutResumo[]>(`/api/simulacao/layouts?cenario=${cenario}`, signal)
export const createLayout = (cenario: Cenario, nome?: string, configuracao?: LayoutConfig) => sendJson<LayoutResumo>('/api/simulacao/layouts', 'POST', { cenario, nome, configuracao })
export const saveLayout = (id: number, nome: string, configuracao: LayoutConfig, versao: number) => sendJson<LayoutResumo>(`/api/simulacao/layouts/${id}`, 'PUT', { nome, configuracao, versao })
export const restorePreset = (id: number) => sendJson<LayoutResumo>(`/api/simulacao/layouts/${id}/restaurar-preset`, 'POST')
export const archiveLayout = (id: number) => apiRequest<void>(`/api/simulacao/layouts/${id}`, { method: 'DELETE' })
export const getSessions = (signal?: AbortSignal) => readJson<SessaoResumo[]>('/api/simulacao/sessoes', signal)
export const startSession = (layoutId: number) => sendJson<Sessao>('/api/simulacao/sessoes', 'POST', { layout_id: layoutId })
export const getSession = (codigo: string, desdeVersao?: number, signal?: AbortSignal) =>
  readJson<Sessao | (Pick<Sessao, 'codigo' | 'versao' | 'estado' | 'motor'> & { inalterada: true })>(
    `/api/simulacao/sessoes/${codigo}${desdeVersao !== undefined ? `?desde_versao=${desdeVersao}` : ''}`, signal)
export const sessionAction = (codigo: string, acao: 'pausar' | 'retomar' | 'reiniciar' | 'encerrar') => sendJson<Sessao>(`/api/simulacao/sessoes/${codigo}/${acao}`, 'POST')
export const addItem = (codigo: string, item: { nome: string; tipo?: string; epc?: string; gerar_epc?: boolean; x?: number; y?: number }) => sendJson<Sessao>(`/api/simulacao/sessoes/${codigo}/itens`, 'POST', item)
export const updateItem = (codigo: string, id: string, campos: Partial<Pick<ItemVirtual, 'x' | 'y' | 'nome' | 'tipo' | 'epc'>> & { gerar_epc?: boolean; remover_epc?: boolean }) =>
  sendJson<{ codigo: string; versao: number; itens: ItemVirtual[] }>(`/api/simulacao/sessoes/${codigo}/itens/${id}`, 'PATCH', campos)
export const removeItem = (codigo: string, id: string) => apiRequest<{ codigo: string; versao: number; itens: ItemVirtual[] }>(`/api/simulacao/sessoes/${codigo}/itens/${id}`, { method: 'DELETE' })
export const quickTest = (cenario: Cenario) => sendJson<Sessao>('/api/simulacao/teste-rapido', 'POST', { cenario })
export const wipeScenario = (cenario: Cenario) => sendJson<{ sessoes_encerradas: number; layouts_arquivados: number }>('/api/simulacao/apagar-tudo', 'POST', { cenario })
export const clearItems = (codigo: string) => apiRequest<{ codigo: string; versao: number; itens: ItemVirtual[] }>(`/api/simulacao/sessoes/${codigo}/itens`, { method: 'DELETE' })
export const getMonitor = (codigo: string, signal?: AbortSignal) => readJson<Monitor>(`/api/simulacao/sessoes/${codigo}/monitor`, signal)
export const runPath = (codigo: string, id: string, pontos: PontoTrajeto[]) =>
  sendJson<{ codigo: string; versao: number; itens: ItemVirtual[]; relogio: Relogio }>(`/api/simulacao/sessoes/${codigo}/itens/${id}/trajeto`, 'POST', { pontos })
export const getClock = (signal?: AbortSignal) => readJson<Relogio>('/api/simulacao/relogio', signal)
export const setClock = (mudanca: { fator?: number; avancar_s?: number }) => sendJson<Relogio>('/api/simulacao/relogio', 'POST', mudanca)

/** Mesma interpolação de api/simulacao/trajeto.py: posição executada no instante simulado `agoraMs`. */
export function posicaoNoTempo(item: ItemVirtual, agoraMs: number): Ponto {
  const trajeto = item.trajeto
  if (!trajeto) return { x: item.x, y: item.y }
  const limite = trajeto.pausado_em ? Math.min(agoraMs, Date.parse(trajeto.pausado_em)) : agoraMs
  const decorrido = (limite - Date.parse(trajeto.inicio)) / 1000
  const pontos = trajeto.pontos
  if (decorrido <= 0) return { x: pontos[0].x, y: pontos[0].y }
  const ultimo = pontos[pontos.length - 1]
  if (decorrido >= ultimo.t) return { x: ultimo.x, y: ultimo.y }
  let baixo = 0, alto = pontos.length - 1
  while (alto - baixo > 1) { const meio = (baixo + alto) >> 1; if (pontos[meio].t <= decorrido) baixo = meio; else alto = meio }
  const a = pontos[baixo], b = pontos[alto]
  const f = b.t === a.t ? 0 : (decorrido - a.t) / (b.t - a.t)
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }
}

/** O item ainda percorre o trajeto (pausado conta). */
export function emTrajeto(item: ItemVirtual, agoraMs: number) {
  const trajeto = item.trajeto
  if (!trajeto) return false
  return !!trajeto.pausado_em || agoraMs < Date.parse(trajeto.inicio) + trajeto.pontos[trajeto.pontos.length - 1].t * 1000
}

export const controlUrl = (codigo: string) => `${window.location.origin}${window.location.pathname}#/simulador/controle/${codigo}`

/** Mesma fórmula de api/simulacao/geometria.py: alcance na direção `angulo` (radianos, escala de x, y para baixo). */
export function alcanceNaDirecao(antena: AntenaLayout, angulo: number) {
  if (antena.orientacao === null || antena.orientacao === undefined) return antena.alcance
  const f = antena.fator_traseiro ?? FATOR_TRASEIRO_PADRAO
  const frente = (1 + Math.cos(angulo - (antena.orientacao * Math.PI) / 180)) / 2
  return antena.alcance * (f + (1 - f) * frente ** 2)
}

/** A antena lê o ponto? Distância na escala de x, alcance conforme a visada. */
export function inRange(item: Ponto, antenna: AntenaLayout, proporcao: number) {
  if (!antenna.posicao) return false
  const dx = item.x - antenna.posicao.x, dy = (item.y - antenna.posicao.y) / proporcao
  return Math.hypot(dx, dy) <= alcanceNaDirecao(antenna, Math.atan2(dy, dx)) + 1e-9
}

/** Contorno da cobertura (coordenadas 0–100 da planta) para desenhar no SVG. */
export function contornoCobertura(antena: AntenaLayout, proporcao: number, passos = 48) {
  if (!antena.posicao) return ''
  const { x, y } = antena.posicao
  const pontos = Array.from({ length: passos }, (_, i) => {
    const angulo = (i / passos) * 2 * Math.PI
    const r = alcanceNaDirecao(antena, angulo)
    return `${(x + r * Math.cos(angulo)).toFixed(2)},${(y + r * Math.sin(angulo) * proporcao).toFixed(2)}`
  })
  return `M${pontos.join(' L')} Z`
}

/** Novos padrões para antenas de layouts antigos: visada para o centro da própria zona,
 *  traseira curta e alcance limitado. Posições, portais e nomes não mudam. */
export function aplicarPadroesDeAntena(layout: LayoutConfig): LayoutConfig {
  const limite = layout.cenario === 'easy' ? 11 : ALCANCE_PADRAO
  return { ...layout, leitores: layout.leitores.map((leitor) => ({ ...leitor, antenas: leitor.antenas.map((antena) => {
    if (antena.orientacao !== null && antena.orientacao !== undefined) return antena
    const area = layout.zonas.find((zona) => zona.chave === antena.zona)?.area
    let orientacao = 0
    if (area && antena.posicao) {
      const dx = area.x + area.largura / 2 - antena.posicao.x, dy = (area.y + area.altura / 2 - antena.posicao.y) / layout.proporcao
      if (Math.hypot(dx, dy) > 0.5) orientacao = Math.round(((Math.atan2(dy, dx) * 180) / Math.PI + 360) % 360)
    }
    return { ...antena, orientacao, fator_traseiro: FATOR_TRASEIRO_PADRAO, alcance: Math.min(antena.alcance, limite) }
  }) })) }
}

export function zoneAt(layout: LayoutConfig, point: Ponto) {
  return layout.zonas.find((zona) => zona.area && point.x >= zona.area.x && point.x <= zona.area.x + zona.area.largura
    && point.y >= zona.area.y && point.y <= zona.area.y + zona.area.altura) ?? null
}

/** Zona restrita vigiada pelo leitor (alguma antena dele fica dentro dela), ou null. */
export function zonaRestritaDoLeitor(layout: LayoutConfig, leitor: LeitorLayout) {
  const restritas = new Set(layout.zonas.filter((zona) => zona.restrita).map((zona) => zona.chave))
  const chave = leitor.antenas.find((antena) => antena.zona && restritas.has(antena.zona))?.zona
  return layout.zonas.find((zona) => zona.chave === chave) ?? null
}

export const antenaNaZonaRestrita = (layout: LayoutConfig, antena: AntenaLayout) =>
  !!antena.zona && layout.zonas.some((zona) => zona.chave === antena.zona && zona.restrita)

const alcanceEntre = (a: AntenaLayout, b: AntenaLayout, p: number) =>
  alcanceNaDirecao(a, Math.atan2((b.posicao!.y - a.posicao!.y) / p, b.posicao!.x - a.posicao!.x))

/** Mesmo lado e mesma zona, cada uma num portal: no mesmo ponto valem como UM ponto de detecção (igual a esquema.py). */
export const pontoUnico = (a: AntenaLayout, b: AntenaLayout) => !!a.portal && !!b.portal && a.portal !== b.portal && a.lado === b.lado && a.zona === b.zona

/** O que ainda falta para a demonstração funcionar (mesmas regras de `avisos` no backend). */
export function pendencias(layout: LayoutConfig): string[] {
  const resultado: string[] = []
  if (!layout.zonas.length) resultado.push('Desenhe pelo menos duas zonas.')
  for (const zona of layout.zonas) if (!zona.area) resultado.push(`Delimite a zona “${zona.nome}” na planta.`)
  if (layout.zonas.length >= 2 && !layout.portais.length) resultado.push('Crie um portal entre duas zonas.')
  for (const leitor of layout.leitores) {
    if (!leitor.posicao) resultado.push(`Posicione o ${leitor.nome}.`)
    for (const antena of leitor.antenas) if (!antena.posicao) resultado.push(`Posicione a ${antena.nome} do ${leitor.nome}.`)
  }
  for (const portal of layout.portais) {
    const lados = new Set(layout.leitores.flatMap((l) => l.antenas.filter((a) => a.portal === portal.chave).map((a) => a.lado)))
    for (const [lado, zona] of [['a', portal.zona_a], ['b', portal.zona_b]] as const) if (!lados.has(lado)) {
      const nome = layout.zonas.find((item) => item.chave === zona)?.nome ?? zona
      resultado.push(`Portal “${portal.nome}”: nenhuma antena no lado ${lado.toUpperCase()} (${nome}), então a passagem por ele nunca é confirmada. Ligue uma antena a esse lado ou remova o portal se essa entrada é vigiada só pelo leitor de área restrita.`)
    }
  }
  const posicionadas = layout.leitores.flatMap((leitor) => leitor.antenas.filter((antena) => antena.posicao).map((antena) => ({ leitor, antena })))
  posicionadas.forEach(({ leitor, antena }, i) => {
    for (const outro of posicionadas.slice(i + 1)) {
      const d = Math.hypot(antena.posicao!.x - outro.antena.posicao!.x, (antena.posicao!.y - outro.antena.posicao!.y) / layout.proporcao)
      const nomes = `${leitor.nome} / ${antena.nome} e ${outro.leitor.nome} / ${outro.antena.nome}`
      if (d < 1 && !pontoUnico(antena, outro.antena)) resultado.push(`${nomes} estão no mesmo ponto: só faz sentido se forem o mesmo lado de portais diferentes, na mesma zona.`)
      else if (antena.portal && antena.portal === outro.antena.portal && antena.lado !== outro.antena.lado && d <= alcanceEntre(antena, outro.antena, layout.proporcao) + alcanceEntre(outro.antena, antena, layout.proporcao))
        resultado.push(`${nomes}: os alcances dos lados A e B se sobrepõem e a direção não é confirmada. Afaste-as ou reduza o alcance.`)
    }
  })
  const restritas = new Set(layout.zonas.filter((zona) => zona.restrita).map((zona) => zona.chave))
  for (const leitor of layout.leitores) if (leitor.alerta_area_restrita && !leitor.antenas.some((antena) => antena.zona && restritas.has(antena.zona)))
    resultado.push(`${leitor.nome} avisa área restrita, mas nenhuma antena dele está numa zona marcada como restrita.`)
  return resultado
}
