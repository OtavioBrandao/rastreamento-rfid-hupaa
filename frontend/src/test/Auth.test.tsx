import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

// Servidor falso com estado: a sessão só existe "no cookie" (aqui, na variável
// `sessaoAtual`); o front nunca a vê fora das respostas da API.
const ADMIN = { id: 1, nome: 'Ana Admin', email: 'ana@hupaa.example', perfil: 'administrador',
  ativo: true, deve_trocar_senha: false }
const TEMPORARIA = { id: 2, nome: 'Tina Operadora', email: 'tina@hupaa.example',
  perfil: 'operacional', ativo: true, deve_trocar_senha: true }
const SENHAS: Record<string, string> = { 'ana@hupaa.example': 'senha-correta-1', 'tina@hupaa.example': 'temporaria-1' }
const USUARIOS: Record<string, typeof ADMIN> = { 'ana@hupaa.example': ADMIN, 'tina@hupaa.example': TEMPORARIA }

let sessaoAtual: typeof ADMIN | null
let chamadas: { path: string; init?: RequestInit }[]
let servidorFora: boolean

function sessao(usuario: typeof ADMIN) {
  return { usuario, sessao_expira_em: '2026-09-26T20:00:00Z',
    permissoes: usuario.perfil === 'administrador' ? ['equipamentos:alterar', 'equipamentos:consultar'] : ['equipamentos:consultar'] }
}
const json = (status: number, body: unknown = null) => ({ ok: status < 400, status, json: async () => body })

beforeEach(() => {
  window.location.hash = ''
  localStorage.clear(); sessionStorage.clear()
  sessaoAtual = null
  chamadas = []
  servidorFora = false
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    chamadas.push({ path: url.pathname, init })
    if (servidorFora) throw new TypeError('Failed to fetch')
    const corpo = init?.body ? JSON.parse(String(init.body)) : {}
    switch (url.pathname) {
      case '/auth/me': return sessaoAtual ? json(200, sessao(sessaoAtual)) : json(401, { detail: 'nao_autenticado' })
      case '/auth/login':
        if (!String(corpo.email).includes('@')) return json(422, { detail: [] })
        if (SENHAS[corpo.email] !== corpo.senha) return json(401, { detail: 'credenciais_invalidas' })
        sessaoAtual = { ...USUARIOS[corpo.email] }
        return json(200, sessao(sessaoAtual))
      case '/auth/logout': sessaoAtual = null; return json(204)
      case '/auth/trocar-senha':
        if (!sessaoAtual) return json(401, { detail: 'nao_autenticado' })
        if (SENHAS[sessaoAtual.email] !== corpo.senha_atual) return json(400, { detail: 'senha_atual_incorreta' })
        SENHAS[sessaoAtual.email] = corpo.nova_senha
        sessaoAtual = { ...sessaoAtual, deve_trocar_senha: false }
        return json(204)
    }
    if (!sessaoAtual) return json(401, { detail: 'nao_autenticado' })
    if (url.pathname === '/api/ativos') return json(200, { items: [], total: 0, page: 1, page_size: 20 })
    if (url.pathname === '/api/dashboard/resumo') return json(200, { registered: 0, disponivel: 0, atencao: 0, fora_de_servico: 0, nunca_detectado: 0 })
    if (url.pathname === '/api/dashboard/atividade') return json(200, { items: [] })
    if (url.pathname === '/tipos-equipamento') return json(200, { items: [] })
    return json(200, [])
  }))
})
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks()
  SENHAS['tina@hupaa.example'] = 'temporaria-1'
  SENHAS['ana@hupaa.example'] = 'senha-correta-1'
})

