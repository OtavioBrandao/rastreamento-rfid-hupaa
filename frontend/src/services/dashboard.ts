import type { AssetFilters, AssetPage, AssetStatus, FilterOption, MovementPage, OverviewSummary } from '../types/dashboard'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function readJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, { signal })
  if (!response.ok) throw new Error(`API respondeu ${response.status}`)
  return response.json() as Promise<T>
}

export function getAssets(filters: AssetFilters = {}, signal?: AbortSignal): Promise<AssetPage> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return readJson<AssetPage>(`/api/ativos?${params}`, signal)
}

export function getMovements(equipmentId: number, page = 1, signal?: AbortSignal): Promise<MovementPage> {
  return readJson<MovementPage>(`/equipamentos/${equipmentId}/movimentacoes?page=${page}&size=20`, signal)
}

export async function getAllAssets(filters: AssetFilters = {}, signal?: AbortSignal) {
  const first = await getAssets({ ...filters, page: 1, page_size: 100 }, signal)
  const items = [...first.items]
  const pages = Math.ceil(first.total / 100)
  for (let start = 2; start <= pages; start += 4) {
    const batch = await Promise.all(Array.from({ length: Math.min(4, pages - start + 1) },
      (_, offset) => getAssets({ ...filters, page: start + offset, page_size: 100 }, signal)))
    for (const result of batch) items.push(...result.items)
  }
  return items
}

export interface LabReading {
  id: number
  epc: string
  antena_porta: number
  recebido_em: string
}

export function getLabReadings(afterId = 0, epc = '', signal?: AbortSignal): Promise<{ items: LabReading[]; next_id: number }> {
  const params = new URLSearchParams({ after_id: String(afterId), limit: '100' })
  if (epc) params.set('epc', epc)
  return readJson(`/api/laboratorio/leituras?${params}`, signal)
}

export async function getTypes(signal?: AbortSignal): Promise<FilterOption[]> {
  const result = await readJson<{ items: FilterOption[] }>('/tipos-equipamento?size=100', signal)
  return result.items
}

interface ZoneTree { setores: { zonas: FilterOption[] }[] }
export async function getZones(signal?: AbortSignal): Promise<FilterOption[]> {
  const result = await readJson<ZoneTree[]>('/localizacoes/arvore', signal)
  return result.flatMap((floor) => floor.setores.flatMap((sector) => sector.zonas))
}

export async function getOverviewSummary(signal?: AbortSignal): Promise<OverviewSummary> {
  const statuses: AssetStatus[] = ['disponivel', 'atencao', 'fora_de_servico', 'nunca_detectado']
  const results = await Promise.all([
    getAssets({ page_size: 1 }, signal),
    ...statuses.map((status) => getAssets({ status, page_size: 1 }, signal)),
  ])
  return { registered: results[0].total,
    disponivel: results[1].total, atencao: results[2].total,
    fora_de_servico: results[3].total, nunca_detectado: results[4].total }
}
