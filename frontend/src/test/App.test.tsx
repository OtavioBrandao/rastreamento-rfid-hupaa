import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EquipmentItem } from '../types/dashboard'

const item = (id: number, overrides: Partial<EquipmentItem> = {}): EquipmentItem => ({
  id, nome: `Maca ${id}`, identificador_interno: `PAT-${id}`, tipo: 'Maca', tipo_id: 1,
  epc: `E2000017221101441890A00${id}`, status: 'disponivel',
  ultima_zona: { id: 1, nome: 'Zona 1', referencia_planta: 'zona-1',
    andar: '2º andar', setor: 'Bloco B', caminho: '2º andar → Bloco B → Zona 1' },
  ultima_deteccao_em: '2026-09-26T12:00:00Z', localizacao_desatualizada: false, ...overrides,
})
const assets = [item(1, { status: 'atencao', localizacao_desatualizada: true }), item(2, {
  status: 'nunca_detectado', ultima_zona: null, ultima_deteccao_em: null,
  localizacao_desatualizada: null,
}), item(3, { ultima_zona: { id: 3, nome: 'Zona A', referencia_planta: 'sala-a',
  andar: '2º andar', setor: 'Bloco B', caminho: '2º andar → Bloco B → Zona A' } })]
let calls: string[]
let paginationMode: boolean
let historyFailure: boolean

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  window.location.hash = ''
  calls = []
  paginationMode = false
  historyFailure = false
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    calls.push(String(input))
    const url = new URL(String(input), 'http://localhost')
    if (historyFailure && url.pathname.endsWith('/movimentacoes')) return { ok: false, status: 503 }
    let body: unknown
    if (url.pathname === '/api/ativos') {
      const epc = url.searchParams.get('epc')
      const page = Number(url.searchParams.get('page') ?? '1')
      const filtered = epc ? assets.filter((asset) => asset.epc === epc) : assets
      const paginated = paginationMode && url.searchParams.get('page_size') === '20'
      body = { items: paginated && page === 2 ? [item(99)] : page > 1 ? [] : filtered,
        total: paginated ? 21 : filtered.length, page,
        page_size: Number(url.searchParams.get('page_size') ?? '20') }
    } else if (url.pathname === '/api/laboratorio/leituras') {
      body = { items: url.searchParams.get('after_id') === '0' ? [{ id: 8, epc: assets[2].epc,
        antena_porta: 1, recebido_em: '2026-09-26T12:00:00Z' }] : [], next_id: 8 }
    } else if (url.pathname.match(/^\/equipamentos\/\d+\/movimentacoes$/)) {
      body = { items: [{ id: 10, origem_registro: 'automatico', zona_origem: 'Zona 0',
        zona_destino: 'Zona 1', movimentada_em: '2026-09-26T12:00:00Z',
        registrado_em: '2026-09-26T12:10:00Z', justificativa: null }],
        page: 1, size: 20, total: 1, pages: 1 }
    } else if (url.pathname === '/tipos-equipamento') body = { items: [{ id: 1, nome: 'Maca' }] }
    else body = [{ setores: [{ zonas: [{ id: 1, nome: 'Zona 1' }] }] }]
    return { ok: true, json: async () => body }
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('integração da busca', () => {
  it('mostra a badge de localização na tabela e no detalhe; preserva null', async () => {
    render(<App/>)
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Localização pode estar desatualizada')).toBeInTheDocument()
    expect(within(table).getByText('Nenhuma localização registrada')).toBeInTheDocument()
    expect(within(table).getByText('2º andar → Bloco B → Zona 1')).toBeInTheDocument()
    expect(within(table).getAllByText(/26\/09\/2026.*09:00/).length).toBeGreaterThan(0)
    fireEvent.click(within(table).getByRole('button', { name: /Maca 1/ }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Localização pode estar desatualizada')
    expect(screen.getByRole('dialog')).toHaveTextContent('2º andar → Bloco B → Zona 1')
    fireEvent.click(screen.getByRole('button', { name: 'Ver histórico completo' }))
    expect(await screen.findByText('Zona 0 → Zona 1')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('26/09/2026')
    expect(calls.some((url) => url.includes('/equipamentos/1/movimentacoes?page=1&size=20'))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Fechar painel' }))
    fireEvent.change(screen.getByRole('searchbox', { name: 'EPC' }), { target: { value: assets[0].epc } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    await waitFor(() => expect(calls.some((url) => url.includes(`epc=${assets[0].epc}`))).toBe(true))
  })

  it('filtra EPC nos dois modos e não plota ativo nunca detectado', async () => {
    render(<App/>)
    fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
    expect(await screen.findByRole('heading', { name: 'Ainda não detectados' })).toBeInTheDocument()
    expect(screen.getByText('Maca 2')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /1 equipamento.*Última zona/ })).toHaveLength(1)
    fireEvent.click(screen.getByRole('tab', { name: 'Laboratório de Testes (EASY)' }))
    expect(screen.getByRole('tabpanel', { name: 'Laboratório de Testes (EASY)' })).toBeInTheDocument()
    expect(await within(screen.getByRole('region', { name: 'Leituras das antenas' })).findByText(assets[2].epc!)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /1 equipamento.*Última zona: Sala A/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /Antena A.*Sala A/ })).toHaveClass('marker-pulse'))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Consultar EPC' }), { target: { value: 'FFFFFFFFFFFFFFFFFFFFFFFF' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar tag' }))
    expect(await screen.findByText('Nenhum ativo associado a este EPC.')).toBeInTheDocument()
  })

  it('usa a paginação real do servidor', async () => {
    paginationMode = true
    render(<App/>)
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', { name: 'Próxima' }))
    expect(await screen.findByRole('button', { name: /Maca 99/ })).toBeInTheDocument()
    expect(calls.some((url) => url.includes('page=2') && url.includes('page_size=20'))).toBe(true)
  })

  it('exibe erro recuperável quando a API falha', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })))
    render(<App/>)
    expect(await screen.findByText('Não foi possível carregar os equipamentos.')).toBeInTheDocument()
  })

  it('não exibe histórico antigo quando a consulta falha e permite nova tentativa', async () => {
    render(<App/>)
    const table = await screen.findByRole('table')
    fireEvent.click(within(table).getByRole('button', { name: /Maca 1/ }))
    historyFailure = true
    fireEvent.click(screen.getByRole('button', { name: 'Ver histórico completo' }))
    expect(await screen.findByText(/Não foi possível carregar o histórico/)).toBeInTheDocument()
    expect(screen.queryByText('Zona 0 → Zona 1')).not.toBeInTheDocument()
    historyFailure = false
    fireEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }))
    expect(await screen.findByText('Zona 0 → Zona 1')).toBeInTheDocument()
  })
})
