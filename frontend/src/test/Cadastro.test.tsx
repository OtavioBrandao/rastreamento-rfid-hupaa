import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RegistrationPage } from '../pages/RegistrationPage'
import { epcProblem } from '../services/cadastro'
import { LiveProvider } from '../services/live'

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body })
const recent = new Date().toISOString()
const unknown = {
  epc: 'E2804C417F4EB9E99018F57B', situacao: 'desconhecido', equipamento: null, leituras: 34,
  primeira_leitura_em: recent, ultima_leitura_em: recent, recente: true,
  ultima_antena: { antena_id: 2, porta: 2, leitor: 'sim-easy-01', leitor_modelo: 'EZ700 (virtual)', zona: 'Zona B', origem: 'simulado' },
  antenas: [],
}
let calls: { url: URL; init: RequestInit }[]

beforeEach(() => {
  calls = []
  window.location.hash = '#/cadastro'
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push({ url, init })
    if (url.pathname === '/api/cadastro/epcs-detectados') return json({ gerado_em: recent, janela_segundos: 900, recente_segundos: 120, total: 1, desconhecidos: 1, items: [unknown],
      leitores: [{ reader_id: 'sim-easy-01', modelo: 'EZ700', origem: 'simulado', ultimo_contato_em: recent, status: 'online', antenas: [] },
        { reader_id: 'reader-01', modelo: 'EZ700', origem: 'fisico', ultimo_contato_em: null, status: 'nunca_conectado', antenas: [] }] })
    if (url.pathname === '/tipos-equipamento') return json({ items: [{ id: 3, nome: 'Maca', ativo: true }] })
    if (url.pathname === '/api/cadastro/equipamentos' && init.method === 'POST') {
      const body = JSON.parse(String(init.body))
      if (body.epc === 'E2000017221101441890A001') return json({ detail: "EPC 'E2000017221101441890A001' já está associado a outro equipamento ativo" }, 409)
      return json({ id: 9, nome: body.nome, tipo_nome: 'Maca', identificador_interno: 'EQ-20261023-ABC123', epc: body.epc ?? null, situacao_tag: body.epc ? 'com_tag' : 'sem_tag' }, 201)
    }
    if (url.pathname === '/api/cadastro/equipamentos') return json({ items: [{ id: 4, nome: 'Cadeira de rodas', identificador_interno: 'EQ-1', status: 'ativo', descricao: null, tipo_id: 3, tipo_nome: 'Cadeira', ultima_zona: null, epc: null, situacao_tag: 'sem_tag', vinculo_inicio: null, created_at: recent }], page: 1, size: 20, total: 1, pages: 1 })
    if (url.pathname.startsWith('/api/cadastro/epcs/')) return json({ epc: 'X', disponivel: true, equipamento: null })
    return json({})
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const renderPage = (canEdit = true) => render(<LiveProvider><RegistrationPage canEdit={canEdit}/></LiveProvider>)

describe('cadastro por leitura RFID', () => {
  it('mostra EPC detectado com leitor, origem simulada e aviso de leitor sem contato', async () => {
    renderPage()
    expect(await screen.findByText(unknown.epc)).toBeInTheDocument()
    expect(screen.getByText('Simulado')).toBeInTheDocument()
    expect(screen.getByText(/reader-01 \(Nunca conectado\)/)).toBeInTheDocument()
  })

  it('exige confirmação e envia a associação com origem leitura', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: `Cadastrar equipamento com a tag ${unknown.epc}` }))
    fireEvent.change(screen.getByPlaceholderText('Ex.: Maca hospitalar'), { target: { value: 'Maca hospitalar' } })
    await screen.findByRole('option', { name: 'Maca' })
    fireEvent.change(screen.getByRole('combobox', { name: /Tipo/ }), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar e associar tag' }))
    expect(await screen.findByText('Confirme que a tag pertence a este equipamento.')).toBeInTheDocument()
    expect(calls.some((call) => call.init.method === 'POST')).toBe(false)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar e associar tag' }))
    expect(await screen.findByText(/associado à tag E2804C417F4EB9E99018F57B/)).toBeInTheDocument()
    const body = JSON.parse(String(calls.find((call) => call.init.method === 'POST')!.init.body))
    expect(body).toMatchObject({ nome: 'Maca hospitalar', tipo_id: 3, epc: unknown.epc, origem_epc: 'leitura', confirmar_associacao: true })
  })

  it('operacional consulta sem botão de cadastro', async () => {
    renderPage(false)
    expect(await screen.findByText(unknown.epc)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cadastrar equipamento/ })).toBeNull()
    expect(screen.getByText(/apenas administradores cadastram/)).toBeInTheDocument()
  })
})

