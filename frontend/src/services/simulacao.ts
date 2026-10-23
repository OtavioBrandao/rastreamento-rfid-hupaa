import { apiRequest, sendJson } from './api'
import { readJson } from './dashboard'

export type Cenario = 'easy' | 'hupaa'
export type Modelo = 'EZ700' | 'DR_MAX'
export interface Ponto { x: number; y: number }
export interface Area { x: number; y: number; largura: number; altura: number }

export interface ZonaLayout { chave: string; nome: string; cor: string; area: Area | null; referencia_planta: string | null; restrita: boolean }
export interface PortalLayout { chave: string; nome: string; zona_a: string; zona_b: string; posicao: Ponto | null }
export interface AntenaLayout { chave: string; nome: string; porta: number; posicao: Ponto | null; alcance: number; portal: string | null; lado: 'a' | 'b' | null; zona: string | null }
export interface LeitorLayout { chave: string; nome: string; reader_id: string; modelo: Modelo; posicao: Ponto | null; antenas: AntenaLayout[] }
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

export interface ItemVirtual { id: string; nome: string; tipo: string | null; epc: string | null; x: number; y: number; x0: number; y0: number }

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
export interface Monitor {
  gerado_em: string
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
export const getMonitor = (codigo: string, signal?: AbortSignal) => readJson<Monitor>(`/api/simulacao/sessoes/${codigo}/monitor`, signal)

export const controlUrl = (codigo: string) => `${window.location.origin}${window.location.pathname}#/simulador/controle/${codigo}`

/** Mesmo cálculo de api/simulacao/geometria.py: distância na escala de x. */
export function inRange(item: Ponto, antenna: AntenaLayout, proporcao: number) {
  if (!antenna.posicao) return false
  return Math.hypot(item.x - antenna.posicao.x, (item.y - antenna.posicao.y) / proporcao) <= antenna.alcance
}

export function zoneAt(layout: LayoutConfig, point: Ponto) {
  return layout.zonas.find((zona) => zona.area && point.x >= zona.area.x && point.x <= zona.area.x + zona.area.largura
    && point.y >= zona.area.y && point.y <= zona.area.y + zona.area.altura) ?? null
}
