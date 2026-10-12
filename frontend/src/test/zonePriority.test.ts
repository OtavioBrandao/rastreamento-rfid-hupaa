import { describe, expect, it } from 'vitest'
import { zonePriority } from '../components/mapa/MapDataTabs'
import type { EquipmentItem } from '../types/dashboard'

const item = (id: number, nome: string, overrides: Partial<EquipmentItem>): EquipmentItem => ({
  id, nome, identificador_interno: `PAT-${id}`, tipo: 'Maca', tipo_id: 1, epc: null, status: 'disponivel',
  ultima_zona: null, ultima_deteccao_em: null, localizacao_desatualizada: false, ...overrides,
})

describe('zonePriority', () => {
  it('coloca em trânsito antes de atenção e desatualizados por último', () => {
    const ordenados = zonePriority([
      item(1, 'A desatualizada', { status: 'disponivel', localizacao_desatualizada: true }),
      item(2, 'B atenção', { status: 'atencao' }),
      item(3, 'C em trânsito', { status: 'disponivel' }),
      item(4, 'D desatualizada', { status: 'atencao', localizacao_desatualizada: true }),
      item(5, 'B em trânsito', { status: 'disponivel' }),
    ])
    expect(ordenados.map((entry) => entry.id)).toEqual([5, 3, 2, 1, 4])
  })
})
