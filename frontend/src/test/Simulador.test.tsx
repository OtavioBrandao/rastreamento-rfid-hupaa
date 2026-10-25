import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LayoutEditor, redimensionar } from '../components/simulador/LayoutEditor'
import { SimulatorControlPage } from '../pages/SimulatorControlPage'
import { aplicarPadroesDeAntena, alcanceNaDirecao, contornoCobertura, inRange, pendencias, zoneAt, type LayoutConfig, type Sessao } from '../services/simulacao'

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

describe('antena direcional', () => {
  it('lê mais longe na visada e pouco atrás; desenha o mesmo contorno', () => {
    const antena = { ...easy.leitores[0].antenas[0], posicao: { x: 50, y: 50 }, alcance: 4, orientacao: 0, fator_traseiro: 0.35 }
    expect(inRange({ x: 53.8, y: 50 }, antena, 1)).toBe(true)
    expect(inRange({ x: 46.5, y: 50 }, antena, 1)).toBe(false)
    expect(inRange({ x: 48.8, y: 50 }, antena, 1)).toBe(true)
    const baixo = { ...antena, orientacao: 90 }
    expect(inRange({ x: 50, y: 53.8 }, baixo, 1)).toBe(true)
    expect(inRange({ x: 50, y: 46.5 }, baixo, 1)).toBe(false)
    expect(alcanceNaDirecao(antena, 0)).toBeCloseTo(4)
    expect(alcanceNaDirecao(antena, Math.PI)).toBeCloseTo(1.4)
    expect(contornoCobertura(antena, 1)).toMatch(/^M54\.00,50\.00 L/)
    const antiga = { ...antena, orientacao: null }
    expect(inRange({ x: 46.5, y: 50 }, antiga, 1)).toBe(true)
  })

  it('aplica novos padrões só em antenas antigas, sem mexer em posições', () => {
    const antigo = structuredClone(easy)
    const novo = aplicarPadroesDeAntena(antigo)
    const [a, b] = novo.leitores[0].antenas
    expect(a.posicao).toEqual(antigo.leitores[0].antenas[0].posicao)
    // Centro das salas fica acima das antenas: visada para cima (pouco inclinada para o centro de cada sala).
    expect(a.orientacao).toBeGreaterThan(250); expect(a.orientacao).toBeLessThan(270)
    expect(b.orientacao).toBeGreaterThan(270); expect(b.orientacao).toBeLessThan(290)
    expect(a.alcance).toBe(11)
    expect(aplicarPadroesDeAntena(novo)).toEqual(novo)
  })
})

describe('áreas', () => {
  it('redimensiona por qualquer borda ou canto sem sair da planta', () => {
    const area = { x: 10, y: 10, largura: 20, altura: 20 }
    expect(redimensionar(area, 'e', 5, 0)).toEqual({ x: 10, y: 10, largura: 25, altura: 20 })
    expect(redimensionar(area, 'w', -15, 0)).toEqual({ x: 0, y: 10, largura: 30, altura: 20 })
    expect(redimensionar(area, 'n', 0, 30)).toEqual({ x: 10, y: 28, largura: 20, altura: 2 })
    expect(redimensionar(area, 'se', 200, 200)).toEqual({ x: 10, y: 10, largura: 90, altura: 90 })
    expect(redimensionar(area, 'nw', 5, 5)).toEqual({ x: 15, y: 15, largura: 15, altura: 15 })
    expect(redimensionar(area, 'mover', 200, -50)).toEqual({ x: 80, y: 0, largura: 20, altura: 20 })
  })
})

