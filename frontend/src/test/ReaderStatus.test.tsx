import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReaderStatusPage } from '../pages/ReaderStatusPage'
import { AppShell } from '../components/AppShell'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

const snapshot = {
  consultado_em: '2026-10-15T12:00:00Z', degradado_apos_segundos: 30, offline_apos_segundos: 90,
  leitores: [
    { id: 1, reader_id: 'reader-01', modelo: 'Simulador', ativo: true, status: 'online', motivo: 'contato_recente', ultimo_contato_em: '2026-10-15T12:00:00Z', ultimo_heartbeat_em: '2026-10-15T12:00:00Z', origem_ultimo_contato: 'heartbeat' },
    { id: 2, reader_id: 'reader-02', modelo: 'Simulador', ativo: true, status: 'offline', motivo: 'timeout_sem_mensagens', ultimo_contato_em: '2026-10-15T11:55:00Z', ultimo_heartbeat_em: null, origem_ultimo_contato: 'leitura' },
    { id: 3, reader_id: 'reader-03', modelo: 'Simulador', ativo: true, status: 'nunca_conectado', motivo: 'sem_contato_observado', ultimo_contato_em: null, ultimo_heartbeat_em: null, origem_ultimo_contato: null },
  ],
  portais: [{ id: 1, nome: 'Portal A/B', ativo: true, status: 'degradado', motivo: 'falha_parcial_ou_degradacao', leitores_ids: [1, 2], ultimo_contato_em: '2026-10-15T12:00:00Z', lados_configurados: ['a', 'b'] }],
}

describe('Status dos leitores', () => {
  it('distingue nunca conectado, offline e falha parcial do portal', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot }))
    render(<ReaderStatusPage/>)
    await screen.findByText('Portal A/B')
    expect(screen.getByText('Prazo sem mensagens excedido')).toBeInTheDocument()
    expect(screen.getByText('Nenhuma mensagem válida observada')).toBeInTheDocument()
    expect(screen.getByText('Parte dos leitores indisponível ou degradada')).toBeInTheDocument()
    expect(screen.getByText('Heartbeat')).toBeInTheDocument()
    expect(screen.getByText(/Degradação após 30 s/)).toBeInTheDocument()
  })

  it('exibe falha de consulta sem inventar estado online', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(<ReaderStatusPage/>)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar'))
    expect(screen.queryByText('Leitores cadastrados')).not.toBeInTheDocument()
  })

  it('só oferece a navegação a quem pode consultar hardware', () => {
    const user = { id: 1, nome: 'Ana', email: 'ana@hupaa.example', perfil: 'operacional', ativo: true, deve_trocar_senha: false }
    const { rerender } = render(<AppShell page="reader-status" user={user} onLogout={() => {}}>Conteúdo</AppShell>)
    expect(screen.queryByRole('link', { name: 'Status dos leitores' })).not.toBeInTheDocument()
    rerender(<AppShell page="reader-status" user={user} onLogout={() => {}} canReadHardware>Conteúdo</AppShell>)
    expect(screen.getByRole('link', { name: 'Status dos leitores' })).toHaveAttribute('aria-current', 'page')
  })
})
