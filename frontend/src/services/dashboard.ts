import { dashboardFixture } from '../mocks/dashboard'
import type { DashboardData, EquipmentItem } from '../types/dashboard'

export type DemoState = 'loaded' | 'empty' | 'error'

// Único ponto de acesso aos dados nesta etapa. Futuras APIs substituirão esta implementação.
export async function getDashboard(state: DemoState = 'loaded'): Promise<DashboardData> {
  await new Promise((resolve) => setTimeout(resolve, 300))
  if (state === 'error') throw new Error('Falha demonstrativa ao carregar os dados')
  if (state === 'empty') return { summary: { registered: 0, recent: 0, outdated: 0, never: 0 }, equipment: [] }
  return dashboardFixture
}

// Busca demonstrativa simples; não define o contrato nem a regra da ISS-019.
export function filterFixtureEquipment(items: EquipmentItem[], query: string): EquipmentItem[] {
  const term = query.trim().toLocaleLowerCase('pt-BR')
  if (!term) return items
  return items.filter((item) =>
    [item.name, item.type, item.assetNumber, item.epc].some((value) =>
      value.toLocaleLowerCase('pt-BR').includes(term),
    ),
  )
}
