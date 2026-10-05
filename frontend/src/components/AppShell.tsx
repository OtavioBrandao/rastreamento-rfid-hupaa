import type { ReactNode } from 'react'
import { Icon } from './layout/Icon'
import { useLiveRefresh } from '../services/live'

interface Props { children: ReactNode; page: 'dashboard' | 'map' | 'readings' }

export function AppShell({ children, page }: Props) {
  const { refresh, pending } = useLiveRefresh()
  return <div className="app-shell">
    <a className="skip-link" href="#conteudo">Ir para o conteúdo</a>
    <aside className="app-sidebar"><div className="sidebar-brand"><svg className="brand-mark" viewBox="0 0 64 64" aria-hidden="true"><g fill="none" stroke="currentColor" strokeWidth="6"><path d="M20 6C3 18 3 46 20 58M44 6c17 12 17 40 0 52"/><path d="M25 19c-9 6-9 20 0 26m14-26c9 6 9 20 0 26"/></g><g fill="#e3262e"><rect x="28" y="21" width="8" height="22" rx="2"/><rect x="21" y="28" width="22" height="8" rx="2"/></g></svg><div><strong>Rastreamento RFID</strong><small>HUPAA · UFAL</small></div></div><p className="sidebar-label">NAVEGAÇÃO</p><nav className="main-nav" aria-label="Navegação principal"><a href="#/" aria-current={page === 'dashboard' ? 'page' : undefined}><Icon name="dashboard"/> Dashboard</a><a href="#/mapa" aria-current={page === 'map' ? 'page' : undefined}><Icon name="map"/> Mapa / Planta</a><a href="#/leituras" aria-current={page === 'readings' ? 'page' : undefined}><Icon name="antenna"/> Leituras</a></nav></aside>
    <div className="app-body"><header className="site-header"><strong>Engenharia clínica</strong><button className="global-refresh" type="button" onClick={refresh} disabled={pending > 0} aria-label="Atualizar todos os dados" title="Atualizar todos os dados" aria-busy={pending > 0}><Icon name="refresh"/><span>{pending > 0 ? 'Atualizando...' : 'Atualizar tudo'}</span></button></header><main id="conteudo" className="main-content">{children}</main></div>
  </div>
}
