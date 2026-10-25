import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LayoutEditor } from '../components/simulador/LayoutEditor'
import { SimulatorControlPage } from '../pages/SimulatorControlPage'
import { inRange, pendencias, zoneAt, type LayoutConfig, type Sessao } from '../services/simulacao'

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

  it('portal novo já vem com leitor e antenas A e B, cada uma na sua zona e sem sobreposição', () => {
    let config: LayoutConfig = { ...structuredClone(easy), portais: [], leitores: [] }
    const onChange = vi.fn((next: LayoutConfig) => { config = next })
    const { rerender } = render(<LayoutEditor config={config} onChange={onChange}/>)
    expect(pendencias(config)).toEqual(['Crie um portal entre duas zonas.'])
    fireEvent.click(screen.getByRole('button', { name: 'Novo portal' }))
    fireEvent.click(screen.getByRole('button', { name: 'Criar portal' }))
    rerender(<LayoutEditor config={config} onChange={onChange}/>)
    const [leitor] = config.leitores
    expect(config.portais[0].posicao).not.toBeNull()
    expect(leitor.reader_id).toBe('sim-easy-01')
    expect(leitor.antenas.map((a) => [a.lado, a.zona])).toEqual([['a', 'zona-a'], ['b', 'zona-b']])
    expect(zoneAt(config, leitor.antenas[0].posicao!)?.chave).toBe('zona-a')
    expect(zoneAt(config, leitor.antenas[1].posicao!)?.chave).toBe('zona-b')
    expect(inRange(leitor.antenas[1].posicao!, leitor.antenas[0], config.proporcao)).toBe(false)
    expect(pendencias(config)).toEqual([])
  })

  it('identifica o leitor da zona restrita e avisa antenas no mesmo ponto', () => {
    const config: LayoutConfig = structuredClone(easy)
    config.zonas.push({ chave: 'escada', nome: 'Escada', cor: '#7a3fb2', area: { x: 1, y: 70, largura: 20, altura: 25 }, referencia_planta: null, restrita: true })
    config.portais.push({ chave: 'p-escada', nome: 'Zona A ↔ Escada', zona_a: 'zona-a', zona_b: 'escada', posicao: null })
    config.leitores.push({ chave: 'leitor-4', nome: 'Leitor 4', reader_id: 'sim-easy-04', modelo: 'DR_MAX', posicao: { x: 10, y: 80 }, antenas: [
      { chave: 'l4-a1', nome: 'Antena 1', porta: 1, posicao: { x: 10, y: 85 }, alcance: 3, portal: 'p-escada', lado: 'b', zona: 'escada' },
      { chave: 'l4-a2', nome: 'Antena 2', porta: 2, posicao: { x: 10, y: 85 }, alcance: 3, portal: null, lado: null, zona: 'escada' }] })
    config.leitores[0].antenas.push({ chave: 'antena-c', nome: 'Antena C', porta: 3, posicao: { x: 10, y: 45 }, alcance: 3, portal: 'p-escada', lado: 'a', zona: 'zona-a' })
    render(<LayoutEditor config={config} onChange={vi.fn()}/>)
    expect(screen.getByText('zona restrita')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Leitor 4 · DR Max/ }))
    expect(screen.getByText('Leitor da zona restrita.')).toBeInTheDocument()
    // Antena sem portal no mesmo ponto: aviso. Lado B de dois portais no mesmo ponto: ponto único válido.
    expect(pendencias(config).join(' ')).toMatch(/Antena 1 e Leitor 4 \/ Antena 2 estão no mesmo ponto/)
    config.portais.push({ chave: 'p-escada-2', nome: 'Zona B ↔ Escada', zona_a: 'zona-b', zona_b: 'escada', posicao: null })
    Object.assign(config.leitores[1].antenas[1], { portal: 'p-escada-2', lado: 'b' })
    config.leitores[0].antenas.push({ chave: 'antena-d', nome: 'Antena D', porta: 4, posicao: { x: 70, y: 45 }, alcance: 3, portal: 'p-escada-2', lado: 'a', zona: 'zona-b' })
    expect(pendencias(config).join(' ')).not.toMatch(/mesmo ponto/)
    const sobreposto = structuredClone(easy)
    sobreposto.leitores[0].antenas[1].posicao = { x: 40, y: 66 }
    expect(pendencias(sobreposto).join(' ')).toMatch(/lados A e B se sobrepõem/)
  })

  it('limpar planta apaga tudo depois de confirmar e mostra o passo a passo', () => {
    let config = structuredClone(easy)
    const onChange = vi.fn((next: LayoutConfig) => { config = next })
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const { rerender } = render(<LayoutEditor config={config} onChange={onChange}/>)
    fireEvent.click(screen.getByRole('button', { name: 'Limpar planta' }))
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Limpar planta' }))
    rerender(<LayoutEditor config={config} onChange={onChange}/>)
    expect([config.zonas, config.portais, config.leitores]).toEqual([[], [], []])
    expect(screen.getByText('Desenhe as zonas')).toBeInTheDocument()
    expect(pendencias(config)).toEqual(['Desenhe pelo menos duas zonas.'])
    vi.restoreAllMocks()
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

  it('adiciona em um clique e remove todos depois de confirmar', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<SimulatorControlPage codigo={session.codigo} canEdit/>)
    await screen.findByRole('button', { name: 'Maca 1, sendo lido' })
    fireEvent.click(screen.getByRole('button', { name: '+ Cadeira de rodas' }))
    await vi.waitFor(() => expect(calls.some((call) => call.init.method === 'POST')).toBe(true))
    expect(JSON.parse(String(calls.find((call) => call.init.method === 'POST')!.init.body))).toMatchObject({ tipo: 'Cadeira de rodas', gerar_epc: true })
    fireEvent.click(screen.getByRole('button', { name: 'Remover todos' }))
    await vi.waitFor(() => expect(calls.some((call) => call.init.method === 'DELETE' && call.url.pathname.endsWith('/itens'))).toBe(true))
    vi.restoreAllMocks()
  })

  it('perfil de consulta não vê controles de alteração', async () => {
    render(<SimulatorControlPage codigo={session.codigo} canEdit={false}/>)
    await screen.findByRole('button', { name: 'Maca 1, sendo lido' })
    expect(screen.queryByRole('button', { name: 'Adicionar à planta' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pausar' })).toBeNull()
  })
})
