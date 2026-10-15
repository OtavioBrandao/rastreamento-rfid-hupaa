import { isFresh } from '../components/DashboardParts'
import type { EquipmentItem } from '../types/dashboard'

const names = new Intl.Collator('pt-BR', { numeric: true, sensitivity: 'base' })

/** Nome em ordem alfabética e numérica; o ID estabiliza nomes equivalentes. */
export function compareAssetNames(a: { nome: string; id: number }, b: { nome: string; id: number }) {
  return names.compare(a.nome, b.nome) || a.id - b.id
}

/** Mesmos grupos de sort=prioridade na API, sem desempate por telemetria. */
export function assetRank(item: EquipmentItem, now: number) {
  const fresh = isFresh(item.ultima_leitura, now)
  if (fresh && item.status === 'disponivel') return 0
  if (item.status === 'disponivel') return 1
  if (fresh) return 2
  if (item.status === 'atencao') return 3
  if (item.status === 'nunca_detectado') return 4
  return 5
}

/** Captura um relógio por ordenação; novas leituras só movem linhas entre grupos. */
export function assetPriority(items: EquipmentItem[], now = Date.now()) {
  return [...items].sort((a, b) => assetRank(a, now) - assetRank(b, now) || compareAssetNames(a, b))
}
