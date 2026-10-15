// Sessão do usuário (ISS-027). O token vive SÓ no cookie HttpOnly `rfid_sessao`,
// definido pela API: nada aqui o lê, guarda em estado, localStorage,
// sessionStorage ou header. Toda chamada vai com credentials 'same-origin'.
// As permissões vêm prontas de /auth/me; a matriz não é copiada no front.

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export const SESSION_ENDED_EVENT = 'rfid:sessao-encerrada'
export const MIN_PASSWORD_LENGTH = 8
export const INVALID_LOGIN_MESSAGE = 'E-mail ou senha inválidos.'

export interface SessionUser {
  id: number
  nome: string
  email: string
  perfil: string
  ativo: boolean
  deve_trocar_senha: boolean
}

export interface Session {
  usuario: SessionUser
  sessao_expira_em: string
  permissoes: string[]
}

export class AuthError extends Error {}

/** Servidor inacessível ou com erro inesperado (não é "sem sessão"). */
export class ServerUnavailableError extends Error {}

function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = init.body ? { 'Content-Type': 'application/json' } : undefined
  return fetch(`${base}${path}`, { ...init, headers, credentials: 'same-origin' })
}

/** Avisa o app de que a sessão acabou (expirou, conta desativada, logout em outra aba). */
export function notifySessionEnded(): void {
  window.dispatchEvent(new Event(SESSION_ENDED_EVENT))
}

export function onSessionEnded(handler: () => void): () => void {
  window.addEventListener(SESSION_ENDED_EVENT, handler)
  return () => window.removeEventListener(SESSION_ENDED_EVENT, handler)
}

/** Sessão atual; `null` quando não há (401). Outros erros sobem como ServerUnavailableError. */
export async function getSession(): Promise<Session | null> {
  let response: Response
  try {
    response = await request('/auth/me')
  } catch {
    throw new ServerUnavailableError('Servidor indisponível.')
  }
  if (response.status === 401) return null
  if (!response.ok) throw new ServerUnavailableError(`API respondeu ${response.status}`)
  return response.json() as Promise<Session>
}

export async function login(email: string, senha: string): Promise<Session> {
  let response: Response
  try {
    response = await request('/auth/login', { method: 'POST', body: JSON.stringify({ email, senha }) })
  } catch {
    throw new AuthError('Não foi possível contactar o servidor. Tente novamente em instantes.')
  }
  // 401 e 422 viram a MESMA mensagem: não revelar se o e-mail existe nem o formato aceito.
  if (response.status === 401 || response.status === 422) throw new AuthError(INVALID_LOGIN_MESSAGE)
  if (!response.ok) throw new AuthError('Não foi possível entrar agora. Tente novamente em instantes.')
  return response.json() as Promise<Session>
}

export async function logout(): Promise<void> {
  try {
    await request('/auth/logout', { method: 'POST' })
  } catch {
    // Logout é idempotente no servidor; sem rede, a tela volta ao login mesmo assim.
  }
}

export async function changePassword(senhaAtual: string, novaSenha: string): Promise<void> {
  let response: Response
  try {
    response = await request('/auth/trocar-senha', {
      method: 'POST', body: JSON.stringify({ senha_atual: senhaAtual, nova_senha: novaSenha }),
    })
  } catch {
    throw new AuthError('Não foi possível contactar o servidor. Tente novamente em instantes.')
  }
  if (response.ok) return
  if (response.status === 401) {
    notifySessionEnded()
    throw new AuthError('Sua sessão expirou. Entre novamente.')
  }
  if (response.status === 400) throw new AuthError('Senha atual incorreta.')
  if (response.status === 422) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new AuthError(body?.detail === 'nova_senha_igual_a_atual'
      ? 'A nova senha precisa ser diferente da atual.'
      : `A nova senha precisa ter pelo menos ${MIN_PASSWORD_LENGTH} caracteres.`)
  }
  throw new AuthError('Não foi possível trocar a senha agora. Tente novamente em instantes.')
}

export function pode(session: Session | null, permissao: string): boolean {
  return session?.permissoes.includes(permissao) ?? false
}

export function profileLabel(perfil: string): string {
  if (perfil === 'administrador') return 'Administrador'
  if (perfil === 'operacional') return 'Operacional'
  return perfil
}
