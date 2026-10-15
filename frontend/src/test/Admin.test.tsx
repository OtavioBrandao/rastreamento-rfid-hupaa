import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuditPage } from '../pages/AuditPage'
import { UsersPage } from '../pages/UsersPage'
import { LiveProvider, useLiveRefresh } from '../services/live'
import type { Auditoria, Usuario } from '../services/admin'

const admin: Usuario = { id: 1, nome: 'Ana', email: 'ana@hupaa.example', perfil: 'administrador', ativo: true,
  deve_trocar_senha: false, bloqueado_ate: null, ultimo_login_em: null, created_at: '2026-10-14T12:00:00Z', updated_at: '2026-10-14T12:00:00Z' }
const operator: Usuario = { ...admin, id: 2, nome: 'Bia', email: 'bia@hupaa.example', perfil: 'operacional' }
const audit: Auditoria = { id: 7, registrado_em: '2026-10-14T12:00:00Z', acao: 'correcao_manual', origem: 'usuario', entidade: 'equipamentos', entidade_id: 12,
  usuario_id: 1, usuario_nome: 'Ana', motivo: 'Conferido na enfermaria', correlation_id: 'request-7', dados_antes: { nome: '<script>antigo</script>' }, dados_depois: { nome: 'Novo' } }
const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body })
const pagination = (items: unknown[], page = 1) => ({ items, page, size: 20, total: 21, pages: 2 })
let calls: { url: URL; init: RequestInit }[]
let users: Usuario[]
let sessionUser: Usuario
let permissions: string[]
let failureStatus: number
let writeFailure: number
let auditItems: Auditoria[]

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  calls = []; users = [{ ...admin }, { ...operator }]; sessionUser = { ...admin }
  auditItems = [audit]
  permissions = ['usuarios:administrar', 'auditoria:consultar', 'equipamentos:consultar']; failureStatus = 0; writeFailure = 0
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push({ url, init })
    if (url.pathname === '/auth/me') return json({ usuario: sessionUser, permissoes: permissions, sessao_expira_em: '2026-10-14T20:00:00Z' })
    const method = init.method ?? 'GET'
    if (url.pathname.startsWith('/usuarios')) {
      if (method === 'GET') {
        if (failureStatus) return json(null, failureStatus)
        const page = Number(url.searchParams.get('page')) || 1
        return json(pagination(page === 2 ? [] : users.filter((user) => (!url.searchParams.has('ativo') || String(user.ativo) === url.searchParams.get('ativo')) && (!url.searchParams.get('perfil') || user.perfil === url.searchParams.get('perfil'))), page))
      }
      if (writeFailure) return json({ detail: { input: { senha_temporaria: 'nunca-exibir' } } }, writeFailure)
      const body = init.body ? JSON.parse(String(init.body)) : {}
      if (url.pathname === '/usuarios') {
        const created = { ...operator, ...body, id: 3, deve_trocar_senha: true }
        users.push(created); return json(created, 201)
      }
      const target = users.find((user) => user.id === Number(url.pathname.split('/')[2]))!
      if (method === 'PATCH') Object.assign(target, body)
      else if (url.pathname.endsWith('/desativar')) target.ativo = false
      else if (url.pathname.endsWith('/reativar')) target.ativo = true
      else if (url.pathname.endsWith('/redefinir-senha')) target.deve_trocar_senha = true
      if (target.id === 1) { sessionUser = { ...target }; if (target.perfil === 'operacional') permissions = ['equipamentos:consultar'] }
      return json(target)
    }
    if (url.pathname.startsWith('/auditorias')) {
      if (failureStatus) return json(null, failureStatus)
      if (url.pathname === '/auditorias/7') return json(audit)
      return json(pagination(auditItems, Number(url.searchParams.get('page')) || 1))
    }
    return json({ items: [], total: 0, page: 1, page_size: 20, registered: 0, disponivel: 0, atencao: 0, fora_de_servico: 0, nunca_detectado: 0 })
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const writes = () => calls.filter((call) => call.init.method && call.init.method !== 'GET')
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }))
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } })
function Refresh() { const { refresh } = useLiveRefresh(); return <button onClick={refresh}>Atualizar consulta</button> }
function renderUsers(onSessionChanged = vi.fn()) {
  render(<LiveProvider><UsersPage currentUserId={1} onSessionChanged={onSessionChanged}/><Refresh/></LiveProvider>)
  return onSessionChanged
}

