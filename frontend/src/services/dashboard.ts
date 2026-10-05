import type { ActivityItem, AssetFilters, AssetPage, FilterOption, MovementPage, OverviewSummary, ReadSummary } from '../types/dashboard'
import { notifySessionEnded } from './auth'
import type { MapTopology, RegisteredPortal, RegisteredZone } from './mapTopology'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function readJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  const timeout = window.setTimeout(abort, 8000)
  try {
    const response = await fetch(`${base}${path}`, { signal: controller.signal, cache: 'no-store', credentials: 'same-origin' })
    // 401 no meio do uso = sessão expirada, conta desativada ou logout em outra aba (ISS-027).
    if (response.status === 401) notifySessionEnded()
    if (!response.ok) throw new Error(`API respondeu ${response.status}`)
    return await response.json() as T
  } finally { window.clearTimeout(timeout); signal?.removeEventListener('abort', abort) }
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

export function getOverviewSummary(signal?: AbortSignal): Promise<OverviewSummary> {
  return readJson('/api/dashboard/resumo', signal)
}

export async function getRecentActivity(signal?: AbortSignal): Promise<ActivityItem[]> {
  const result = await readJson<{ items: ActivityItem[] }>('/api/dashboard/atividade?limit=8', signal)
  return result.items
}

export async function getMapTopology(signal?: AbortSignal): Promise<MapTopology> {
  type Tree = { setores: { zonas: RegisteredZone[] }[] }[]
  type PortalPage = { items: RegisteredPortal[]; pages: number }
  const [tree, first] = await Promise.all([
    readJson<Tree>('/localizacoes/arvore', signal),
    readJson<PortalPage>('/portais?page=1&size=100', signal),
  ])
  const portals = [...first.items]
  for (let page = 2; page <= first.pages; page++) {
    const next = await readJson<PortalPage>(`/portais?page=${page}&size=100`, signal)
    portals.push(...next.items)
  }
  return { zones: tree.flatMap((floor) => floor.setores.flatMap((sector) => sector.zonas)), portals }
}

export function getReadSummary(windowSeconds: number, registeredOnly = false, signal?: AbortSignal): Promise<ReadSummary> {
  const params = new URLSearchParams({ janela_segundos: String(windowSeconds) })
  if (registeredOnly) params.set('somente_cadastradas', 'true')
  return readJson(`/api/leituras/resumo?${params}`, signal)
}
