import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LayoutEditor } from '../components/simulador/LayoutEditor'
import { SimulatorControlPage } from '../pages/SimulatorControlPage'
import { inRange, zoneAt, type LayoutConfig, type Sessao } from '../services/simulacao'

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body })

const easy: LayoutConfig = {
  cenario: 'easy', proporcao: 880 / 560, destino: { andar: 'Laboratório RFID', setor: 'Bancada de testes' },
  zonas: [
    { chave: 'zona-a', nome: 'Zona A', cor: '#2f6fb2', area: { x: 1, y: 5, largura: 49, altura: 60 }, referencia_planta: 'sala-a', restrita: false },
    { chave: 'zona-b', nome: 'Zona B', cor: '#1f8a70', area: { x: 50, y: 5, largura: 49, altura: 60 }, referencia_planta: 'sala-b', restrita: false },
  ],
  portais: [{ chave: 'portal-easy', nome: 'Portal de teste RFID', zona_a: 'zona-a', zona_b: 'zona-b', posicao: { x: 50, y: 54 } }],
  leitores: [{ chave: 'leitor-easy', nome: 'Leitor EASY', reader_id: 'sim-easy-01', modelo: 'EZ700', posicao: { x: 50, y: 66 }, antenas: [
    { chave: 'antena-a', nome: 'Antena A', porta: 1, posicao: { x: 28, y: 66 }, alcance: 16, portal: 'portal-easy', lado: 'a', zona: 'zona-a' },
    { chave: 'antena-b', nome: 'Antena B', porta: 2, posicao: { x: 72, y: 66 }, alcance: 16, portal: 'portal-easy', lado: 'b', zona: 'zona-b' },
  ] }],
}

describe('geometria compartilhada com o motor', () => {
  it('usa a mesma distância corrigida pela proporção', () => {
    const antena = easy.leitores[0].antenas[0]
    expect(inRange({ x: 28, y: 66 }, antena, easy.proporcao)).toBe(true)
    expect(inRange({ x: 44, y: 66 }, antena, easy.proporcao)).toBe(true)
    expect(inRange({ x: 28, y: 92 }, antena, easy.proporcao)).toBe(false)
    expect(zoneAt(easy, { x: 70, y: 20 })?.nome).toBe('Zona B')
    expect(zoneAt(easy, { x: 50, y: 90 })).toBeNull()
  })
})

describe('editor da planta', () => {
  afterEach(cleanup)
  it('limita quatro antenas por leitor e mostra o aviso do DR Max', () => {
    let config = structuredClone(easy)
    const onChange = vi.fn((next: LayoutConfig) => { config = next })
    const { rerender } = render(<LayoutEditor config={config} onChange={onChange}/>)
    fireEvent.click(screen.getByRole('button', { name: /Leitor EASY · EZ700/ }))
    for (let i = 0; i < 3; i++) {
      const add = screen.getByRole('button', { name: 'Adicionar antena' })
      if ((add as HTMLButtonElement).disabled) break
      fireEvent.click(add)
      rerender(<LayoutEditor config={config} onChange={onChange}/>)
    }
    expect(config.leitores[0].antenas).toHaveLength(4)
    expect(new Set(config.leitores[0].antenas.map((a) => a.porta)).size).toBe(4)
    expect(screen.getByRole('button', { name: 'Adicionar antena' })).toBeDisabled()
    fireEvent.change(screen.getByRole('combobox', { name: 'Modelo' }), { target: { value: 'DR_MAX' } })
    rerender(<LayoutEditor config={config} onChange={onChange}/>)
    expect(screen.getByText(/integração física ao MQTT ainda não foi validada/)).toBeInTheDocument()
  })
})

describe('aba de controle', () => {
  let session: Sessao
  let calls: { url: URL; init: RequestInit }[]
  beforeEach(() => {
    calls = []
    session = { codigo: '0123456789abcdef', layout_id: 1, cenario: 'easy', estado: 'em_execucao', versao: 3, layout: easy,
      itens: [{ id: 'it-1', nome: 'Maca 1', tipo: 'Maca', epc: 'E2804C4100000000000000A1', x: 28, y: 66, x0: 8, y0: 94 },
        { id: 'it-2', nome: 'Cadeira', tipo: 'Cadeira', epc: null, x: 72, y: 66, x0: 24, y0: 94 }],
      iniciada_em: new Date().toISOString(), atualizada_em: new Date().toISOString(), encerrada_em: null,
      motor: { ativo: true, lider: true, conectado: true, erro: null, destino: 'mqtt://localhost:1883', pendentes: 0, sessao: { publicadas: 12, no_alcance: {}, ultima_deteccao: {}, erro: null } } }
    vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push({ url, init })
      if (url.pathname.endsWith('/itens') && init.method === 'POST') return json({ ...session, versao: 4 }, 201)
      return json(session)
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('mostra leitura só do item etiquetado e publica pelo servidor', async () => {
    render(<SimulatorControlPage codigo={session.codigo} canEdit/>)
    expect(await screen.findByRole('button', { name: 'Maca 1, sendo lido' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cadeira (sem etiqueta)' })).toBeInTheDocument()
    expect(screen.getByText(/12 leitura\(s\) publicada\(s\)/)).toBeInTheDocument()
    expect(await screen.findByText(/não tem etiqueta: nenhuma leitura/)).toBeInTheDocument()
  })

  it('adiciona equipamento sem etiqueta', async () => {
    render(<SimulatorControlPage codigo={session.codigo} canEdit/>)
    await screen.findByRole('button', { name: 'Maca 1, sendo lido' })
    fireEvent.change(screen.getByPlaceholderText('Ex.: Maca 1'), { target: { value: 'Cadeira 2' } })
    fireEvent.click(screen.getByLabelText(/Sem etiqueta/))
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar à planta' }))
    await vi.waitFor(() => expect(calls.some((call) => call.init.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find((call) => call.init.method === 'POST')!.init.body))
    expect(body).toMatchObject({ nome: 'Cadeira 2', gerar_epc: false })
    expect(body.epc).toBeUndefined()
  })

  it('perfil de consulta não vê controles de alteração', async () => {
    render(<SimulatorControlPage codigo={session.codigo} canEdit={false}/>)
    await screen.findByRole('button', { name: 'Maca 1, sendo lido' })
    expect(screen.queryByRole('button', { name: 'Adicionar à planta' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pausar' })).toBeNull()
  })
})
