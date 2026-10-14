import { notifySessionEnded, type SessionUser } from './auth'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export interface Pagina<T> { items: T[]; page: number; size: number; total: number; pages: number }
export interface Usuario extends SessionUser {
  bloqueado_ate: string | null
  ultimo_login_em: string | null
  created_at: string
  updated_at: string
}
export interface Auditoria {
  id: number
  registrado_em: string
  acao: string
  origem: string
  entidade: string
  entidade_id: number | null
  usuario_id: number | null
  usuario_nome: string | null
  motivo: string | null
  correlation_id: string | null
  dados_antes: Record<string, unknown> | null
  dados_depois: Record<string, unknown> | null
}
export type Filtros = Record<string, string>

export class AdminError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

// O corpo de erro nunca é exibido: um 422 pode conter dados enviados pelo usuário.
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init, credentials: 'same-origin',
    headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (response.status === 401) notifySessionEnded()
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: 'Sua sessão expirou. Entre novamente.',
      403: 'Você não tem permissão para esta operação.',
      404: 'O registro não foi encontrado. Atualize a consulta.',
      409: 'A operação foi recusada. Confira se o e-mail já existe ou se a alteração deixaria o sistema sem administrador ativo.',
      422: 'Confira os campos. A senha deve ter de 8 a 128 caracteres e não pode conter apenas espaços.',
    }
    throw new AdminError(messages[response.status] ?? 'Não foi possível concluir a operação. Tente novamente.', response.status)
  }
  return response.json() as Promise<T>
}

function query(filters: Filtros, page: number, size: number): string {
  const params = new URLSearchParams({ page: String(page), size: String(size) })
  for (const [key, value] of Object.entries(filters)) if (value !== '') params.set(key, value)
  return params.toString()
}

export const getUsers = (filters: Filtros, page: number, signal: AbortSignal) =>
  request<Pagina<Usuario>>(`/usuarios?${query(filters, page, 20)}`, { signal })
export const createUser = (body: { nome: string; email: string; perfil: string; senha_temporaria: string }) =>
  request<Usuario>('/usuarios', { method: 'POST', body: JSON.stringify(body) })
export const editUser = (id: number, body: { nome?: string; perfil?: string }) =>
  request<Usuario>(`/usuarios/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const changeUserState = (id: number, active: boolean) =>
  request<Usuario>(`/usuarios/${id}/${active ? 'reativar' : 'desativar'}`, { method: 'POST' })
export const resetUserPassword = (id: number, senha_temporaria: string) =>
  request<Usuario>(`/usuarios/${id}/redefinir-senha`, { method: 'POST', body: JSON.stringify({ senha_temporaria }) })
export const getAudits = (filters: Filtros, page: number, signal: AbortSignal) =>
  request<Pagina<Auditoria>>(`/auditorias?${query(filters, page, 50)}`, { signal })
export const getAudit = (id: number, signal: AbortSignal) =>
  request<Auditoria>(`/auditorias/${id}`, { signal })

export function adminDate(value: string | null): string {
  return value ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium', timeZone: 'America/Maceio' }).format(new Date(value)) : '—'
}

export const adminErrorMessage = (error: unknown) => error instanceof AdminError
  ? error.message : 'Não foi possível contactar o servidor. Tente novamente.'
export const accessDenied = (error: Error | null) => error instanceof AdminError && [401, 403].includes(error.status)
