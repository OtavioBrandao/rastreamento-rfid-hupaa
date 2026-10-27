import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MapaHUAoVivo } from '../components/mapa/MapaHUAoVivo'
import { MapWorkspace, statusDominante } from '../components/mapa/MapWorkspace'
import { labMainZones } from '../config/mapaConfig'
import type { BoundZone } from '../services/mapTopology'
import type { LayoutConfig } from '../services/simulacao'
import type { AssetStatus, EquipmentItem } from '../types/dashboard'

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body })
const agora = () => new Date().toISOString()

const config: LayoutConfig = {
  cenario: 'hupaa', proporcao: 2.05, destino: null,
  zonas: [
    { chave: 'zona-1', nome: 'Zona 1', cor: '#2f6fb2', area: { x: 13, y: 1, largura: 34, altura: 47 }, referencia_planta: null, restrita: false },
    { chave: 'zona-2', nome: 'Zona 2', cor: '#1f8a70', area: { x: 60, y: 3, largura: 39, altura: 44 }, referencia_planta: null, restrita: false },
    { chave: 'escada', nome: 'Circulação vertical (escada)', cor: '#7a3fb2', area: { x: 37, y: 54, largura: 12, altura: 15 }, referencia_planta: null, restrita: true },
  ],
  portais: [{ chave: 'portal-1-2', nome: 'Zona 1 ↔ Zona 2', zona_a: 'zona-1', zona_b: 'zona-2', posicao: { x: 53, y: 24 } }],
  leitores: [
    { chave: 'leitor-1', nome: 'Leitor 1', reader_id: 'sim-hupaa-01', modelo: 'EZ700', posicao: { x: 50, y: 30 }, antenas: [
      { chave: 'l1-a', nome: 'Antena 1', porta: 1, posicao: { x: 45, y: 29 }, alcance: 4, orientacao: 0, portal: 'portal-1-2', lado: 'a', zona: 'zona-1' }] },
    { chave: 'leitor-4', nome: 'Leitor 4', reader_id: 'sim-hupaa-04', modelo: 'DR_MAX', posicao: { x: 44, y: 60 }, alerta_area_restrita: true, antenas: [
      { chave: 'l4-a', nome: 'Antena 1', porta: 1, posicao: { x: 43, y: 61 }, alcance: 4, orientacao: null, portal: null, lado: null, zona: 'escada' }] },
  ],
}

const equipamento = (id: number, nome: string, status: AssetStatus, zona: number | null): EquipmentItem => ({
  id, nome, identificador_interno: `DEMO-HU-${id}`, tipo: 'Maca', tipo_id: 1, epc: `E2804C41000000000000A1${String(id).padStart(2, '0')}`, status,
  ultima_zona: zona ? { id: zona, nome: `Zona ${zona}`, referencia_planta: null, andar: 'HU', setor: 'HU', caminho: `HU / Zona ${zona}` } : null,
  ultima_deteccao_em: zona ? agora() : null, localizacao_desatualizada: null,
})

