import { describe, expect, it } from 'vitest'
import { zonePriority } from '../components/mapa/MapDataTabs'
import type { EquipmentItem } from '../types/dashboard'

const now = Date.parse('2026-10-15T12:00:00Z')
const item = (id: number, nome: string, overrides: Partial<EquipmentItem> = {}): EquipmentItem => ({
  id, nome, identificador_interno: `PAT-${id}`, tipo: 'Maca', tipo_id: 1, epc: null, status: 'disponivel',
  ultima_zona: null, ultima_deteccao_em: null, localizacao_desatualizada: false, ...overrides,
})
const reading = (seconds: number) => ({ em: new Date(now - seconds * 1000).toISOString() })

describe('prioridade estável nas tabelas do mapa', () => {
  it('mantém trânsito junto no topo, com lidos agora primeiro, antes de atenção', () => {
    const rows = [
      item(1, 'A atenção', { status: 'atencao', localizacao_desatualizada: true }),
      item(2, 'B trânsito'),
      item(3, 'C lida agora sem zona', { status: 'nunca_detectado', ultima_leitura: reading(1) }),
      item(4, 'D trânsito lido agora', { ultima_leitura: reading(25) }),
      item(5, 'E sem zona', { status: 'nunca_detectado' }),
      item(6, 'F fora de serviço', { status: 'fora_de_servico' }),
    ]
    expect(zonePriority(rows, now).map((entry) => entry.id)).toEqual([4, 2, 3, 1, 5, 6])
    expect(rows.map((entry) => entry.id)).toEqual([1, 2, 3, 4, 5, 6])
  })

  it('ordena nomes e números sem trocar posições com novas leituras', () => {
    const rows = [item(1, 'Bomba 10', { ultima_leitura: reading(0) }),
      item(2, 'Bomba 2', { ultima_leitura: reading(20) }),
      item(3, 'Bomba 1', { ultima_leitura: reading(10) }),
      item(4, 'Bomba 2', { ultima_leitura: reading(1) })]
    expect(zonePriority(rows, now).map((entry) => entry.id)).toEqual([3, 2, 4, 1])
    rows[1].ultima_leitura = reading(0)
    expect(zonePriority(rows, now).map((entry) => entry.id)).toEqual([3, 2, 4, 1])
  })

  it('só muda de grupo ao expirar a janela de presença', () => {
    const rows = [item(1, 'Bomba 1'), item(2, 'Bomba 2', { ultima_leitura: reading(0) })]
    expect(zonePriority(rows, now).map((entry) => entry.id)).toEqual([2, 1])
    expect(zonePriority(rows, now + 31_000).map((entry) => entry.id)).toEqual([1, 2])
  })
})
