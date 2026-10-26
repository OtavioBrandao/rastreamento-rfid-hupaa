import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../App'
import { getMapTopology } from '../services/dashboard'

let revision: number
let fail: string
let calls: string[]
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
const SESSAO_ADMIN = {
  usuario: { id: 1, nome: 'Ana Admin', email: 'ana@hupaa.example', perfil: 'administrador', ativo: true, deve_trocar_senha: false },
  sessao_expira_em: '2026-10-05T20:00:00Z',
  permissoes: ['equipamentos:consultar', 'equipamentos:alterar', 'laboratorio:consultar'],
}
const ativoAtual = (single: boolean) => {
  const zones = [{ id: 31, nome: 'Sala A', referencia_planta: 'sala-a', ativo: true },
    { id: 82, nome: 'Sala B', referencia_planta: 'sala-b', ativo: true }]
  const item = { id: 1, nome: `Maca ${revision}`, identificador_interno: 'PAT-1', epc: 'E20001', tipo: 'Maca', tipo_id: 1, status: 'disponivel', localizacao_desatualizada: revision > 0,
    ultima_zona: { ...zones[revision > 0 ? 1 : 0], caminho: revision > 0 ? 'EASY → Sala B' : 'EASY → Sala A' }, ultima_deteccao_em: '2026-10-05T12:00:00Z' }
  return single ? item : { items: [item], total: 1, page: 1, page_size: 20 }
}
beforeEach(() => {
  vi.useFakeTimers()
  revision = 0; fail = ''; calls = []
  window.history.replaceState(null, '', '/')
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = new URL(input, 'http://localhost')
    calls.push(url.pathname)
    if (fail === url.pathname) return { ok: false, status: 503 }
    // ISS-027: o painel (e a atualização automática) só monta com sessão.
    if (url.pathname === '/auth/me') return response(SESSAO_ADMIN)
    const zones = [{ id: 31, nome: 'Sala A', referencia_planta: 'sala-a', ativo: true },
      { id: 82, nome: 'Sala B', referencia_planta: 'sala-b', ativo: true }]
    if (url.pathname === '/localizacoes/arvore') return response([{ setores: [{ zonas: zones }] }])
    if (url.pathname === '/tipos-equipamento') return response({ items: [{ id: 1, nome: `Tipo ${revision}` }] })
    if (url.pathname === '/portais') return response({ items: [{ id: 907, nome: 'Portal de teste RFID', ativo: true, zona_a_id: 31, zona_b_id: 82 }], pages: 1 })
    if (url.pathname === '/api/ativos' || url.pathname === '/api/ativos/1') return response(ativoAtual(url.pathname === '/api/ativos/1'))
    if (url.pathname === '/api/dashboard/resumo') return response({ registered: 10 + revision, disponivel: 2 + revision, atencao: 0, fora_de_servico: 0, nunca_detectado: 0 })
    if (url.pathname === '/api/dashboard/atividade') return response({ items: [{ id: revision + 1, equipamento_nome: `Evento ${revision}`, zona_origem: 'Sala A', zona_destino: 'Sala B', movimentada_em: '2026-10-05T12:00:00Z' }] })
    if (url.pathname.endsWith('/movimentacoes')) return response({ items: [{ id: revision + 1, zona_origem: 'Sala A', zona_destino: `Destino ${revision}`, movimentada_em: '2026-10-05T12:00:00Z' }], page: 1, pages: 1 })
    if (url.pathname === '/api/laboratorio/leituras') return response({ items: Number(url.searchParams.get('after_id')) < revision + 1 ? [{ id: revision + 1, epc: `TAG-${revision}`, antena_porta: 1, recebido_em: '2026-10-05T12:00:00Z' }] : [], next_id: revision + 1 })
    throw new Error(`Endpoint não esperado: ${url.pathname}`)
  }))
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })
const mount = async () => { await act(async () => { render(<App/>) }) }
const tick = async (ms = 2000) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }

it('atualiza inventário, indicadores, opções e atividade sem clique nem reload', async () => {
  await mount()
  expect(screen.getByRole('table')).toHaveTextContent('Maca 0')
  expect(screen.getByText('Em trânsito', { selector: '.kpi-card-label' }).closest('article')).toHaveTextContent('2')
  revision = 1
  await tick()
  expect(screen.getByRole('table')).toHaveTextContent('Maca 1')
  expect(screen.getByRole('option', { name: 'Tipo 1' })).toBeInTheDocument()
  expect(screen.getByText('Em trânsito', { selector: '.kpi-card-label' }).closest('article')).toHaveTextContent('3')
  expect(screen.getByRole('region', { name: 'Movimentações recentes' })).toHaveTextContent('Evento 1')
  expect(screen.queryByText('Disponível')).not.toBeInTheDocument()
})