describe('acompanhamento do HU', () => {
  let monitor: Record<string, unknown>
  let sessoes: unknown[]
  beforeEach(() => {
    sessionStorage.clear()
    sessoes = [{ codigo: 'abcdef0123456789', layout_id: 1, cenario: 'hupaa', estado: 'em_execucao', versao: 2, itens: 9, iniciada_em: agora() }]
    monitor = { gerado_em: agora(), leituras_total: 1, tags: [], zonas: {}, leitores: [], alertas_restritos: [], equipamentos: [],
      leituras: [{ id: 5, epc: 'X', reader_id: 'sim-hupaa-01', porta: 1, antena: 'l1-a', lido_em: agora(), rssi: null, equipamento: null }],
      passagens: [{ id: 7, epc: 'E1', portal: 'Zona 1 ↔ Zona 2', direcao: 'a_para_b', direcao_status: 'confirmed', zona_origem: 'Zona 1', zona_destino: 'Zona 2', detectada_em: agora(), equipamento: 'Maca HU-03' }] }
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/simulacao/layouts') return json([{ id: 1, nome: 'Hospital HUPAA (padrão)', cenario: 'hupaa', configuracao: config, versao: 11, arquivado: false,
        aplicado_em: agora(), updated_at: agora(), avisos: [], zonas_ids: { 'zona-1': 41, 'zona-2': 42, escada: 43 } }])
      if (url.pathname === '/api/simulacao/sessoes') return json(sessoes)
      if (url.pathname.endsWith('/monitor')) return json(structuredClone(monitor))  // cada consulta é um objeto novo
      return json({})
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  const itens = [equipamento(1, 'Bomba HU-01', 'atencao', 41), equipamento(2, 'Monitor HU-02', 'atencao', 41), equipamento(3, 'Maca HU-03', 'disponivel', 42)]
  const topology = { zones: [], portals: [] }

  it('zona recolhida em um ícone com a quantidade; clicar expande e clicar de novo (ou fora) recolhe', async () => {
    const { container } = render(<MapaHUAoVivo topology={topology} items={itens} onSelect={() => undefined}/>)
    const zona1 = await screen.findByRole('button', { name: /^2 equipamentos em Zona 1, maioria atenção/ })
    expect(zona1).toHaveClass('marker-atencao')
    expect(zona1).toHaveTextContent('2')
    expect(screen.queryByRole('button', { name: /^Bomba HU-01/ })).toBeNull()
    fireEvent.click(zona1)
    const bomba = screen.getByRole('button', { name: 'Bomba HU-01: Atenção. Abrir detalhes' })
    expect(bomba).toHaveClass('marker-individual')
    expect(screen.getByRole('button', { name: 'Monitor HU-02: Atenção. Abrir detalhes' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^2 equipamentos em Zona 1/ }))
    expect(screen.queryByRole('button', { name: /^Bomba HU-01/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /^2 equipamentos em Zona 1/ }))
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('button', { name: /^Bomba HU-01/ })).toBeNull()
    // Planta original do HU com limites e leitores por cima; sem controles de tempo nem resumo antigo.
    expect(screen.getByRole('img', { name: 'Esquema do segundo pavimento do HUPAA' })).toBeInTheDocument()
    expect(container.querySelectorAll('.hu-limite')).toHaveLength(3)
    expect(screen.getByRole('button', { name: /^Leitor 4\. DR Max|^Leitor 4\. Identix DR Max/ })).toBeInTheDocument()
    expect(screen.queryByText(/HU ao vivo/)).toBeNull()
    expect(screen.queryByRole('button', { name: '+30 min' })).toBeNull()
    expect(screen.queryByLabelText('Velocidade')).toBeNull()
  })

  it('item só lido (sem transição) fica perto da antena como zona não confirmada, fora da contagem da zona', async () => {
    const lido = { ...equipamento(9, 'Maca nova', 'nunca_detectado', null), ultima_leitura: { em: agora(), leitor: 'sim-hupaa-01', porta: 1, zona: 'Zona 1' } }
    render(<MapaHUAoVivo topology={topology} items={[...itens, lido]} onSelect={() => undefined}/>)
    const marcador = await screen.findByRole('button', { name: 'Maca nova: zona não confirmada, visto perto da antena. Abrir detalhes' })
    expect(marcador).toHaveClass('marker-nao-confirmado')
    expect(screen.getByRole('button', { name: /^2 equipamentos em Zona 1/ })).toBeInTheDocument()  // não entrou na Zona 1
    fireEvent.click(screen.getByRole('tab', { name: /Zona não confirmada/ }))
    expect(within(screen.getByRole('tabpanel', { name: /Zona não confirmada/ })).getByText(/Zona não confirmada · visto perto da Zona 1/)).toBeInTheDocument()
  })

  it('mostra as mesmas abas do EASY e as passagens detalhadas; cobertura opcional abaixo da legenda', async () => {
    const { container } = render(<MapaHUAoVivo topology={topology} items={itens} onSelect={() => undefined}/>)
    for (const aba of ['Equipamentos detectados', 'Ativos nas salas', 'Zonas e portais', 'Zona não confirmada', 'Outras zonas'])
      expect(await screen.findByRole('tab', { name: new RegExp(aba) })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Passagens detalhadas/ }))
    const linha = await screen.findByText(/Maca HU-03 saiu da Zona 1 e entrou na Zona 2 pelo .* — passagem confirmada/)
    expect(linha).toHaveClass('hu-ev-ok')
    expect(linha.querySelector('time')?.textContent).toMatch(/^[0-9]{2}:[0-9]{2}:[0-9]{2}$/)
    expect(screen.queryByText('Entradas, saídas e detecções')).toBeNull()
    expect(container.querySelector('.hu-cobertura')).toBeNull()
    const toggle = screen.getByLabelText(/Áreas de cobertura/)
    expect(toggle.closest('.hu-legenda')).not.toBeNull()
    fireEvent.click(toggle)
    expect(container.querySelectorAll('.hu-cobertura')).toHaveLength(2)
  })

  it('notifica uma vez a entrada confirmada na zona restrita, sem repetir enquanto o item fica lá', { timeout: 15000 }, async () => {
    const entrada = agora()
    monitor.alertas_restritos = [{ epc: 'E2804C41000000000000A107', entrada_em: entrada, zona: 'Circulação vertical (escada)', leitor: 'Leitor 4', reader_id: 'sim-hupaa-04',
      antena: 'Antena 1', porta: 1, leituras: 3, primeira_leitura_em: entrada, ultima_leitura_em: agora(), recente: true, equipamento: { id: 7, nome: 'Maca HU-07' } }]
    render(<MapaHUAoVivo topology={topology} items={itens} onSelect={() => undefined}/>)
    expect(await screen.findByText(/Maca HU-07 entrou na área restrita/)).toBeInTheDocument()
    // No mapa, a zona restrita pisca e o aviso diz que é atividade suspeita.
    expect(document.querySelector('.hu-zona-fundo.restrita.alerta')).not.toBeNull()
    expect(screen.getByText('Atividade suspeita')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Cores da planta do HU' })).toHaveTextContent(/Circulação vertical.*Sala de aula.*Corredores.*Pacientes.*Serviço/)
    expect(screen.getByRole('list', { name: 'Cores da planta do HU' })).not.toHaveTextContent(/Administrativo/)
    fireEvent.click(screen.getByRole('button', { name: 'Dispensar notificação' }))
    // Várias consultas depois, o item continua na zona: nenhuma notificação nova.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 3500)) })
    expect(screen.queryByText(/Maca HU-07 entrou na área restrita/)).toBeNull()
    // Saiu e voltou: nova entrada, nova notificação (uma só).
    monitor.alertas_restritos = [{ ...(monitor.alertas_restritos as object[])[0], entrada_em: new Date(Date.now() + 1000).toISOString() }]
    expect(await screen.findByText(/Maca HU-07 entrou na área restrita/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getAllByText(/Maca HU-07 entrou na área restrita/)).toHaveLength(1)
  })
})