describe('administração de usuários', () => {
  it('cria uma conta com senha temporária e limpa o formulário após sucesso', async () => {
    renderUsers(); await screen.findByText('bia@hupaa.example')
    click('Novo usuário'); change('Nome', 'Cris'); change('E-mail', 'cris@hupaa.example'); change('Senha temporária', 'temporaria-local')
    click('Criar usuário')
    await screen.findByText('cris@hupaa.example')
    expect(JSON.parse(String(writes()[0].init.body))).toEqual({ nome: 'Cris', email: 'cris@hupaa.example', perfil: 'operacional', senha_temporaria: 'temporaria-local' })
    expect(writes()[0].init.credentials).toBe('same-origin')
    expect(screen.queryByLabelText('Senha temporária')).not.toBeInTheDocument()
    expect(screen.getByText('Troca de senha pendente')).toBeInTheDocument()
  })

  it('edita somente o nome alterado, sem mandar e-mail nem senha', async () => {
    renderUsers(); await screen.findByText('bia@hupaa.example')
    click('Editar Bia'); change('Nome', 'Beatriz'); click('Salvar alterações')
    await screen.findByRole('button', { name: 'Editar Beatriz' })
    expect(writes()[0].url.pathname).toBe('/usuarios/2')
    expect(writes()[0].init.method).toBe('PATCH')
    expect(JSON.parse(String(writes()[0].init.body))).toEqual({ nome: 'Beatriz' })
  })

  it('confirma desativação e reativação e bloqueia ações na própria conta', async () => {
    renderUsers(); await screen.findByText('bia@hupaa.example')
    expect(screen.getByRole('button', { name: 'Desativar Ana' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Redefinir senha de Ana' })).toBeDisabled()
    click('Desativar Bia'); expect(writes()).toHaveLength(0)
    click('Cancelar'); expect(writes()).toHaveLength(0)
    click('Desativar Bia'); click('Confirmar')
    await screen.findByRole('button', { name: 'Reativar Bia' })
    expect(writes()[0].url.pathname).toBe('/usuarios/2/desativar')
    click('Reativar Bia'); click('Confirmar')
    await screen.findByRole('button', { name: 'Desativar Bia' })
    expect(writes()[1].url.pathname).toBe('/usuarios/2/reativar')
  })

  it('redefine senha com confirmação, trata recusa e apaga o segredo', async () => {
    renderUsers(); await screen.findByText('bia@hupaa.example')
    click('Redefinir senha de Bia'); change('Senha temporária', 'temporaria-local'); writeFailure = 422; click('Confirmar')
    await screen.findByRole('alert')
    expect(screen.queryByText('nunca-exibir')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Senha temporária')).toHaveValue('')
    writeFailure = 0; change('Senha temporária', 'nova-temporaria'); click('Confirmar')
    await screen.findByText(/Senha redefinida/)
    expect(writes()[1].url.pathname).toBe('/usuarios/2/redefinir-senha')
    expect(JSON.parse(String(writes()[1].init.body))).toEqual({ senha_temporaria: 'nova-temporaria' })
  })

  it('aplica filtros no servidor e reinicia a página', async () => {
    renderUsers(); await screen.findByText('bia@hupaa.example')
    click('Próxima'); await screen.findByText('Nenhum usuário encontrado para estes filtros.')
    change('Perfil de acesso', 'operacional')
    await screen.findByText('bia@hupaa.example')
    const last = calls.at(-1)!.url
    expect(last.searchParams.get('page')).toBe('1'); expect(last.searchParams.get('perfil')).toBe('operacional')
    change('Estado da conta', 'false')
    await screen.findByText('Nenhum usuário encontrado para estes filtros.')
    expect(calls.at(-1)!.url.searchParams.get('ativo')).toBe('false')
  })

  it('mostra a recusa por último administrador e mantém o formulário', async () => {
    renderUsers(); await screen.findByText('ana@hupaa.example')
    click('Editar Ana'); change('Perfil', 'operacional'); writeFailure = 409; click('Salvar alterações')
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Perfil', { exact: true })).toHaveValue('operacional')
    expect(screen.getByRole('alert')).toHaveTextContent('administrador ativo')
  })

  it('recarrega permissões ao editar o próprio perfil e impede acesso direto sem permissão', async () => {
    window.location.hash = '#/usuarios'; render(<App/>); await screen.findByText('ana@hupaa.example')
    click('Editar Ana'); change('Perfil', 'operacional'); click('Salvar alterações')
    await screen.findByRole('heading', { name: 'Acesso restrito' })
    expect(screen.queryByRole('link', { name: /Usuários/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Auditoria/ })).not.toBeInTheDocument()
    expect(calls.filter((call) => call.url.pathname === '/auth/me').length).toBe(2)
  })

  it.each(['#/usuarios', '#/auditoria'])('nega URL %s ao operacional sem consultar os dados', async (hash) => {
    sessionUser = { ...operator }; permissions = ['equipamentos:consultar']; window.location.hash = hash
    render(<App/>); await screen.findByRole('heading', { name: 'Acesso restrito' })
    expect(calls.map((call) => call.url.pathname)).toEqual(['/auth/me'])
  })

  it('oculta dados após 403 e volta ao login após 401', async () => {
    window.location.hash = '#/usuarios'; render(<App/>); await screen.findByText('bia@hupaa.example')
    failureStatus = 403; click('Atualizar todos os dados')
    await screen.findByRole('alert'); expect(screen.queryByText('bia@hupaa.example')).not.toBeInTheDocument()
    failureStatus = 401; click('Atualizar todos os dados')
    await screen.findByRole('button', { name: 'Entrar' })
    expect(screen.getByText('Sua sessão expirou. Entre novamente.')).toBeInTheDocument()
  })
})

describe('consulta da auditoria', () => {
  it('abre o detalhe em modal mesmo com 50 linhas e mantém filtros ao fechar', async () => {
    auditItems = Array.from({ length: 50 }, (_, index) => ({ ...audit, id: index + 1 }))
    render(<LiveProvider><AuditPage/><Refresh/></LiveProvider>)
    await screen.findByRole('button', { name: 'Ver registro #7' })
    change('Entidade', 'equipamentos'); click('Aplicar filtros')
    await waitFor(() => expect(calls.at(-1)!.url.searchParams.get('entidade')).toBe('equipamentos'))
    screen.getByRole('button', { name: 'Ver registro #7' }).focus()
    click('Ver registro #7')
    const dialog = await screen.findByRole('dialog', { name: 'Registro #7' })
    expect(dialog).toHaveAttribute('open')
    await within(dialog).findByRole('heading', { name: 'Antes' })
    fireEvent.click(within(dialog).getByRole('heading', { name: 'Depois' }))
    expect(dialog).toBeInTheDocument()
    click('Atualizar consulta')
    await waitFor(() => expect(calls.filter((call) => call.url.pathname === '/auditorias/7')).toHaveLength(2))
    expect(dialog).toHaveAttribute('open')
    click('Fechar registro')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ver registro #7' })).toHaveFocus()
    expect(screen.getByLabelText('Entidade', { exact: true })).toHaveValue('equipamentos')
    click('Ver registro #7')
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    click('Ver registro #7')
    fireEvent.click(screen.getByRole('dialog'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('envia filtros combinados, fuso de Maceió e paginação para a API', async () => {
    render(<LiveProvider><AuditPage/></LiveProvider>); await screen.findByRole('button', { name: 'Ver registro #7' })
    change('Entidade', 'equipamentos'); change('ID da entidade', '12'); change('Ação', 'correcao_manual'); change('Origem', 'usuario'); change('ID do autor', '1'); change('Correlação', 'request-7')
    change('Desde (Maceió, inclusivo)', '2026-10-14T08:00'); change('Até (Maceió, exclusivo)', '2026-10-14T10:00'); click('Aplicar filtros')
    await waitFor(() => expect(calls.at(-1)!.url.searchParams.get('desde')).toBe('2026-10-14T11:00:00.000Z'))
    expect(Object.fromEntries(calls.at(-1)!.url.searchParams)).toMatchObject({ entidade: 'equipamentos', entidade_id: '12', acao: 'correcao_manual', origem: 'usuario', usuario_id: '1', correlation_id: 'request-7', ate: '2026-10-14T13:00:00.000Z' })
    click('Próxima'); await waitFor(() => expect(calls.at(-1)!.url.searchParams.get('page')).toBe('2'))
    click('Limpar filtros'); await waitFor(() => expect(Object.fromEntries(calls.at(-1)!.url.searchParams)).toEqual({ page: '1', size: '50' }))
  })

  it('valida intervalo antes de consultar', async () => {
    render(<LiveProvider><AuditPage/></LiveProvider>); await screen.findByRole('button', { name: 'Ver registro #7' })
    const before = calls.length
    change('Desde (Maceió, inclusivo)', '2026-10-14T10:00'); change('Até (Maceió, exclusivo)', '2026-10-14T08:00'); click('Aplicar filtros')
    expect(screen.getByRole('alert')).toHaveTextContent('início deve ser anterior'); expect(calls).toHaveLength(before)
  })

  it('consulta registro por ID, exibe antes/depois como texto e filtra correlação', async () => {
    render(<LiveProvider><AuditPage/></LiveProvider>); await screen.findByRole('button', { name: 'Ver registro #7' }); click('Ver registro #7')
    await screen.findByRole('heading', { name: 'Antes' })
    expect(calls.some((call) => call.url.pathname === '/auditorias/7')).toBe(true)
    expect(screen.getByText(/<script>antigo<\/script>/)).toBeInTheDocument(); expect(document.querySelector('script')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Depois' })).toBeInTheDocument()
    click('Ver eventos relacionados')
    await waitFor(() => expect(calls.at(-1)!.url.searchParams.get('correlation_id')).toBe('request-7'))
    expect(writes()).toHaveLength(0)
  })

  it('oculta lista e detalhe quando a API revoga o acesso', async () => {
    render(<LiveProvider><AuditPage/><Refresh/></LiveProvider>); await screen.findByRole('button', { name: 'Ver registro #7' }); click('Ver registro #7')
    await screen.findByRole('heading', { name: 'Antes' }); failureStatus = 403; click('Atualizar consulta')
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Ver registro #7' })).not.toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: 'Antes' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('alert')).getByText(/não tem permissão/)).toBeInTheDocument()
  })
})