it('mantém último resultado durante falha e recupera automaticamente', async () => {
  await mount(); fail = '/api/ativos'; revision = 1
  await tick()
  expect(screen.getByRole('table')).toHaveTextContent('Maca 0')
  expect(screen.getByText('Não foi possível carregar os equipamentos.')).toBeInTheDocument()
  fail = ''
  await tick()
  expect(screen.getByRole('table')).toHaveTextContent('Maca 1')
  expect(screen.queryByText('Não foi possível carregar os equipamentos.')).not.toBeInTheDocument()
})

it('um botão global renova todos os recursos ativos sem aguardar o próximo ciclo', async () => {
  await mount(); revision = 1; calls = []
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' })) })
  expect(screen.getAllByRole('button', { name: 'Atualizar todos os dados' })).toHaveLength(1)
  expect(calls.sort()).toEqual(['/api/ativos', '/api/dashboard/atividade', '/api/dashboard/resumo', '/localizacoes/arvore', '/tipos-equipamento'].sort())
  expect(screen.getByRole('table')).toHaveTextContent('Maca 1')
})

it('não sobrepõe consultas lentas e cancela a pendente ao sair', async () => {
  await mount()
  const original = globalThis.fetch
  let signal: AbortSignal | undefined
  let pending = 0
  vi.stubGlobal('fetch', vi.fn((input: string, init?: RequestInit) => {
    if (input.startsWith('/api/ativos')) {
      pending++; signal = init?.signal as AbortSignal
      return new Promise((_resolve, reject) => signal!.addEventListener('abort', () => reject(new Error('aborted'))))
    }
    return original(input, init)
  }))
  await tick(6000)
  expect(pending).toBe(1)
  expect(screen.getByRole('button', { name: 'Atualizar todos os dados' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
  expect(pending).toBe(1)
  cleanup()
  expect(signal?.aborted).toBe(true)
})

it('interrompe uma consulta travada em 8s e permite recuperar os dados', async () => {
  await mount()
  const original = globalThis.fetch
  vi.stubGlobal('fetch', vi.fn((input: string, init?: RequestInit) => input.startsWith('/api/ativos')
    ? new Promise((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new Error('timeout'))))
    : original(input, init)))
  await tick(10000)
  expect(screen.getByText('Não foi possível carregar os equipamentos.')).toBeInTheDocument()
  vi.stubGlobal('fetch', original); revision = 1
  await tick()
  expect(screen.getByRole('table')).toHaveTextContent('Maca 1')
})

it('atualiza detalhes e histórico enquanto o painel permanece aberto', async () => {
  await mount()
  await act(async () => { fireEvent.click(within(screen.getByRole('table')).getByRole('button', { name: /Maca 0/ })) })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Ver histórico completo' })) })
  expect(screen.getByRole('dialog')).toHaveTextContent('Destino 0')
  revision = 1; await tick()
  expect(screen.getByRole('dialog')).toHaveTextContent('Maca 1')
  expect(screen.getByRole('dialog')).toHaveTextContent('Destino 1')
  expect(screen.getByRole('dialog')).toHaveTextContent('Localização pode estar desatualizada')
})

it('atualiza zonas, contagens, portal e leituras do EASY e oferece seleção textual', async () => {
  window.location.hash = '#/mapa'; await mount()
  await act(async () => { fireEvent.click(screen.getByRole('tab', { name: 'Laboratório de Testes (EASY)' })) })
  expect(screen.getByRole('button', { name: /Portal de teste RFID.*Lado A/ })).toHaveAttribute('data-portal-id', '907')
  expect(screen.getByRole('button', { name: /1 equipamento.*Sala A/ })).toBeInTheDocument()
  revision = 1; await tick()
  expect(screen.queryByRole('button', { name: /1 equipamento.*Sala A/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /1 equipamento.*Sala B/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Zonas e portais' }))
  expect(screen.getByRole('button', { name: 'Sala A · 0 ativo(s)' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Sala A · 0 ativo(s)' }))
  expect(screen.getByRole('region', { name: 'Equipamentos em Sala A' })).toHaveTextContent('Nenhum equipamento nesta zona agora.')
  expect(screen.queryByRole('button', { name: /Maca 1/ })).not.toBeInTheDocument()
  fail = '/portais'; await tick()
  expect(screen.queryByRole('button', { name: /Portal de teste RFID.*Lado A/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Equipamentos em Sala A' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: /Outras zonas/ }))
  expect(screen.getByRole('button', { name: /Maca 1/ })).toBeInTheDocument()
  fail = ''; calls = []
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' })) })
  expect(calls).toEqual(expect.arrayContaining(['/api/ativos', '/portais', '/localizacoes/arvore', '/api/laboratorio/leituras']))
  expect(screen.getByRole('button', { name: /Portal de teste RFID.*Lado A/ })).toBeInTheDocument()
})

it('consulta todas as páginas de portais', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => input.startsWith('/localizacoes')
    ? response([]) : response({ items: [{ id: input.includes('page=2') ? 200 : 100 }], pages: 2 })))
  const result = await getMapTopology()
  expect(result.portals.map((portal) => portal.id)).toEqual([100, 200])
})
