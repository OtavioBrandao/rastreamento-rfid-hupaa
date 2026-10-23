import { apiRequest, sendJson } from './api'
import { readJson } from './dashboard'

export interface AntenaDetectada {
  antena_id: number
  porta: number
  leitor: string
  leitor_modelo: string
  zona: string | null
  origem: 'fisico' | 'simulado'
  leituras?: number
  ultima_leitura_em?: string
}

export interface EpcDetectado {
  epc: string
  situacao: 'desconhecido' | 'cadastrado'
  equipamento: { id: number; nome: string; status: string; identificador_interno: string; tipo: string } | null
  leituras: number
  primeira_leitura_em: string
  ultima_leitura_em: string
  recente: boolean
  ultima_antena: AntenaDetectada | null
  antenas: AntenaDetectada[]
}

export interface LeitorDescoberta {
  reader_id: string
  modelo: string
  origem: 'fisico' | 'simulado'
  ultimo_contato_em: string | null
  status: 'online' | 'degradado' | 'offline' | 'nunca_conectado'
  antenas: { antena_id: number; porta: number }[]
}

export interface Descoberta {
  gerado_em: string
  janela_segundos: number
  recente_segundos: number
  total: number
  desconhecidos: number
  items: EpcDetectado[]
  leitores: LeitorDescoberta[]
}

export interface FiltrosDescoberta {
  janela_segundos: number
  situacao: 'todos' | 'desconhecidos' | 'cadastrados'
  leitor?: string
  antena_id?: number
}

export interface EquipamentoCadastro {
  id: number
  nome: string
  identificador_interno: string
  status: string
  descricao: string | null
  tipo_id: number
  tipo_nome: string
  ultima_zona: string | null
  epc: string | null
  situacao_tag: 'sem_tag' | 'com_tag'
  vinculo_inicio: string | null
  created_at: string
}

export interface PaginaCadastro { items: EquipamentoCadastro[]; page: number; size: number; total: number; pages: number }

export interface NovoCadastro {
  nome: string
  tipo_id: number
  identificador_interno?: string
  descricao?: string
  epc?: string
  origem_epc: 'manual' | 'leitura'
  confirmar_associacao: boolean
}

export interface CadastroCriado {
  id: number
  nome: string
  tipo_nome: string
  identificador_interno: string
  epc: string | null
  situacao_tag: 'sem_tag' | 'com_tag'
}

export interface TipoEquipamento { id: number; nome: string; ativo?: boolean }

const EPC_RE = /^[0-9A-F]+$/

/** Mesma regra do backend (api/epc.py): 8–32 hex, quantidade par. */
export function epcProblem(value: string): string | null {
  const epc = value.trim().toUpperCase()
  if (!epc) return null
  if (!EPC_RE.test(epc)) return 'Use apenas dígitos hexadecimais (0–9, A–F).'
  if (epc.length % 2) return 'O EPC deve ter um número par de caracteres.'
  if (epc.length < 8 || epc.length > 32) return 'O EPC deve ter entre 8 e 32 caracteres.'
  return null
}

export function getDiscovery(filters: FiltrosDescoberta, signal?: AbortSignal): Promise<Descoberta> {
  const params = new URLSearchParams({ janela_segundos: String(filters.janela_segundos), situacao: filters.situacao })
  if (filters.leitor) params.set('leitor', filters.leitor)
  if (filters.antena_id) params.set('antena_id', String(filters.antena_id))
  return readJson(`/api/cadastro/epcs-detectados?${params}`, signal)
}

export function getRegistrations(situacao: string, busca: string, page: number, signal?: AbortSignal): Promise<PaginaCadastro> {
  const params = new URLSearchParams({ situacao, page: String(page), size: '20' })
  if (busca.trim()) params.set('busca', busca.trim())
  return readJson(`/api/cadastro/equipamentos?${params}`, signal)
}

export async function getEquipmentTypes(signal?: AbortSignal): Promise<TipoEquipamento[]> {
  const result = await readJson<{ items: TipoEquipamento[] }>('/tipos-equipamento?size=100', signal)
  return result.items.filter((tipo) => tipo.ativo !== false)
}

export const createEquipmentType = (nome: string) => sendJson<TipoEquipamento>('/tipos-equipamento', 'POST', { nome })
export const register = (payload: NovoCadastro) => sendJson<CadastroCriado>('/api/cadastro/equipamentos', 'POST', payload)
export const associateTag = (equipamentoId: number, epc: string) => sendJson(`/equipamentos/${equipamentoId}/tag`, 'POST', { epc })
export const epcAvailability = (epc: string) => apiRequest<{ epc: string; disponivel: boolean; equipamento: EpcDetectado['equipamento'] }>(`/api/cadastro/epcs/${encodeURIComponent(epc.trim())}`)
