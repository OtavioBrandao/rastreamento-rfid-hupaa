import type { ReactNode } from 'react'

interface Props { children: ReactNode; page: 'dashboard' | 'map' }

export function AppShell({ children, page }: Props) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#conteudo">Ir para o conteúdo</a>
      <header className="site-header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true"><span /></span>
            <span>Rastreamento RFID</span>
          </div>
          <span className="header-context">Equipamentos hospitalares</span>
        </div>
      </header>
      <div className="nav-wrap">
        <nav className="main-nav" aria-label="Navegação principal">
          <a href="#/" aria-current={page === 'dashboard' ? 'page' : undefined}>Dashboard</a>
          <a href="#/mapa" aria-current={page === 'map' ? 'page' : undefined}>Mapa / Planta</a>
        </nav>
      </div>
      <main id="conteudo" className="main-content">{children}</main>
      <footer className="site-footer">Rastreamento aproximado por zona · Dados demonstrativos</footer>
    </div>
  )
}
