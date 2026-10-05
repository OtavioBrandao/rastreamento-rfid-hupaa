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
let assetsFailure: boolean
let activityFailure: boolean

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  window.location.hash = ''
  calls = []
  paginationMode = false
  historyFailure = false
  assetsFailure = false
  activityFailure = false
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    calls.push(String(input))
    const url = new URL(String(input), 'http://localhost')
    if (historyFailure && url.pathname.endsWith('/movimentacoes')) return { ok: false, status: 503 }
    if (assetsFailure && url.pathname === '/api/ativos') return { ok: false, status: 503 }
    if (activityFailure && url.pathname === '/api/dashboard/atividade') return { ok: false, status: 503 }
    let body: unknown
    if (url.pathname === '/api/ativos') {
      const epc = url.searchParams.get('epc')
      const page = Number(url.searchParams.get('page') ?? '1')
      const filtered = epc ? assets.filter((asset) => asset.epc === epc) : assets
      const paginated = paginationMode && url.searchParams.get('page_size') === '20'
      body = { items: paginated && page === 2 ? [item(99)] : page > 1 ? [] : filtered,
        total: paginated ? 21 : filtered.length, page,
        page_size: Number(url.searchParams.get('page_size') ?? '20') }
    } else if (url.pathname === '/api/dashboard/resumo') {
      body = { registered: 3, disponivel: 1, atencao: 1, fora_de_servico: 0, nunca_detectado: 1 }
    } else if (url.pathname === '/api/dashboard/atividade') {
      body = { items: [{ id: 10, equipamento_id: 1, equipamento_nome: 'Maca 1',
        zona_origem: 'Zona 0', zona_destino: 'Zona 1',
        movimentada_em: '2026-09-26T12:00:00Z', origem_registro: 'passagem_automatica' }] }
    } else if (url.pathname === '/api/laboratorio/leituras') {
      body = { items: url.searchParams.get('after_id') === '0' ? [{ id: 8, epc: assets[2].epc,
        antena_porta: 1, recebido_em: '2026-09-26T12:00:00Z' }] : [], next_id: 8 }
    } else if (url.pathname.match(/^\/equipamentos\/\d+\/movimentacoes$/)) {
      body = { items: [{ id: 10, origem_registro: 'automatico', zona_origem: 'Zona 0',
        zona_destino: 'Zona 1', movimentada_em: '2026-09-26T12:00:00Z',
        registrado_em: '2026-09-26T12:10:00Z', justificativa: null }],
        page: 1, size: 20, total: 1, pages: 1 }
    } else if (url.pathname === '/api/leituras/resumo') {
      const registered = [
        { epc: assets[1].epc, cadastrada: true, equipamento: { id: 2, nome: 'Maca 2', identificador_interno: 'PAT-2', ultima_zona: null, ultima_zona_em: null },
          leituras: 610, leituras_por_antena: [{ antena_id: 1, leituras: 610 }], ultima_leitura: { em: new Date().toISOString(), leitor: 'reader-01', porta: 1, zona: 'Sala A' } },
        { epc: assets[0].epc, cadastrada: true, equipamento: { id: 1, nome: 'Maca 1', identificador_interno: 'PAT-1', ultima_zona: 'Zona 1', ultima_zona_em: '2026-09-26T12:00:00Z' },
          leituras: 0, leituras_por_antena: [], ultima_leitura: null },
      ]
      const loose = { epc: '3034000000000C400000012F', cadastrada: false, equipamento: null, leituras: 644,
        leituras_por_antena: [{ antena_id: 1, leituras: 563 }, { antena_id: 2, leituras: 81 }],
        ultima_leitura: { em: new Date().toISOString(), leitor: 'reader-01', porta: 1, zona: 'Sala A' } }
      const only = url.searchParams.get('somente_cadastradas') === 'true'
      body = { janela_segundos: Number(url.searchParams.get('janela_segundos')), gerado_em: new Date().toISOString(),
        total_leituras: only ? 610 : 1254, tags_detectadas: only ? 1 : 2, cadastradas_detectadas: 1, cadastradas_sem_leitura: 1,
        nao_cadastradas: only ? 0 : 1,
        antenas: [{ antena_id: 1, leitor: 'reader-01', porta: 1, zona: 'Sala A' }, { antena_id: 2, leitor: 'reader-01', porta: 2, zona: 'Sala B' }],
        items: only ? registered : [...registered, loose] }
    } else if (url.pathname === '/tipos-equipamento') body = { items: [{ id: 1, nome: 'Maca' }] }
    else if (url.pathname === '/portais') body = { items: [{ id: 10, nome: 'Portal de teste RFID', zona_a_id: 3, zona_b_id: 4, ativo: true }], pages: 1 }
    else body = [{ setores: [{ zonas: [{ id: 1, nome: 'Zona 1', referencia_planta: 'zona-1', ativo: true }, { id: 3, nome: 'Sala A', referencia_planta: 'sala-a', ativo: true }, { id: 4, nome: 'Sala B', referencia_planta: 'sala-b', ativo: true }] }] }]
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
    expect(await screen.findByRole('heading', { name: 'Movimentações recentes' })).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Movimentações recentes' })).toHaveTextContent('Maca 1 · Zona 0 → Zona 1')
    expect(calls.filter((url) => url.includes('/api/dashboard/resumo'))).toHaveLength(1)
    expect(calls.filter((url) => url.includes('/api/dashboard/atividade'))).toHaveLength(1)
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
    expect(await screen.findByRole('heading', { name: 'Sem zona confirmada' })).toBeInTheDocument()
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

  it('mostra leituras por tag separando cadastradas de avulsas', async () => {
    render(<App/>)
    fireEvent.click(screen.getByRole('link', { name: 'Leituras' }))
    const table = await within(await screen.findByRole('region', { name: 'Tags lidas' })).findByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Maca 2')
    expect(rows[1]).toHaveTextContent('610')
    expect(rows[1]).toHaveTextContent('Antena 1 · Sala A')
    expect(rows[3]).toHaveTextContent('Não cadastrada')
    expect(rows[3]).toHaveTextContent('563')
    expect(rows[3]).toHaveTextContent('81')
    expect(within(table).getByRole('columnheader', { name: 'Antena 2 · Sala B' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Somente tags cadastradas' }))
    await waitFor(() => expect(calls.some((url) => url.includes('somente_cadastradas=true'))).toBe(true))
    await waitFor(() => expect(screen.queryByText('Não cadastrada')).not.toBeInTheDocument())
  })

  it('lista equipamentos detectados abaixo dos mapas e indica leitura sem zona', async () => {
    assets[1].ultima_leitura = { em: new Date().toISOString(), leitor: 'reader-01', porta: 1, zona: 'Sala A' }
    try {
      render(<App/>)
      const dashboard = await screen.findByRole('table')
      expect(within(dashboard).getByText('Sem zona confirmada')).toBeInTheDocument()
      expect(within(dashboard).getByText(/Lida agora · Antena 1 · Sala A/)).toBeInTheDocument()
      fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
      const region = await screen.findByRole('region', { name: 'Detectados recentemente' })
      const rows = await within(region).findAllByRole('row')
      expect(rows[1]).toHaveTextContent('Maca 2')
      expect(rows[1]).toHaveTextContent('Antena 1 · Sala A')
      expect(rows[2]).toHaveTextContent('Sem leitura recente')
      fireEvent.click(screen.getByRole('tab', { name: 'Laboratório de Testes (EASY)' }))
      const labRegion = within(screen.getByRole('tabpanel', { name: 'Laboratório de Testes (EASY)' })).getByRole('region', { name: 'Detectados recentemente' })
      fireEvent.click(await within(labRegion).findByRole('button', { name: /Maca 2/ }))
      expect(screen.getByRole('dialog')).toHaveTextContent('Antena 1 · Sala A')
    } finally { delete assets[1].ultima_leitura }
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

  it('limpa a lista antiga ao falhar uma busca e recupera no retry', async () => {
    render(<App/>)
    expect(await screen.findByRole('table')).toBeInTheDocument()
    assetsFailure = true
    fireEvent.change(screen.getByRole('searchbox', { name: 'Nome ou patrimônio' }), { target: { value: 'Maca' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    expect(await screen.findByText('Não foi possível carregar os equipamentos.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    assetsFailure = false
    fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('ignora resposta atrasada de uma busca anterior após erro', async () => {
    render(<App/>)
    expect(await screen.findByRole('table')).toBeInTheDocument()
    const originalFetch = globalThis.fetch
    let releaseOld!: (value: { ok: boolean; json: () => Promise<unknown> }) => void
    vi.stubGlobal('fetch', vi.fn((input: string, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/ativos' && url.searchParams.get('q') === 'Antiga') {
        return new Promise((resolve) => { releaseOld = resolve })
      }
      if (url.pathname === '/api/ativos' && url.searchParams.get('q') === 'Nova') {
        return Promise.resolve({ ok: false, status: 503 })
      }
      return originalFetch(input, init)
    }))
    const search = screen.getByRole('searchbox', { name: 'Nome ou patrimônio' })
    fireEvent.change(search, { target: { value: 'Antiga' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    await waitFor(() => expect(releaseOld).toBeDefined())
    fireEvent.change(search, { target: { value: 'Nova' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    expect(await screen.findByText('Não foi possível carregar os equipamentos.')).toBeInTheDocument()
    releaseOld({ ok: true, json: async () => ({ items: assets, total: 3, page: 1, page_size: 20 }) })
    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument())
  })

  it('exibe erro da atividade e recupera sem dados antigos', async () => {
    activityFailure = true
    render(<App/>)
    const region = screen.getByRole('region', { name: 'Movimentações recentes' })
    expect(await within(region).findByText(/Não foi possível carregar as movimentações/)).toBeInTheDocument()
    expect(region).not.toHaveTextContent('Zona 0 → Zona 1')
    activityFailure = false
    fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
    await waitFor(() => expect(region).toHaveTextContent('Maca 1 · Zona 0 → Zona 1'))
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
    fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
    expect(await screen.findByText('Zona 0 → Zona 1')).toBeInTheDocument()
  })
})
