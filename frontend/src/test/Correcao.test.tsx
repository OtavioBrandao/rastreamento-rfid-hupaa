import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

// Servidor falso da ISS-025: o equipamento tem versão otimista e a próxima
// resposta das rotas de correção pode ser forçada (conflito ou recusa).
interface Registro {
  id: number; nome: string; tipo_id: number; tipo_nome: string; identificador_interno: string
  descricao: string | null; status: string; ultima_zona_id: number | null
  ultima_deteccao_em: string | null; versao: number
}
let registro: Registro
let permissoes: string[]
let proximaResposta: { status: number; detail: unknown } | null
let posts: { path: string; body: Record<string, unknown> }[]
// Revisão do #77: a busca textual pode não trazer o equipamento na 1ª página.
let buscaSemOEquipamento: boolean

const ativo = () => ({
  id: 1, nome: registro.nome, identificador_interno: registro.identificador_interno,
  tipo: registro.tipo_nome, tipo_id: registro.tipo_id, epc: null, status: 'disponivel',
  ultima_zona: registro.ultima_zona_id === 4
    ? { id: 4, nome: 'Zona D', referencia_planta: 'zona-d', andar: '2º andar', setor: 'Bloco B', caminho: '2º andar → Bloco B → Zona D' }
    : { id: 3, nome: 'Zona C', referencia_planta: 'zona-c', andar: '2º andar', setor: 'Bloco B', caminho: '2º andar → Bloco B → Zona C' },
  ultima_deteccao_em: '2026-09-26T12:00:00Z', localizacao_desatualizada: false,
})
const outro = (id: number) => ({ ...ativo(), id, nome: `Bomba ${id}`, identificador_interno: `${id}1` })
const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body })

