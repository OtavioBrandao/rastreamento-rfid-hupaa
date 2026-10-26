import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MapaHUAoVivo } from '../components/mapa/MapaHUAoVivo'
import type { EquipamentoAoVivo, LayoutConfig } from '../services/simulacao'

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body })

const layout: LayoutConfig = {
  cenario: 'hupaa', proporcao: 2, destino: null,
  zonas: [
    { chave: 'zona-1', nome: 'Zona 1', cor: '#2f6fb2', area: { x: 5, y: 5, largura: 40, altura: 60 }, referencia_planta: 'zona-1', restrita: false },
    { chave: 'zona-2', nome: 'Zona 2', cor: '#1f8a70', area: { x: 55, y: 5, largura: 40, altura: 60 }, referencia_planta: 'zona-2', restrita: false },
  ],
  portais: [{ chave: 'portal-1-2', nome: 'Zona 1 ↔ Zona 2', zona_a: 'zona-1', zona_b: 'zona-2', posicao: { x: 50, y: 30 } }],
  leitores: [{ chave: 'leitor-1', nome: 'Leitor 1', reader_id: 'sim-hupaa-01', modelo: 'EZ700', posicao: { x: 50, y: 40 }, antenas: [
    { chave: 'l1-a', nome: 'Antena 1', porta: 1, posicao: { x: 44, y: 30 }, alcance: 4, orientacao: 0, portal: 'portal-1-2', lado: 'a', zona: 'zona-1' },
    { chave: 'l1-b', nome: 'Antena 2', porta: 2, posicao: { x: 56, y: 30 }, alcance: 4, orientacao: 180, portal: 'portal-1-2', lado: 'b', zona: 'zona-2' },
  ] }],
}

const agora = () => new Date().toISOString()
const equipamento = (nome: string, extra: Partial<EquipamentoAoVivo>): EquipamentoAoVivo => ({
  epc: `E2804C41000000000000${nome.length.toString().padStart(4, '0')}`, equipamento: { id: nome.length, nome, tipo: 'Maca', status: 'ativo' },
  estado: 'confirmado', condicoes: ['confirmado'], zona_confirmada: null, zona_leitura: null, antena: null, portal: null, area_restrita: false,
  ultima_leitura_em: null, ultima_deteccao_em: null, recencia: 'recente', ultima_passagem: null, ...extra,
})

describe('mapa do HU ao vivo no dashboard', () => {
  let monitor: Record<string, unknown>
  let sessoes: unknown[]
  beforeEach(() => {
    sessoes = [{ codigo: 'abcdef0123456789', layout_id: 1, cenario: 'hupaa', estado: 'em_execucao', versao: 2, itens: 1, iniciada_em: agora() }]
    monitor = {
      gerado_em: agora(), leituras_total: 10, tags: [], zonas: {}, leitores: [], alertas_restritos: [],
      leituras: [{ id: 1, epc: 'X', reader_id: 'sim-hupaa-01', porta: 2, antena: 'l1-b', lido_em: agora(), rssi: null, equipamento: null }],
      passagens: [{ id: 7, epc: 'E1', portal: 'Zona 1 ↔ Zona 2', direcao: 'a_para_b', direcao_status: 'confirmed', zona_origem: 'Zona 1', zona_destino: 'Zona 2', detectada_em: agora(), equipamento: 'Maca 01' }],
      equipamentos: [
        equipamento('Maca 01', { zona_confirmada: 'zona-2', estado: 'confirmado', condicoes: ['confirmado'] }),
        equipamento('Bomba de infusão 02', { zona_confirmada: 'zona-1', zona_leitura: 'zona-2', antena: 'l1-b', portal: 'portal-1-2', estado: 'em_transito', condicoes: ['em_transito', 'detectado', 'confirmado'], ultima_leitura_em: agora() }),
        equipamento('Cadeira 03 longa', { zona_confirmada: 'zona-2', estado: 'atencao', condicoes: ['atencao', 'confirmado'], recencia: 'desatualizada' }),
        equipamento('Monitor 04 inativo xx', { zona_confirmada: 'zona-1', estado: 'fora_de_servico', condicoes: ['fora_de_servico', 'confirmado'] }),
      ],
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/simulacao/relogio') return json({ agora: agora(), real: agora(), fator: 10, adiantado_s: 1800, acelerado: true, fatores: [1, 10] })
      if (url.pathname === '/api/simulacao/sessoes') return json(sessoes)
      if (url.pathname.endsWith('/monitor')) return json(monitor)
      // A posição virtual do simulador nunca deve aparecer no dashboard.
      return json({ codigo: 'abcdef0123456789', layout_id: 1, cenario: 'hupaa', estado: 'em_execucao', versao: 2, layout,
        itens: [{ id: 'v', nome: 'Posição virtual secreta', tipo: 'Maca', epc: 'E2804C4100000000000099AA', x: 70, y: 30, x0: 70, y0: 30 }],
        iniciada_em: agora(), atualizada_em: agora(), encerrada_em: null, motor: null })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('mostra leitores e antenas configurados, estados do sistema e acelerado visível', async () => {
    const { container } = render(<MapaHUAoVivo items={[]} onSelect={() => undefined} canControlTime fallback={<p>planta estática</p>}/>)
    expect(await screen.findByLabelText('Leitor 1 · EZ700')).toBeInTheDocument()
    expect(screen.getByLabelText('Leitor 1 / Antena 2, lendo agora')).toBeInTheDocument()
    const bomba = await screen.findByRole('button', { name: /^Bomba de infusão 02: Em trânsito · Detectado agora · Passagem confirmada/ })
    expect(bomba).toHaveClass('hu-em_transito')
    expect(screen.getByRole('button', { name: /^Cadeira 03 longa: Atenção/ })).toHaveClass('hu-atencao')
    expect(screen.getByRole('button', { name: /^Monitor 04 inativo xx: Fora de serviço/ })).toHaveClass('hu-fora_de_servico')
    expect(screen.queryByText('Posição virtual secreta')).toBeNull()
    expect(container.querySelector('.sim-clock-selo')?.textContent).toMatch(/acelerado ×10 · \+30 min/)
    expect(await screen.findByText(/Maca 01: saiu de Zona 1 e entrou em Zona 2/)).toBeInTheDocument()
  })

  it('clicar na zona lista os equipamentos dela, sem confirmar quem só foi lido', async () => {
    render(<MapaHUAoVivo items={[]} onSelect={() => undefined} canControlTime={false} fallback={<p>planta estática</p>}/>)
    fireEvent.click(await screen.findByRole('button', { name: 'Zona 2: ver equipamentos' }))
    const painel = screen.getByRole('heading', { name: 'Zona 2' }).closest('section') as HTMLElement
    expect(within(painel).getByText('Maca 01')).toBeInTheDocument()
    expect(within(painel).getByText(/Em trânsito · lido aqui, ainda não confirmado/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+30 min' })).toBeNull()
  })

  it('sem simulação do HU aberta, mostra a planta de referência', async () => {
    sessoes = []
    render(<MapaHUAoVivo items={[]} onSelect={() => undefined} canControlTime fallback={<p>planta estática</p>}/>)
    expect(await screen.findByText('planta estática')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Nenhuma simulação do HU em execução')
  })
})
