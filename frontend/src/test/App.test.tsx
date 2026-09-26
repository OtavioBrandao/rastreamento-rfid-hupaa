import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EquipmentItem } from '../types/dashboard'

const item = (id: number, overrides: Partial<EquipmentItem> = {}): EquipmentItem => ({
  id, nome: `Maca ${id}`, identificador_interno: `PAT-${id}`, tipo: 'Maca', tipo_id: 1,
  epc: `E2000017221101441890A00${id}`, status: 'disponivel',
  ultima_zona: { id: 1, nome: 'Zona 1', referencia_planta: 'zona-1' },
  ultima_deteccao_em: '2026-09-26T12:00:00Z', localizacao_desatualizada: false, ...overrides,
})
const assets = [item(1, { status: 'atencao', localizacao_desatualizada: true }), item(2, {
  status: 'nunca_detectado', ultima_zona: null, ultima_deteccao_em: null,
  localizacao_desatualizada: null,
})]
let calls: string[]
let paginationMode: boolean

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  window.location.hash = ''
  calls = []
  paginationMode = false
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    calls.push(String(input))
    const url = new URL(String(input), 'http://localhost')
    let body: unknown
    if (url.pathname === '/api/ativos') {
      const epc = url.searchParams.get('epc')
      const page = Number(url.searchParams.get('page') ?? '1')
      const filtered = epc ? assets.filter((asset) => asset.epc === epc) : assets
      const paginated = paginationMode && url.searchParams.get('page_size') === '20'
      body = { items: paginated && page === 2 ? [item(99)] : page > 1 ? [] : filtered,
        total: paginated ? 21 : filtered.length, page,
        page_size: Number(url.searchParams.get('page_size') ?? '20') }
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
    fireEvent.click(within(table).getByRole('button', { name: /Maca 1/ }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Localização pode estar desatualizada')
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
    fireEvent.click(screen.getByRole('button', { name: 'Leitura simulada na Sala A' }))
    expect(within(screen.getByRole('region', { name: 'Log simulado de leituras' })).getByText('Sala A', { exact: false })).toBeInTheDocument()
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
})
