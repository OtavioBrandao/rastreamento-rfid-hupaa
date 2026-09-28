import type { ReactNode } from 'react'
import { Icon } from './layout/Icon'

interface Props { children: ReactNode; page: 'dashboard' | 'map' }

export function AppShell({ children, page }: Props) {
  return <div className="app-shell">
    <a className="skip-link" href="#conteudo">Ir para o conteúdo</a>
    <aside className="app-sidebar"><div className="sidebar-brand"><span className="brand-mark"><span/></span><div><strong>Rastreamento RFID</strong><small>HUPAA · UFAL</small></div></div><p className="sidebar-label">NAVEGAÇÃO</p><nav className="main-nav" aria-label="Navegação principal"><a href="#/" aria-current={page === 'dashboard' ? 'page' : undefined}><Icon name="dashboard"/> Dashboard</a><a href="#/mapa" aria-current={page === 'map' ? 'page' : undefined}><Icon name="map"/> Mapa / Planta</a></nav></aside>
    <div className="app-body"><header className="site-header"><strong>Engenharia clínica</strong></header><main id="conteudo" className="main-content">{children}</main></div>
  </div>
}