describe('mapa do EASY também agrupa por zona', () => {
  afterEach(cleanup)
  it('ícone único com a cor da maioria e expansão dentro da sala', () => {
    const zones: BoundZone[] = labMainZones.map((zona, i) => ({ ...zona, zoneId: 10 + i }))
    const sala = (id: number, status: AssetStatus) => ({ ...equipamento(id, `Item ${id}`, status, null),
      ultima_zona: { id: 10, nome: 'Sala A', referencia_planta: 'sala-a', andar: 'Lab', setor: 'Lab', caminho: 'Lab / Sala A' }, ultima_deteccao_em: agora() })
    render(<MapWorkspace mode="lab" zones={zones} portals={[]} items={[sala(1, 'disponivel'), sala(2, 'disponivel'), sala(3, 'fora_de_servico')]} onSelect={() => undefined}/>)
    const icone = screen.getByRole('button', { name: /^3 equipamentos em Sala A, maioria disponível/ })
    expect(icone).toHaveClass('marker-disponivel')
    fireEvent.click(icone)
    const itens = screen.getAllByRole('button', { name: /^Item \d: / })
    expect(itens).toHaveLength(3)
    for (const item of itens) {  // dentro dos limites da Sala A (x 1–50, y 5–65)
      expect(parseFloat(item.style.left)).toBeGreaterThan(1)
      expect(parseFloat(item.style.left)).toBeLessThan(50)
    }
  })

  it('empate de categorias fica com a de maior alerta', () => {
    const lista = [equipamento(1, 'A', 'disponivel', 1), equipamento(2, 'B', 'atencao', 1)]
    expect(statusDominante(lista)).toBe('atencao')
    expect(statusDominante([...lista, equipamento(3, 'C', 'fora_de_servico', 1), equipamento(4, 'D', 'fora_de_servico', 1)])).toBe('fora_de_servico')
    expect(statusDominante([equipamento(5, 'E', 'disponivel', 1), equipamento(6, 'F', 'disponivel', 1), equipamento(7, 'G', 'atencao', 1)])).toBe('disponivel')
  })
})
