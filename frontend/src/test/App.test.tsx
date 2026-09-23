import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { StatusBadge } from '../components/DashboardParts'
import type { DetectionStatus } from '../types/dashboard'

beforeEach(() => { window.history.replaceState(null, '', '/'); window.location.hash = '' })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('StatusBadge', () => {
  it.each<[DetectionStatus, string]>([
    ['recent', 'Recente'],
    ['outdated', 'Desatualizada'],
    ['never', 'Nunca detectado'],
  ])('exibe texto acessível para %s', (status, label) => {
    const { container } = render(<StatusBadge status={status} />)
    expect(container.querySelector('.status-badge')).toHaveTextContent(label)
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument()
  })
})

describe('Etapa A do dashboard', () => {
  it('mostra título, cards e última zona com estado', async () => {
    render(<App />)
    expect(screen.getByText('Rastreamento RFID')).toBeInTheDocument()
    expect(await screen.findByText('Equipamentos cadastrados')).toBeInTheDocument()
    expect(screen.getByText('Detectados recentemente')).toBeInTheDocument()
    expect(screen.getByText('Localizações desatualizadas')).toBeInTheDocument()
    expect(screen.getByText('Nunca detectados')).toBeInTheDocument()
    expect(screen.getByText('4º andar › Centro Cirúrgico')).toBeInTheDocument()
    expect(screen.getAllByText(/Recente/).length).toBeGreaterThan(0)
  })

  it('não inventa zona para equipamento nunca detectado', async () => {
    render(<App />)
    const name = await screen.findByText('Carrinho de Emergência 03')
    const row = name.closest('li')!
    expect(row).toHaveTextContent('Nenhuma localização registrada')
    expect(row).toHaveTextContent('Nunca detectado')
    expect(row).not.toHaveTextContent('Última detecção há')
  })

  it('mostra estado vazio', async () => {
    window.history.replaceState(null, '', '/?estado=vazio')
    render(<App />)
    expect(await screen.findByText('Nenhum equipamento cadastrado')).toBeInTheDocument()
    expect(screen.getByText('Equipamentos cadastrados')).toBeInTheDocument()
  })

  it('remove dados e mostra erro explícito', async () => {
    window.history.replaceState(null, '', '/?estado=erro')
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Não foi possível carregar as informações.')
    expect(screen.queryByText('Cadeira de Rodas 12')).not.toBeInTheDocument()
  })

  it('navega entre Dashboard e Mapa / Planta', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('link', { name: 'Mapa / Planta' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Mapa / Planta' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }))
    expect(await screen.findByText('Equipamentos cadastrados')).toBeInTheDocument()
  })

  it('busca nas fixtures por patrimônio', async () => {
    render(<App />)
    await screen.findByText('Equipamentos cadastrados')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'PAT-3170' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    expect(screen.getByText('Maca 07')).toBeInTheDocument()
    expect(screen.queryByText('Cadeira de Rodas 12')).not.toBeInTheDocument()
  })
})
