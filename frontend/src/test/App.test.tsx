import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { StatusBadge } from '../components/DashboardParts'
import type { DetectionStatus } from '../types/dashboard'

beforeEach(() => { window.history.replaceState(null, '', '/'); window.location.hash = '' })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('sinais de recência', () => {
  it.each<[DetectionStatus, string]>([['recent', 'Recente'], ['outdated', 'Desatualizada'], ['never', 'Nunca detectado']])('combina símbolo e texto para %s', (status, label) => {
    const { container } = render(<StatusBadge status={status}/>)
    expect(container.querySelector('.status-badge')).toHaveTextContent(label)
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument()
  })
})

describe('dashboard e mapas demonstrativos', () => {
  it('preserva resumo, última zona e recência da Etapa A', async () => {
    render(<App/>)
    expect(screen.getByText('Rastreamento RFID')).toBeInTheDocument()
    expect(await screen.findByText('Total de equipamentos')).toBeInTheDocument()
    expect(screen.getByText('Disponíveis')).toBeInTheDocument()
    expect(screen.getAllByText('Atenção necessária').length).toBeGreaterThan(0)
    const row = within(screen.getByRole('table')).getByRole('button', { name: /Cadeira de Rodas 12/ }).closest('tr')!
    expect(row).toHaveTextContent('4º andar › Centro Cirúrgico')
    expect(row).toHaveTextContent('Recente')
  })

  it('não inventa zona para equipamento nunca detectado e abre o detalhe', async () => {
    render(<App/>)
    const button = await screen.findByRole('button', { name: /Carrinho de Emergência 03/ })
    const row = button.closest('tr')!
    expect(row).toHaveTextContent('Nenhuma localização registrada')
    expect(row).toHaveTextContent('Nunca detectado')
    fireEvent.click(button)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Nenhuma localização registrada')
    expect(dialog).toHaveTextContent('Nenhuma leitura registrada')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('preserva estados vazio e erro', async () => {
    window.history.replaceState(null, '', '/?estado=vazio')
    const { unmount } = render(<App/>)
    expect(await screen.findByText('Nenhum equipamento cadastrado')).toBeInTheDocument()
    expect(screen.getByText('Total de equipamentos')).toBeInTheDocument()
    unmount()
    window.history.replaceState(null, '', '/?estado=erro')
    render(<App/>)
    expect(await screen.findByRole('alert')).toHaveTextContent('Não foi possível carregar as informações.')
    expect(screen.queryByRole('button', { name: /Cadeira de Rodas 12/ })).not.toBeInTheDocument()
  })

  it('busca pelo patrimônio sem alterar os dados de demonstração', async () => {
    render(<App/>)
    await screen.findByText('Total de equipamentos')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'PAT-3170' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    const table = screen.getByRole('table')
    expect(within(table).getByRole('button', { name: /Maca 07/ })).toBeInTheDocument()
    expect(within(table).queryByRole('button', { name: /Cadeira de Rodas 12/ })).not.toBeInTheDocument()
  })

  it('alterna mapas sem reload e abre o mesmo detalhe pelo marcador', async () => {
    render(<App/>)
    fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Mapa / Planta' })).toBeInTheDocument())
    expect(screen.getByRole('tabpanel', { name: 'Mapa do Hospital (HUPAA)' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Monitor Multiparamétrico 05.*PAT-2205/ }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Monitor Multiparamétrico 05')
    fireEvent.click(screen.getByRole('button', { name: 'Fechar painel' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Laboratório de Testes (EASY)' }))
    expect(screen.getByRole('tabpanel', { name: 'Laboratório de Testes (EASY)' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/mapa')
  })

  it('filtra marcadores no hospital e registra leitura simulada no laboratório', async () => {
    render(<App/>)
    fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
    await waitFor(() => expect(screen.getByRole('tabpanel', { name: 'Mapa do Hospital (HUPAA)' })).toBeInTheDocument())
    const zoneSelect = screen.getByRole('combobox', { name: 'Zona' })
    fireEvent.change(zoneSelect, { target: { value: 'servico' } })
    expect(screen.getByText('1 de 8 na planta')).toBeInTheDocument()
    const mapMarker = screen.getByRole('button', { name: /Bomba de Infusão 14.*PAT-2104/ })
    expect(mapMarker).toHaveClass('marker-dimmed')
    fireEvent.click(screen.getByRole('tab', { name: 'Laboratório de Testes (EASY)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Leitura na Sala A' }))
    expect(screen.getByText('E2000017221101441890A001')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Log de leituras' })).getByText('Sala A')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Antena A. Sala A' })).toHaveClass('marker-pulse')
  })
})
