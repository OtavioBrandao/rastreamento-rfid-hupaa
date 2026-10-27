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
// ISS-027: o painel só monta com sessão; /auth/me responde uma sessão de administrador.
const SESSAO_ADMIN = {
  usuario: { id: 1, nome: 'Ana Admin', email: 'ana@hupaa.example', perfil: 'administrador',
    ativo: true, deve_trocar_senha: false },
  sessao_expira_em: '2026-09-26T20:00:00Z',
  permissoes: ['equipamentos:consultar', 'equipamentos:alterar'],
}
const sessionResponse = () => ({ ok: true, status: 200, json: async () => SESSAO_ADMIN })

/** Renderiza e ESPERA o painel montar (a sessão é consultada antes). */
async function renderApp() {
  render(<App/>)
  await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })
}
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
    if (url.pathname === '/auth/me') return sessionResponse()
    if (historyFailure && url.pathname.endsWith('/percursos')) return { ok: false, status: 503 }
    if (assetsFailure && url.pathname === '/api/ativos') return { ok: false, status: 503 }
    if (activityFailure && url.pathname === '/api/dashboard/atividade') return { ok: false, status: 503 }
    let body: unknown
    const porId = url.pathname.match(/^\/api\/ativos\/(\d+)$/)
    if (porId) {
      // ISS-025: o painel de detalhe recarrega o equipamento pelo ID.
      const found = assets.find((asset) => asset.id === Number(porId[1]))
      return found ? { ok: true, status: 200, json: async () => found } : { ok: false, status: 404 }
    }
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
    } else if (url.pathname.match(/^\/equipamentos\/\d+\/percursos$/)) {
      body = { em_circulacao: false, ultima_observacao: null, items: [{ tipo: 'percurso', titulo: 'Zona 0 → Zona 1', origem: 'Zona 0',
        destino: 'Zona 1', em: '2026-09-26T12:00:00Z', completo: true, saida_registrada: true, mesma_zona: false,
        tempo_na_circulacao_s: null, etapas: [{ movimentacao_id: 10, de: 'Zona 0', para: 'Zona 1', em: '2026-09-26T12:00:00Z',
          portal: 'Portal 1', leitor: 'Leitor 1', antenas: [{ porta: 1, lido_em: '2026-09-26T11:59:58Z' }, { porta: 2, lido_em: '2026-09-26T12:00:00Z' }],
          ordem: '1 → 2', travessia_s: 2, origem_registro: 'passagem_automatica' }] }] }
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
  it('solicita prioridade global no inventário e a preserva nos filtros e páginas', async () => {
    paginationMode = true
    await renderApp()
    await screen.findByRole('button', { name: /Maca 1/ })
    const assetCalls = () => calls.map((call) => new URL(call, 'http://localhost')).filter((url) => url.pathname === '/api/ativos')
    expect(assetCalls().at(-1)!.searchParams.get('sort')).toBe('prioridade')
    fireEvent.click(screen.getByRole('button', { name: 'Próxima' }))
    await screen.findByRole('button', { name: /Maca 99/ })
    expect(assetCalls().at(-1)!.searchParams.get('page')).toBe('2')
    fireEvent.change(screen.getByLabelText('Status', { exact: true }), { target: { value: 'atencao' } })
    await waitFor(() => expect(assetCalls().at(-1)!.searchParams.get('status')).toBe('atencao'))
    expect(assetCalls().every((url) => url.searchParams.get('sort') === 'prioridade')).toBe(true)
    expect(assetCalls().at(-1)!.searchParams.get('page')).toBe('1')
  })

  it('mostra a badge de localização na tabela e no detalhe; preserva null', async () => {
    await renderApp()
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
    // Resumo já aberto com o percurso; o histórico completo traz as etapas e as evidências.
    expect(await within(screen.getByRole('dialog')).findByText(/Percurso concluído/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver histórico completo' }))
    expect((await screen.findAllByText('Zona 0 → Zona 1')).length).toBe(2)  // resumo e título do bloco
    expect(screen.getByText(/Portal 1 · Leitor 1 · antenas 1 → 2/)).toBeInTheDocument()
    expect(screen.getByText(/Leituras usadas: Antena 1 às .*; Antena 2 às .*travessia em 2 s/)).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('26/09/2026')
    expect(calls.some((url) => url.includes('/equipamentos/1/percursos'))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Fechar painel' }))
    fireEvent.change(screen.getByRole('searchbox', { name: 'EPC' }), { target: { value: assets[0].epc } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    await waitFor(() => expect(calls.some((url) => url.includes(`epc=${assets[0].epc}`))).toBe(true))
  })

  it('filtra EPC nos dois modos e não plota ativo nunca detectado', async () => {
    await renderApp()
    fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
    fireEvent.click(await screen.findByRole('tab', { name: /Zona não confirmada/ }))
    const semZona = screen.getByRole('tabpanel', { name: /Zona não confirmada/ })
    expect(within(semZona).getByRole('button', { name: /Maca 2/ })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /1 equipamento em/ })).toHaveLength(1)
    fireEvent.click(screen.getByRole('tab', { name: 'Laboratório de Testes (EASY)' }))
    expect(screen.getByRole('tabpanel', { name: 'Laboratório de Testes (EASY)' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Leituras das antenas' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /1 equipamento em Sala A/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /Antena A.*Sala A/ })).toHaveClass('marker-pulse'))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Consultar EPC' }), { target: { value: 'FFFFFFFFFFFFFFFFFFFFFFFF' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar tag' }))
    expect(await screen.findByText('Nenhum ativo associado a este EPC.')).toBeInTheDocument()
  })

  it('abre o cluster da zona, troca as abas pela tabela da zona e restaura ao fechar', async () => {
    await renderApp()
    fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
    fireEvent.click(await screen.findByRole('tab', { name: 'Laboratório de Testes (EASY)' }))
    const marker = await screen.findByRole('button', { name: /1 equipamento em Sala A/ })
    expect(marker).toHaveTextContent('1')
    expect(marker).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(marker)
    const dot = screen.getByRole('button', { name: /^Maca 3: .*Abrir detalhes/ })
    expect(dot).toHaveClass('marker-individual')
    expect(screen.queryByRole('tablist', { name: 'Dados da planta' })).not.toBeInTheDocument()
    const zoneTable = screen.getByRole('region', { name: 'Equipamentos em Sala A' })
    expect(within(zoneTable).getAllByRole('row')).toHaveLength(2)
    fireEvent.click(dot)
    expect(screen.getByRole('dialog')).toHaveTextContent('Maca 3')
    fireEvent.click(screen.getByRole('button', { name: 'Fechar painel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Fechar zona e voltar às abas' }))
    expect(screen.queryByRole('button', { name: /^Maca 3: / })).not.toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'Dados da planta' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sala A: clique para ver os equipamentos' }))
    expect(screen.getByRole('button', { name: /^Maca 3: / })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('button', { name: /^Maca 3: / })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Equipamentos detectados/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('mostra leituras por tag separando cadastradas de avulsas', async () => {
    await renderApp()
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
      expect(within(dashboard).getByText('Zona não confirmada')).toBeInTheDocument()
      expect(within(dashboard).getByText(/Leitura recente · Antena 1 · Sala A/)).toBeInTheDocument()
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
    await renderApp()
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', { name: 'Próxima' }))
    expect(await screen.findByRole('button', { name: /Maca 99/ })).toBeInTheDocument()
    expect(calls.some((url) => url.includes('page=2') && url.includes('page_size=20'))).toBe(true)
  })

  it('exibe erro recuperável quando a API falha', async () => {
    // Sessão válida; só os dados falham (senão o teste veria o login, não o erro de dados).
    vi.stubGlobal('fetch', vi.fn(async (input: string) =>
      new URL(String(input), 'http://localhost').pathname === '/auth/me'
        ? sessionResponse() : { ok: false, status: 503 }))
    await renderApp()
    expect(await screen.findByText('Não foi possível carregar os equipamentos.')).toBeInTheDocument()
  })

  it('limpa a lista antiga ao falhar uma busca e recupera no retry', async () => {
    await renderApp()
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
    await renderApp()
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

  it('permite consultar ensaios arquivados sem misturá-los na visão inicial', async () => {
    await renderApp()
    await waitFor(() => expect(calls.some((url) => url.includes('/api/ativos?') && url.includes('somente_ativos=true'))).toBe(true))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mostrar cadastros inativos (ensaios arquivados)' }))
    await waitFor(() => expect(calls.some((url) => url.includes('/api/ativos?') && url.includes('somente_ativos=false'))).toBe(true))
    await waitFor(() => expect(calls.some((url) => url.includes('/api/dashboard/resumo?somente_ativos=false'))).toBe(true))
  })

  it('exibe erro da atividade e recupera sem dados antigos', async () => {
    activityFailure = true
    await renderApp()
    const region = screen.getByRole('region', { name: 'Movimentações recentes' })
    expect(await within(region).findByText(/Não foi possível carregar as movimentações/)).toBeInTheDocument()
    expect(region).not.toHaveTextContent('Zona 0 → Zona 1')
    activityFailure = false
    fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
    await waitFor(() => expect(region).toHaveTextContent('Maca 1 · Zona 0 → Zona 1'))
  })

  it('não exibe histórico antigo quando a consulta falha e permite nova tentativa', async () => {
    await renderApp()
    const table = await screen.findByRole('table')
    historyFailure = true
    fireEvent.click(within(table).getByRole('button', { name: /Maca 1/ }))
    expect(await screen.findByText(/Não foi possível carregar o histórico/)).toBeInTheDocument()
    expect(screen.queryByText('Zona 0 → Zona 1')).not.toBeInTheDocument()
    historyFailure = false
    fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
    expect(await screen.findByText('Zona 0 → Zona 1')).toBeInTheDocument()
  })
})