describe('cadastro manual', () => {
  it('valida EPC no cliente e mostra conflito de EPC duplicado do servidor', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: 'Cadastro manual' }))
    fireEvent.change(screen.getByPlaceholderText('Ex.: Maca hospitalar'), { target: { value: 'Maca hospitalar' } })
    await screen.findByRole('option', { name: 'Maca' })
    fireEvent.change(screen.getByRole('combobox', { name: /Tipo/ }), { target: { value: '3' } })
    const epc = screen.getByPlaceholderText(/Opcional — ex\./)
    fireEvent.change(epc, { target: { value: 'XYZ' } })
    expect(screen.getByText('Use apenas dígitos hexadecimais (0–9, A–F).')).toBeInTheDocument()
    fireEvent.change(epc, { target: { value: 'E2000017221101441890A001' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar e associar tag' }))
    expect(await screen.findByText(/já está associado a outro equipamento ativo/)).toBeInTheDocument()
  })

  it('cadastra sem tag quando o EPC fica vazio', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: 'Cadastro manual' }))
    fireEvent.change(screen.getByPlaceholderText('Ex.: Maca hospitalar'), { target: { value: 'Cadeira de rodas' } })
    await screen.findByRole('option', { name: 'Maca' })
    fireEvent.change(screen.getByRole('combobox', { name: /Tipo/ }), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar sem tag' }))
    expect(await screen.findByText(/cadastrado \(EQ-20261023-ABC123\) sem tag/)).toBeInTheDocument()
    const body = JSON.parse(String(calls.find((call) => call.init.method === 'POST')!.init.body))
    expect(body.epc).toBeUndefined()
    expect(body.confirmar_associacao).toBe(false)
  })

  it('lista equipamentos sem tag com ação de associar', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: 'Equipamentos e tags' }))
    expect(await screen.findByText('Cadeira de rodas')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Associar tag' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Associar' })).toBeInTheDocument())
  })

  it('administrador coloca fora de serviço depois de confirmar e filtra os fora de serviço', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: 'Equipamentos e tags' }))
    const button = await screen.findByRole('button', { name: 'Colocar fora de serviço: Cadeira de rodas' })
    fireEvent.click(button)
    expect(calls.some((call) => call.url.pathname.endsWith('/inativar'))).toBe(false)
    fireEvent.click(button)
    await waitFor(() => expect(calls.some((call) => call.url.pathname === '/equipamentos/4/inativar' && call.init.method === 'POST')).toBe(true))
    expect(await screen.findByText('“Cadeira de rodas” está fora de serviço.')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'Serviço' }), { target: { value: 'inativo' } })
    await waitFor(() => expect(calls.some((call) => call.url.searchParams.get('estado') === 'inativo')).toBe(true))
    confirm.mockRestore()
  })

  it('operacional não vê o botão de fora de serviço', async () => {
    renderPage(false)
    fireEvent.click(screen.getByRole('tab', { name: 'Equipamentos e tags' }))
    expect(await screen.findByText('Cadeira de rodas')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /fora de serviço|Reativar/ })).toBeNull()
  })
})

describe('regra de EPC', () => {
  it('espelha api/epc.py', () => {
    expect(epcProblem('')).toBeNull()
    expect(epcProblem('E2000017221101441890A001')).toBeNull()
    expect(epcProblem('ABC')).toMatch(/par/)
    expect(epcProblem('ABCD')).toMatch(/entre 8 e 32/)
  })
})