describe('editor da planta', () => {
  afterEach(cleanup)

  it('seleciona a área pela lista, mostra as 8 alças e aceita valores numéricos', () => {
    let config = structuredClone(easy)
    const onChange = vi.fn((next: LayoutConfig) => { config = next })
    const { rerender } = render(<LayoutEditor config={config} onChange={onChange}/>)
    fireEvent.click(screen.getByRole('button', { name: 'Zona A' }))
    expect(document.querySelectorAll('.sim-handle')).toHaveLength(8)
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Largura' }), { target: { value: '30' } })
    rerender(<LayoutEditor config={config} onChange={onChange}/>)
    expect(config.zonas[0].area).toEqual({ x: 1, y: 5, largura: 30, altura: 60 })
  })

  it('gira a visada da antena pela rosa dos ventos', () => {
    let config = structuredClone(easy)
    const onChange = vi.fn((next: LayoutConfig) => { config = next })
    const { rerender } = render(<LayoutEditor config={config} onChange={onChange}/>)
    fireEvent.click(screen.getByRole('button', { name: /Leitor EASY · EZ700/ }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Visada baixo (90°)' })[0])
    rerender(<LayoutEditor config={config} onChange={onChange}/>)
    expect(config.leitores[0].antenas[0].orientacao).toBe(90)
    expect(screen.getAllByText(/Visada direta: ↓ baixo \(90°\)/)[0]).toBeInTheDocument()
  })
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
    expect(screen.getByText('Leitor da área restrita.')).toBeInTheDocument()
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
  let monitor: Record<string, unknown>
  let patch: (url: URL, init: RequestInit) => Promise<unknown> | unknown
  beforeEach(() => {
    calls = []
    monitor = { gerado_em: new Date().toISOString(), leituras_total: 3, leituras: [], tags: [], passagens: [], zonas: {}, leitores: [], alertas_restritos: [] }
    patch = (_url, init) => json({ codigo: session.codigo, versao: session.versao + 1, itens: session.itens.map((item) => item.id === 'it-1' ? { ...item, ...JSON.parse(String(init.body)) } : item) })
    session = { codigo: '0123456789abcdef', layout_id: 1, cenario: 'easy', estado: 'em_execucao', versao: 3, layout: easy,
      itens: [{ id: 'it-1', nome: 'Maca 1', tipo: 'Maca', epc: 'E2804C4100000000000000A1', x: 28, y: 66, x0: 8, y0: 94 },
        { id: 'it-2', nome: 'Cadeira', tipo: 'Cadeira', epc: null, x: 72, y: 66, x0: 24, y0: 94 }],
      iniciada_em: new Date().toISOString(), atualizada_em: new Date().toISOString(), encerrada_em: null,
      motor: { ativo: true, lider: true, conectado: true, erro: null, destino: 'mqtt://localhost:1883', pendentes: 0, sessao: { publicadas: 12, no_alcance: {}, ultima_deteccao: {}, erro: null } } }
    vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push({ url, init })
      if (url.pathname.endsWith('/monitor')) return json(monitor)
      if (url.pathname.endsWith('/itens') && init.method === 'POST') return json({ ...session, versao: 4 }, 201)
      if (init.method === 'PATCH') return patch(url, init)
      return json(session)
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('mostra leitura só do item etiquetado e publica pelo servidor', async () => {
    render(<SimulatorControlPage codigo={session.codigo} canEdit/>)
    expect(await screen.findByRole('button', { name: 'Maca 1, sendo lido' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cadeira (sem etiqueta)' })).toBeInTheDocument()
    expect(screen.getByText(/12 publicada\(s\)/)).toBeInTheDocument()
    expect(await screen.findByText(/sem etiqueta: nenhuma leitura/)).toBeInTheDocument()
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

  it('resposta antiga do arraste não desfaz a posição final', async () => {
    const respostas: ((valor: unknown) => void)[] = []
    patch = () => new Promise((resolve) => { respostas.push(resolve) })
    const { container } = render(<SimulatorControlPage codigo={session.codigo} canEdit/>)
    const maca = await screen.findByRole('button', { name: 'Maca 1, sendo lido' })
    const plano = container.querySelector('.sim-plan') as HTMLElement
    plano.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.pointerDown(maca, { clientX: 28, clientY: 66 })
    fireEvent.pointerMove(plano, { clientX: 40, clientY: 66 })
    fireEvent.pointerUp(plano, { clientX: 40, clientY: 66 })
    await vi.waitFor(() => expect(respostas.length).toBe(2))
    const item = (x: number, versao: number) => json({ codigo: session.codigo, versao, itens: [{ ...session.itens[0], x, y: 66 }, session.itens[1]] })
    // Chega primeiro a resposta do último envio (x=40) e depois a do primeiro (x=40 também, versão menor).
    respostas[1](item(40, 6)); respostas[0](item(28, 5))
    await vi.waitFor(() => expect((container.querySelector('.sim-item.tagged') as HTMLElement).style.left).toBe('40%'))
  })

  it('mostra o alerta de área restrita vindo do sistema', async () => {
    monitor.alertas_restritos = [{ epc: 'E2804C4100000000000000A1', zona: 'Escada', leitor: 'Leitor 5 · área restrita', reader_id: 'sim-hupaa-05', antena: 'Antena 1', porta: 1, leituras: 4,
      primeira_leitura_em: new Date().toISOString(), ultima_leitura_em: new Date().toISOString(), recente: true, equipamento: { id: 1, nome: 'Maca 01' } }]
    render(<SimulatorControlPage codigo={session.codigo} canEdit/>)
    expect(await screen.findByText('1 item(ns) na área restrita agora')).toBeInTheDocument()
    expect(screen.getByText('Maca 01')).toBeInTheDocument()
  })

  it('perfil de consulta não vê controles de alteração', async () => {
    render(<SimulatorControlPage codigo={session.codigo} canEdit={false}/>)
    await screen.findByRole('button', { name: 'Maca 1, sendo lido' })
    expect(screen.queryByRole('button', { name: 'Adicionar à planta' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pausar' })).toBeNull()
  })
})
