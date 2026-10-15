import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RegisteredDetections } from '../components/mapa/RegisteredDetections'
import type { EquipmentItem, ReadSummaryItem } from '../types/dashboard'

let rows: ReadSummaryItem[] = []
vi.mock('../services/live', () => ({ useLiveQuery: () => ({ data: { items: rows } }) }))
afterEach(cleanup)

it('mantém nomes em ordem natural quando contagens e horários mudam nos detectados', () => {
  const now = Date.now()
  const items: EquipmentItem[] = [10, 2, 1].map((id) => ({
    id, nome: `Bomba ${id}`, identificador_interno: `PAT-${id}`, epc: `E200${id}`,
    tipo: 'Bomba', tipo_id: 1, status: 'disponivel', ultima_zona: null,
    ultima_deteccao_em: null, localizacao_desatualizada: false,
  }))
  rows = items.map((asset, index) => ({
    epc: asset.epc!, cadastrada: true, equipamento: { ...asset, ultima_zona: null, ultima_zona_em: null },
    leituras: 100 - index, leituras_por_antena: [],
    ultima_leitura: { em: new Date(now - index * 1000).toISOString() },
  }))
  const { rerender } = render(<RegisteredDetections items={items} onSelect={() => {}}/>)
  const names = () => within(screen.getByRole('table')).getAllByRole('row').slice(1)
    .map((row) => within(row).getByRole('button').textContent?.split('E200')[0])
  expect(names()).toEqual(['Bomba 1', 'Bomba 2', 'Bomba 10'])
  rows = rows.map((row, index) => ({ ...row, leituras: index * 200,
    ultima_leitura: { em: new Date(now - (2 - index) * 1000).toISOString() } }))
  rerender(<RegisteredDetections items={items} onSelect={() => {}}/>)
  expect(names()).toEqual(['Bomba 1', 'Bomba 2', 'Bomba 10'])
})
