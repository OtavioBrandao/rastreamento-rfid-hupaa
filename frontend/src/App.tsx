import { useCallback, useEffect, useState } from 'react'
import { AppShell } from './components/AppShell'
import { EquipmentDrawer } from './components/equipamento/EquipmentDrawer'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { MapPage } from './pages/MapPage'
import { ReadingsPage } from './pages/ReadingsPage'
import { getSession, logout, onSessionEnded, pode, type Session } from './services/auth'
import type { EquipmentItem } from './types/dashboard'
import { LiveProvider } from './services/live'

export type Page = 'dashboard' | 'map' | 'readings'

const SESSION_EXPIRED = 'Sua sessão expirou. Entre novamente.'
const SERVER_UNAVAILABLE = 'Não foi possível contactar o servidor. Tente entrar novamente em instantes.'

type AuthState =
  | { phase: 'loading' }
  | { phase: 'anonymous'; notice?: string }
  | { phase: 'authenticated'; session: Session }

function currentPage(): Page {
  if (window.location.hash === '#/mapa') return 'map'
  if (window.location.hash === '#/leituras') return 'readings'
  return 'dashboard'
}

export default function App() {
  const [auth, setAuth] = useState<AuthState>({ phase: 'loading' })

  const loadSession = useCallback(() => {
    getSession()
      .then((session) => setAuth(session ? { phase: 'authenticated', session } : { phase: 'anonymous' }))
      // Servidor fora do ar: nunca preso em "carregando".
      .catch(() => setAuth({ phase: 'anonymous', notice: SERVER_UNAVAILABLE }))
  }, [])

  useEffect(loadSession, [loadSession])
  useEffect(() => onSessionEnded(() => setAuth((current) => current.phase === 'authenticated'
    ? { phase: 'anonymous', notice: SESSION_EXPIRED } : current)), [])

  async function signOut() {
    await logout()
    setAuth({ phase: 'anonymous' })
  }

  if (auth.phase === 'loading') {
    return <main className="auth-screen" id="conteudo"><p className="auth-loading" role="status">Carregando…</p></main>
  }
  if (auth.phase === 'anonymous') {
    return <LoginPage notice={auth.notice} onAuthenticated={(session) => setAuth({ phase: 'authenticated', session })}/>
  }
  if (auth.session.usuario.deve_trocar_senha) {
    return <ChangePasswordPage session={auth.session} onChanged={loadSession} onLogout={signOut}/>
  }
  // A atualização automática (ISS-033) só existe com sessão: o provedor monta junto com o painel.
  return <LiveProvider><Panel session={auth.session} onLogout={signOut}/></LiveProvider>
}

function Panel({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [page, setPage] = useState(currentPage)
  const [selected, setSelected] = useState<EquipmentItem | null>(null)
  // ISS-025: corrigir é só do administrador; a matriz vem pronta de /auth/me.
  const canCorrect = pode(session, 'equipamentos:corrigir')
  useEffect(() => {
    const onHashChange = () => setPage(currentPage())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  return <AppShell page={page} user={session.usuario} onLogout={onLogout}>
    {page === 'map' ? <MapPage onSelect={setSelected} /> : page === 'readings' ? <ReadingsPage /> : <DashboardPage onSelect={setSelected} />}
    <EquipmentDrawer item={selected} onClose={() => setSelected(null)} canCorrect={canCorrect}/>
  </AppShell>
}
