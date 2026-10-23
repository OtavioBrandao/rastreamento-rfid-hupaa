// Escrita na API com cookie de sessão (mesma origem). Mensagens de erro vêm do
// `detail` do backend somente quando ele é texto ou `{ mensagem }`; listas de
// validação do Pydantic viram texto curto, sem o valor enviado pelo usuário.
import { notifySessionEnded } from './auth'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message: string, public status: number, public codigo?: string) { super(message) }
}

const FALLBACK: Record<number, string> = {
  401: 'Sua sessão expirou. Entre novamente.',
  403: 'Você não tem permissão para esta operação.',
  404: 'O registro não foi encontrado. Atualize a página.',
  409: 'A operação foi recusada por conflito com o estado atual.',
  422: 'Confira os campos informados.',
}

function detailMessage(detail: unknown, status: number): { message: string; codigo?: string } {
  if (typeof detail === 'string') return { message: detail }
  if (detail && typeof detail === 'object' && 'mensagem' in detail) {
    const item = detail as { mensagem?: unknown; codigo?: unknown }
    return { message: String(item.mensagem ?? FALLBACK[status] ?? ''), codigo: typeof item.codigo === 'string' ? item.codigo : undefined }
  }
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => (item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg).replace(/^Value error, /, '') : '')).filter(Boolean)
    if (messages.length) return { message: messages.join('; ') }
  }
  return { message: FALLBACK[status] ?? 'Não foi possível concluir a operação. Tente novamente.' }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...init, credentials: 'same-origin', cache: 'no-store',
      headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch {
    throw new ApiError('Não foi possível contactar o servidor.', 0)
  }
  if (response.status === 401) notifySessionEnded()
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    const { message, codigo } = detailMessage(body?.detail, response.status)
    throw new ApiError(message, response.status, codigo)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Falha inesperada.'

export const sendJson = <T>(path: string, method: string, body?: unknown) =>
  apiRequest<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) })