beforeEach(() => {
  window.location.hash = ''
  registro = { id: 1, nome: 'Maca 1', tipo_id: 1, tipo_nome: 'Maca', identificador_interno: 'PAT-001',
    descricao: 'Maca de transporte', status: 'ativo', ultima_zona_id: 3,
    ultima_deteccao_em: '2026-09-26T12:00:00Z', versao: 3 }
  permissoes = ['equipamentos:consultar', 'equipamentos:alterar', 'equipamentos:corrigir']
  proximaResposta = null
  posts = []
  buscaSemOEquipamento = false
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    if (url.pathname === '/auth/me') {
      return json(200, { usuario: { id: 9, nome: 'Ana Admin', email: 'ana@x.org', perfil: 'administrador',
        ativo: true, deve_trocar_senha: false }, sessao_expira_em: '2026-09-26T20:00:00Z', permissoes })
    }
    if (init?.method === 'POST' && url.pathname.includes('/correcoes/')) {
      const body = JSON.parse(String(init.body))
      posts.push({ path: url.pathname, body })
      if (proximaResposta) {
        const resposta = proximaResposta
        proximaResposta = null
        return json(resposta.status, { detail: resposta.detail })
      }
      if (body.versao_esperada !== registro.versao) {
        return json(409, { detail: { codigo: 'conflito_de_versao', mensagem: 'x', versao_atual: registro.versao } })
      }
      if (url.pathname.endsWith('/localizacao')) registro = { ...registro, ultima_zona_id: body.zona_id }
      else {
        if (body.identificador_interno) registro = { ...registro, identificador_interno: body.identificador_interno }
        if (body.nome) registro = { ...registro, nome: body.nome }
        if ('descricao' in body) registro = { ...registro, descricao: body.descricao }
      }
      registro = { ...registro, versao: registro.versao + 1 }
      return json(200, url.pathname.endsWith('/localizacao')
        ? { equipamento_id: 1, zona_anterior_id: 3, zona_id: body.zona_id, movimentacao_id: 50,
            movimentada_em: '2026-09-26T13:00:00Z', versao: registro.versao }
        : registro)
    }
    if (url.pathname === '/equipamentos/1') return json(200, registro)
    if (url.pathname === '/equipamentos/1/movimentacoes') {
      return json(200, { items: [{ id: 50, origem_registro: 'correcao_manual', zona_origem: 'Zona C',
        zona_destino: 'Zona D', movimentada_em: '2026-09-26T13:00:00Z', registrado_em: '2026-09-26T13:00:00Z',
        justificativa: 'Vista na sala D', referencia: 'OS-9' }], page: 1, size: 20, total: 1, pages: 1 })
    }
    if (url.pathname === '/api/ativos/1') return json(200, ativo())
    if (url.pathname === '/api/ativos') {
      if (buscaSemOEquipamento) {
        return json(200, { items: Array.from({ length: 20 }, (_, i) => outro(i + 2)), total: 21, page: 1, page_size: 20 })
      }
      return json(200, { items: [ativo()], total: 1, page: 1, page_size: 20 })
    }
    if (url.pathname === '/api/dashboard/resumo') return json(200, { registered: 1, disponivel: 1, atencao: 0, fora_de_servico: 0, nunca_detectado: 0 })
    if (url.pathname === '/api/dashboard/atividade') return json(200, { items: [] })
    if (url.pathname === '/tipos-equipamento') return json(200, { items: [{ id: 1, nome: 'Maca' }, { id: 2, nome: 'Bomba' }] })
    if (url.pathname === '/localizacoes/arvore') {
      return json(200, [{ nome: '2º andar', setores: [{ nome: 'Bloco B', zonas: [{ id: 3, nome: 'Zona C' }, { id: 4, nome: 'Zona D' }] },
        { nome: 'Bloco E', zonas: [{ id: 5, nome: 'Zona C' }] }] }])
    }
    return json(200, [])
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

async function abrirPainel() {
  render(<App/>)
  const tabela = await screen.findByRole('table')
  fireEvent.click(within(tabela).getByRole('button', { name: /Maca 1/ }))
  return screen.getByRole('dialog')
}

async function abrirCorrecao(nome: 'Corrigir localização' | 'Corrigir cadastro') {
  const painel = await abrirPainel()
  fireEvent.click(within(painel).getByRole('button', { name: nome }))
  return within(await screen.findByRole('region', { name: nome }))
}

function preencherJustificativa(regiao: ReturnType<typeof within>, texto = 'Vista na sala D') {
  fireEvent.change(regiao.getByLabelText('Justificativa (obrigatória)'), { target: { value: texto } })
}

describe('correção manual no painel do equipamento', () => {
  it('sem a permissão equipamentos:corrigir os botões não aparecem', async () => {
    permissoes = ['equipamentos:consultar']
    const painel = await abrirPainel()
    expect(within(painel).queryByRole('heading', { name: 'Correção manual' })).not.toBeInTheDocument()
    expect(within(painel).queryByRole('button', { name: 'Corrigir localização' })).not.toBeInTheDocument()
    expect(within(painel).queryByRole('button', { name: 'Corrigir cadastro' })).not.toBeInTheDocument()
  })

  it('localização: mostra o atual, exige justificativa, revisa sem gravar e envia a versão vista', async () => {
    const regiao = await abrirCorrecao('Corrigir localização')
    expect(await regiao.findByRole('group', { name: 'Localização atual' })).toHaveTextContent('2º andar › Bloco B › Zona C')
    // Rótulo completo distingue zonas homônimas de setores diferentes.
    expect(regiao.getByRole('option', { name: '2º andar › Bloco E › Zona C' })).toBeInTheDocument()

    fireEvent.change(regiao.getByLabelText('Nova zona'), { target: { value: '4' } })
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    expect(regiao.getByRole('alert')).toHaveTextContent('Informe a justificativa')

    preencherJustificativa(regiao)
    fireEvent.change(regiao.getByLabelText(/Referência/), { target: { value: '  OS-9 ' } })
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    const tabela = regiao.getByRole('table', { name: 'Revise antes de confirmar' })
    expect(within(tabela).getByRole('row', { name: /Zona.*Zona C.*Zona D/ })).toBeInTheDocument()
    expect(posts).toEqual([])

    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))
    expect(await screen.findByText('Localização corrigida.')).toBeInTheDocument()
    expect(posts).toEqual([{ path: '/equipamentos/1/correcoes/localizacao',
      body: { zona_id: 4, justificativa: 'Vista na sala D', referencia: 'OS-9', versao_esperada: 3 } }])
    expect(await screen.findByText(/Correção manual: Vista na sala D \(ref\. OS-9\)/)).toBeInTheDocument()
  })

  it('mesma zona não grava: Nada a corrigir', async () => {
    const regiao = await abrirCorrecao('Corrigir localização')
    await regiao.findByRole('group', { name: 'Localização atual' })
    fireEvent.change(regiao.getByLabelText('Nova zona'), { target: { value: '3' } })
    preencherJustificativa(regiao)
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    expect(regiao.getByRole('alert')).toHaveTextContent('Nada a corrigir')
    expect(regiao.queryByRole('button', { name: 'Confirmar correção' })).not.toBeInTheDocument()
    expect(posts).toEqual([])
  })

  it('conflito recarrega a versão e a nova confirmação usa a versão nova', async () => {
    const regiao = await abrirCorrecao('Corrigir localização')
    await regiao.findByRole('group', { name: 'Localização atual' })
    fireEvent.change(regiao.getByLabelText('Nova zona'), { target: { value: '4' } })
    preencherJustificativa(regiao)
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    registro = { ...registro, versao: 4 }  // outra operação gravou no meio
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))

    expect(await regiao.findByText(/alterado por outra operação/)).toBeInTheDocument()
    expect(regiao.getByLabelText('Nova zona')).toHaveValue('4')
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))
    expect(await screen.findByText('Localização corrigida.')).toBeInTheDocument()
    expect(posts.map((post) => post.body.versao_esperada)).toEqual([3, 4])
  })

  it('erro de regra volta para a edição com a mensagem', async () => {
    const regiao = await abrirCorrecao('Corrigir localização')
    await regiao.findByRole('group', { name: 'Localização atual' })
    fireEvent.change(regiao.getByLabelText('Nova zona'), { target: { value: '4' } })
    preencherJustificativa(regiao)
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    proximaResposta = { status: 409, detail: { codigo: 'anterior_a_ultima_localizacao', mensagem: 'x' } }
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))

    expect(await regiao.findByRole('alert')).toHaveTextContent('não pode voltar no tempo')
    expect(regiao.getByLabelText('Nova zona')).toHaveValue('4')
    expect(regiao.getByLabelText('Justificativa (obrigatória)')).toHaveValue('Vista na sala D')
  })

  it('cadastro envia só o que mudou', async () => {
    const regiao = await abrirCorrecao('Corrigir cadastro')
    expect(await regiao.findByText('(atual: PAT-001)')).toBeInTheDocument()
    fireEvent.change(regiao.getByLabelText(/^Patrimônio/), { target: { value: ' PAT-101 ' } })
    preencherJustificativa(regiao, 'Patrimônio errado')
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    expect(within(regiao.getByRole('table')).getAllByRole('row')).toHaveLength(2)
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))

    expect(await screen.findByText('Cadastro corrigido.')).toBeInTheDocument()
    expect(posts).toEqual([{ path: '/equipamentos/1/correcoes/cadastro',
      body: { identificador_interno: 'PAT-101', justificativa: 'Patrimônio errado', versao_esperada: 3 } }])
  })

  it('conflito no cadastro não desfaz o campo que a outra operação mudou', async () => {
    const regiao = await abrirCorrecao('Corrigir cadastro')
    await regiao.findByText('(atual: PAT-001)')
    fireEvent.change(regiao.getByLabelText(/^Patrimônio/), { target: { value: 'PAT-101' } })
    preencherJustificativa(regiao, 'Patrimônio errado')
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    // Outra operação muda a DESCRIÇÃO enquanto a pessoa revisa o patrimônio.
    registro = { ...registro, descricao: 'Descrição da outra operação', versao: 4 }
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))

    expect(await regiao.findByText(/alterado por outra operação/)).toBeInTheDocument()
    expect(regiao.getByLabelText(/^Descrição/)).toHaveValue('Descrição da outra operação')
    expect(regiao.getByLabelText(/^Patrimônio/)).toHaveValue('PAT-101')
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))

    expect(await screen.findByText('Cadastro corrigido.')).toBeInTheDocument()
    expect(posts.at(-1)?.body).toEqual({ identificador_interno: 'PAT-101',
      justificativa: 'Patrimônio errado', versao_esperada: 4 })
    await waitFor(() => expect(registro.descricao).toBe('Descrição da outra operação'))
  })

  it('depois de corrigir, o painel recarrega o equipamento pelo ID, não pela busca textual', async () => {
    const regiao = await abrirCorrecao('Corrigir cadastro')
    await regiao.findByText('(atual: PAT-001)')
    fireEvent.change(regiao.getByLabelText(/^Patrimônio/), { target: { value: '1' } })
    preencherJustificativa(regiao, 'Etiqueta errada')
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    // A partir daqui, "1" casa com 21 equipamentos e o corrigido não está na 1ª página.
    buscaSemOEquipamento = true
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))
    expect(await screen.findByText('Cadastro corrigido.')).toBeInTheDocument()
    const painel = screen.getByRole('dialog')
    await waitFor(() => expect(within(painel).getByText('Maca · 1')).toBeInTheDocument())
    expect(within(painel).queryByText('Maca · PAT-001')).not.toBeInTheDocument()
    expect(within(painel).queryByText(/Não foi possível atualizar os detalhes/)).not.toBeInTheDocument()
  })

  it('a localização corrigida aparece no painel sem fechar e reabrir', async () => {
    const regiao = await abrirCorrecao('Corrigir localização')
    await regiao.findByRole('group', { name: 'Localização atual' })
    fireEvent.change(regiao.getByLabelText('Nova zona'), { target: { value: '4' } })
    preencherJustificativa(regiao)
    fireEvent.click(regiao.getByRole('button', { name: 'Revisar correção' }))
    fireEvent.click(regiao.getByRole('button', { name: 'Confirmar correção' }))
    expect(await screen.findByText('Localização corrigida.')).toBeInTheDocument()
    const painel = screen.getByRole('dialog')
    await waitFor(() => expect(within(painel).getByText('2º andar → Bloco B → Zona D')).toBeInTheDocument())
  })
})
