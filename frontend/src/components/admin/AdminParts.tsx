import type { ReactNode } from 'react'

export function AdminPagination({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (page: number) => void }) {
  return <nav className="admin-pagination" aria-label="Páginas da consulta">
    <span>{total} registro(s) · Página {page} de {Math.max(pages, 1)}</span>
    <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>Anterior</button>
    <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>Próxima</button>
  </nav>
}

export function AdminQueryState({ loading, error, children }: { loading: boolean; error: string | null; children?: ReactNode }) {
  return <>{loading && <p role="status">Carregando consulta…</p>}
    {error && <p className="admin-error" role="alert">{error}</p>}{children}</>
}
