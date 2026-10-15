// Correção manual de equipamento (ISS-025): leitura do valor atual com a
// versão otimista e envio das correções. Mesma regra de sessão do resto do
// front: só cookie HttpOnly, credentials 'same-origin', 401 encerra a sessão.
import { notifySessionEnded } from './auth'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export interface EquipmentRecord {
  id: number
  nome: string
  tipo_id: number
  tipo_nome: string
  identificador_interno: string
  descricao: string | null
  status: string
  ultima_zona_id: number | null
  ultima_deteccao_em: string | null
  versao: number
}

export interface Option { id: number; label: string }

export interface LocationCorrection { zona_id: number }
export interface RecordCorrection {
  nome?: string
  tipo_id?: number
  identificador_interno?: string
  descricao?: string | null
}
export interface CorrectionMeta { justificativa: string; referencia?: string; versao_esperada: number }

export type CorrectionResult<T> =
  | { ok: true; data: T }
  | { ok: false; kind: 'conflict' | 'rejected' | 'forbidden' | 'error'; message: string }

const MESSAGES: Record<string, string> = {
  conflito_de_versao: 'O equipamento foi alterado por outra operação enquanto você editava. Os valores atuais foram recarregados: revise e confirme de novo.',
  sem_mudanca: 'Nada a corrigir: os valores informados são iguais aos atuais.',
  zona_invalida: 'Zona inexistente ou inativa.',
  tipo_invalido: 'Tipo de equipamento inexistente ou inativo.',
  equipamento_inativo: 'Equipamento inativo: reative-o antes de corrigir.',
  equipamento_inexistente: 'Equipamento não encontrado.',
  identificador_duplicado: 'Já existe outro equipamento com este patrimônio.',
  anterior_a_ultima_localizacao: 'A última detecção registrada é posterior a agora; a correção não pode voltar no tempo.',
  conflito_de_horario: 'Já existe uma detecção neste mesmo instante. Tente de novo em alguns segundos.',
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`, { credentials: 'same-origin' })
  if (response.status === 401) notifySessionEnded()
  if (!response.ok) throw new Error(`API respondeu ${response.status}`)
  return response.json() as Promise<T>
}

export function getEquipment(id: number): Promise<EquipmentRecord> {
  return getJson<EquipmentRecord>(`/equipamentos/${id}`)
}

interface ZoneTree { nome: string; setores: { nome: string; zonas: { id: number; nome: string }[] }[] }

/** "Andar › Setor › Zona": há nomes de zona repetidos entre setores. */
export async function getZoneOptions(): Promise<Option[]> {
  const tree = await getJson<ZoneTree[]>('/localizacoes/arvore')
  return tree.flatMap((floor) => floor.setores.flatMap((sector) => sector.zonas.map((zone) => ({
    id: zone.id, label: `${floor.nome} › ${sector.nome} › ${zone.nome}`,
  }))))
}

export async function getTypeOptions(): Promise<Option[]> {
  const result = await getJson<{ items: { id: number; nome: string }[] }>('/tipos-equipamento?size=100')
  return result.items.map((type) => ({ id: type.id, label: type.nome }))
}

async function post<T>(path: string, body: unknown): Promise<CorrectionResult<T>> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
  } catch {
    return { ok: false, kind: 'error', message: 'Não foi possível contactar o servidor. Tente novamente.' }
  }
  if (response.ok) return { ok: true, data: await response.json() as T }
  if (response.status === 401) {
    notifySessionEnded()
    return { ok: false, kind: 'error', message: 'Sua sessão expirou. Entre novamente.' }
  }
  if (response.status === 403) {
    return { ok: false, kind: 'forbidden', message: 'Você não tem permissão para corrigir equipamentos.' }
  }
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null
  const detail = payload?.detail
  const code = detail && typeof detail === 'object' && 'codigo' in detail ? String((detail as { codigo: unknown }).codigo) : null
  if (code === 'conflito_de_versao') return { ok: false, kind: 'conflict', message: MESSAGES[code] }
  if (code) return { ok: false, kind: 'rejected', message: MESSAGES[code] ?? 'A correção foi recusada.' }
  if (response.status === 422) return { ok: false, kind: 'rejected', message: 'Confira os campos informados.' }
  return { ok: false, kind: 'error', message: 'Não foi possível registrar a correção agora. Tente novamente.' }
}

export function correctLocation(id: number, body: LocationCorrection & CorrectionMeta) {
  return post<{ versao: number; movimentacao_id: number }>(`/equipamentos/${id}/correcoes/localizacao`, body)
}

export function correctRecord(id: number, body: RecordCorrection & CorrectionMeta) {
  return post<EquipmentRecord>(`/equipamentos/${id}/correcoes/cadastro`, body)
}