async function entrar(email: string, senha: string) {
  fireEvent.change(await screen.findByLabelText('E-mail'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Senha'), { target: { value: senha } })
  fireEvent.click(screen.getByRole('button', { name: 'Entrar' }))
}
const dadosConsultados = () => chamadas.filter(({ path }) => !path.startsWith('/auth/'))

describe('sessão no dashboard', () => {
  it('permite trocar a própria senha mesmo sem troca obrigatória', async () => {
    sessaoAtual = { ...ADMIN }
    window.location.hash = '#/senha'
    render(<App/>)
    await screen.findByRole('heading', { name: 'Trocar minha senha' })
    fireEvent.change(screen.getByLabelText('Senha atual'), { target: { value: 'senha-correta-1' } })
    fireEvent.change(screen.getByLabelText('Nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.change(screen.getByLabelText('Confirmar nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Trocar senha' }))
    await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })
    expect(window.location.hash).toBe('#/')
    expect(chamadas.filter(({ path }) => path === '/auth/trocar-senha')).toHaveLength(1)
    expect(screen.queryByLabelText('Senha atual')).not.toBeInTheDocument()
  })

  it('oferece cancelamento apenas quando a troca não é obrigatória', async () => {
    sessaoAtual = { ...ADMIN }; window.location.hash = '#/senha'
    render(<App/>)
    await screen.findByRole('heading', { name: 'Trocar minha senha' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })
    expect(screen.getByRole('link', { name: 'Trocar minha senha' })).toHaveAttribute('href', '#/senha')
    expect(chamadas.filter(({ path }) => path === '/auth/trocar-senha')).toHaveLength(0)
    cleanup(); sessaoAtual = { ...TEMPORARIA }; window.location.hash = '#/senha'
    render(<App/>)
    await screen.findByRole('heading', { name: 'Troca de senha obrigatória' })
    expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()
  })

  it('sem sessão mostra o login e não consulta dados', async () => {
    render(<App/>)
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    expect(screen.getByLabelText('E-mail')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Senha')).toHaveAttribute('autocomplete', 'current-password')
    expect(dadosConsultados()).toEqual([])
  })

  it('login inválido mostra mensagem genérica e limpa a senha (401 e 422)', async () => {
    render(<App/>)
    await entrar('ana@hupaa.example', 'errada-123')
    expect(await screen.findByRole('alert')).toHaveTextContent('E-mail ou senha inválidos.')
    expect(screen.getByLabelText('Senha')).toHaveValue('')
    await entrar('sem-arroba', 'qualquer-1')
    await waitFor(() => expect(chamadas.filter(({ path }) => path === '/auth/login')).toHaveLength(2))
    expect(await screen.findByRole('alert')).toHaveTextContent('E-mail ou senha inválidos.')
    expect(screen.getByLabelText('Senha')).toHaveValue('')
    expect(dadosConsultados()).toEqual([])
  })

  it('login válido abre o painel com nome e perfil, sem storage e com credentials same-origin', async () => {
    render(<App/>)
    await entrar('ana@hupaa.example', 'senha-correta-1')
    expect(await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })).toBeInTheDocument()
    const usuario = screen.getByRole('group', { name: 'Usuário conectado' })
    expect(usuario).toHaveTextContent('Ana Admin')
    expect(usuario).toHaveTextContent('Administrador')
    await waitFor(() => expect(dadosConsultados().length).toBeGreaterThan(0))
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(chamadas.every(({ init }) => init?.credentials === 'same-origin')).toBe(true)
    expect(chamadas.every(({ init }) => !new Headers(init?.headers).has('Authorization'))).toBe(true)
  })

  it('senha temporária exige troca, confere a confirmação sem chamar a API e abre o painel', async () => {
    render(<App/>)
    await entrar('tina@hupaa.example', 'temporaria-1')
    expect(await screen.findByRole('heading', { name: 'Troca de senha obrigatória' })).toBeInTheDocument()
    expect(screen.getByLabelText('Nova senha')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText('Confirmar nova senha')).toHaveAttribute('autocomplete', 'new-password')
    expect(dadosConsultados()).toEqual([])

    fireEvent.change(screen.getByLabelText('Senha temporária'), { target: { value: 'temporaria-1' } })
    fireEvent.change(screen.getByLabelText('Nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.change(screen.getByLabelText('Confirmar nova senha'), { target: { value: 'outra-senha-9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Trocar senha' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A confirmação não confere')
    fireEvent.change(screen.getByLabelText('Nova senha'), { target: { value: 'curta' } })
    fireEvent.change(screen.getByLabelText('Confirmar nova senha'), { target: { value: 'curta' } })
    fireEvent.click(screen.getByRole('button', { name: 'Trocar senha' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('pelo menos 8 caracteres')
    expect(chamadas.some(({ path }) => path === '/auth/trocar-senha')).toBe(false)

    fireEvent.change(screen.getByLabelText('Nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.change(screen.getByLabelText('Confirmar nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Trocar senha' }))
    expect(await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Usuário conectado' })).toHaveTextContent('Operacional')
  })

  it('troca com senha atual errada mostra o erro e limpa o campo', async () => {
    render(<App/>)
    await entrar('tina@hupaa.example', 'temporaria-1')
    fireEvent.change(await screen.findByLabelText('Senha temporária'), { target: { value: 'errada-000' } })
    fireEvent.change(screen.getByLabelText('Nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.change(screen.getByLabelText('Confirmar nova senha'), { target: { value: 'nova-senha-9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Trocar senha' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Senha atual incorreta.')
    expect(screen.getByLabelText('Senha temporária')).toHaveValue('')
    expect(screen.getByRole('heading', { name: 'Troca de senha obrigatória' })).toBeInTheDocument()
  })

  it('sair encerra a sessão no servidor e volta ao login (painel e tela de troca)', async () => {
    sessaoAtual = { ...ADMIN }
    render(<App/>)
    await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })
    fireEvent.click(within(screen.getByRole('group', { name: 'Usuário conectado' })).getByRole('button', { name: 'Sair' }))
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(chamadas.filter(({ path }) => path === '/auth/logout')).toHaveLength(1)

    await entrar('tina@hupaa.example', 'temporaria-1')
    fireEvent.click(await screen.findByRole('button', { name: 'Sair' }))
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    expect(chamadas.filter(({ path }) => path === '/auth/logout')).toHaveLength(2)
  })

  it('401 no meio do uso volta ao login com aviso de sessão expirada', async () => {
    sessaoAtual = { ...ADMIN }
    render(<App/>)
    await screen.findByRole('searchbox', { name: 'Nome ou patrimônio' })
    sessaoAtual = null  // expirou, conta desativada ou logout em outra aba
    // A busca é ao vivo (ISS-033): o botão global força a próxima consulta, que recebe 401.
    fireEvent.click(screen.getByRole('button', { name: 'Atualizar todos os dados' }))
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Sua sessão expirou. Entre novamente.')
  })

  it('servidor fora do ar no início mostra o login com aviso, sem ficar carregando', async () => {
    servidorFora = true
    render(<App/>)
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Não foi possível contactar o servidor')
    expect(screen.queryByText('Carregando…')).not.toBeInTheDocument()
  })
})
