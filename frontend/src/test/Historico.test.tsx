import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PresenceBadge, PresenceDot, PRESENCE_FRESH_MS } from '../components/DashboardParts'
import { JourneyBlocks, JourneySummary } from '../components/equipamento/MovementJourneys'
import type { Journeys } from '../services/dashboard'

afterEach(() => { cleanup(); vi.useRealTimers() })

const etapa = (id: number, de: string, para: string, ordem: string, em: string) => ({
  movimentacao_id: id, de, para, em, portal: `Portal para ${para === 'Circulação' ? de : para}`, leitor: 'Leitor 1',
  antenas: ordem.split(' → ').map((porta, i) => ({ porta: Number(porta), lido_em: new Date(Date.parse(em) - (1 - i) * 1500).toISOString() })),
  ordem, travessia_s: 1.5, origem_registro: 'passagem_automatica',
})

const historico: Journeys = {
  em_circulacao: true,
  ultima_observacao: { em: '2026-10-27T13:05:00Z', zona: 'Zona 2', leitor: 'Leitor 2', porta: 1 },
  items: [
    { tipo: 'observacao', titulo: 'Visto perto da Zona 2', em: '2026-10-27T13:05:00Z', inicio: '2026-10-27T13:04:50Z', fim: '2026-10-27T13:05:00Z',
      completo: false, zona: 'Zona 2', leitor: 'Leitor 2', porta: 1, leituras: 12, zona_confirmada_no_momento: 'Circulação' },
    { tipo: 'percurso', titulo: 'Zona 2 → Circulação', origem: 'Zona 2', destino: 'Circulação', em: '2026-10-27T13:04:00Z', completo: false,
      saida_registrada: true, tempo_na_circulacao_s: null, etapas: [etapa(3, 'Zona 2', 'Circulação', '2 → 1', '2026-10-27T13:04:00Z')] },
    { tipo: 'percurso', titulo: 'Zona 1 → Zona 2', origem: 'Zona 1', destino: 'Zona 2', em: '2026-10-27T13:02:00Z', completo: true,
      saida_registrada: true, tempo_na_circulacao_s: 60, etapas: [etapa(1, 'Zona 1', 'Circulação', '2 → 1', '2026-10-27T13:01:00Z'), etapa(2, 'Circulação', 'Zona 2', '1 → 2', '2026-10-27T13:02:00Z')] },
    { tipo: 'percurso', titulo: 'Origem desconhecida → Zona 1', origem: null, destino: 'Zona 1', em: '2026-10-27T12:00:00Z', completo: true,
      saida_registrada: false, tempo_na_circulacao_s: null, etapas: [etapa(0, 'Circulação', 'Zona 1', '1 → 2', '2026-10-27T12:00:00Z')] },
  ],
}

describe('histórico do equipamento', () => {
  it('resumo: até três acontecimentos, com observação separada de deslocamento', () => {
    render(<JourneySummary data={historico}/>)
    const linhas = screen.getAllByRole('listitem')
    expect(linhas).toHaveLength(3)
    expect(linhas[0]).toHaveTextContent('Visto perto da Zona 2 — entrada não confirmada')
    expect(linhas[0]).toHaveTextContent('Observação')
    expect(linhas[1]).toHaveTextContent('Zona 2 → Circulação')
    expect(linhas[1]).toHaveTextContent('Saída confirmada · parado na circulação')
    expect(linhas[2]).toHaveTextContent('Zona 1 → Zona 2')
    expect(linhas[2]).toHaveTextContent('Percurso concluído')
    expect(screen.queryByText(/Origem desconhecida/)).toBeNull()  // é o 4º: fica só no completo
  })

  it('histórico completo: um bloco por deslocamento, com etapas, antenas, horários e duração', () => {
    render(<JourneyBlocks data={historico}/>)
    const bloco = screen.getByRole('heading', { name: /Zona 1 → Zona 2/ }).closest('article')!
    const etapas = within(bloco).getAllByRole('listitem')
    expect(etapas[0]).toHaveTextContent('Etapa 1: Zona 1 → Circulação')
    expect(etapas[0]).toHaveTextContent('antenas 2 → 1')
    expect(etapas[1]).toHaveTextContent('Etapa 2: Circulação → Zona 2')
    expect(etapas[1]).toHaveTextContent('antenas 1 → 2')
    expect(etapas[1]).toHaveTextContent(/Leituras usadas: Antena 1 às .*; Antena 2 às .*\(travessia em 2 s\)/)
    expect(bloco).toHaveTextContent('Tempo na circulação entre as etapas: 1 min 0 s')
    const incompleto = screen.getByRole('heading', { name: /Zona 2 → Circulação/ }).closest('article')!
    expect(incompleto).toHaveTextContent('Percurso incompleto: parado na circulação')
    const desconhecida = screen.getByRole('heading', { name: /Origem desconhecida → Zona 1/ }).closest('article')!
    expect(desconhecida).toHaveTextContent('nenhuma localização confirmada antes desta entrada')
    expect(screen.getByRole('heading', { name: /Visto perto da Zona 2/ })).toHaveTextContent('observação, sem deslocamento')
  })
})

describe('indicador de leitura recente', () => {
  it('verde por 90 s desde a última leitura; depois cinza com "Sem leitura recente"', () => {
    vi.useFakeTimers()
    const agora = new Date('2026-10-27T13:00:00Z')
    vi.setSystemTime(agora)
    expect(PRESENCE_FRESH_MS).toBe(90_000)
    const leitura = (segundos: number) => ({ em: new Date(agora.getTime() - segundos * 1000).toISOString(), leitor: 'Leitor 1', porta: 1, zona: 'Zona 1' })
    const { rerender, container } = render(<><PresenceBadge reading={leitura(89)}/><PresenceDot reading={leitura(89)}/></>)
    expect(screen.getByText(/Leitura recente · Antena 1 · Zona 1/)).toBeInTheDocument()
    expect(container.querySelector('.presence-dot.fresh')).not.toBeNull()
    rerender(<><PresenceBadge reading={leitura(91)}/><PresenceDot reading={leitura(91)}/></>)
    expect(screen.getAllByText('Sem leitura recente')).toHaveLength(2)
    expect(container.querySelector('.presence-dot.fresh')).toBeNull()
    // Leitura nova recomeça a contagem.
    rerender(<><PresenceBadge reading={leitura(1)}/><PresenceDot reading={leitura(1)}/></>)
    expect(container.querySelector('.presence-dot.fresh')).not.toBeNull()
  })
})
