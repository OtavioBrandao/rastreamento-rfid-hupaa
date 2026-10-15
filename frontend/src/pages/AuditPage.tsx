import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AdminPagination, AdminQueryState } from '../components/admin/AdminParts'
import { accessDenied, adminDate, adminErrorMessage, getAudit, getAudits, type Filtros } from '../services/admin'
import { useLiveQuery } from '../services/live'

const ACTIONS = ['criar', 'atualizar', 'inativar', 'reativar', 'excluir', 'vincular_epc', 'desvincular_epc', 'alterar_senha', 'correcao_manual', 'login_aceito', 'login_recusado', 'conta_bloqueada', 'logout', 'acesso_negado']
const EMPTY: Filtros = { entidade: '', entidade_id: '', acao: '', origem: '', usuario_id: '', correlation_id: '', desde: '', ate: '' }

// datetime-local não carrega fuso. A tela declara Maceió (UTC-03:00) e envia ISO UTC.
export function auditTimestamp(value: string): string {
  return value ? new Date(`${value}-03:00`).toISOString() : ''
}

export function AuditPage() {
  const [draft, setDraft] = useState<Filtros>({ ...EMPTY })
  const [filters, setFilters] = useState<Filtros>({ ...EMPTY })
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [validation, setValidation] = useState('')
  const query = useLiveQuery(`audits:${JSON.stringify(filters)}:${page}`, (signal) => getAudits(filters, page, signal))
  const data = accessDenied(query.error) ? null : query.data

  function apply(event: FormEvent) {
    event.preventDefault()
    setValidation('')
    try {
      const converted = { ...draft, desde: auditTimestamp(draft.desde), ate: auditTimestamp(draft.ate) }
      if (converted.desde && converted.ate && converted.desde >= converted.ate) {
        setValidation('O início deve ser anterior ao fim do período.'); return
      }
      setFilters(converted); setPage(1); setSelectedId(null)
    } catch { setValidation('Informe datas válidas para o período.') }
  }

  function field(key: string, value: string) { setDraft((current) => ({ ...current, [key]: value })) }
  function correlate(id: string) {
    setDraft({ ...EMPTY, correlation_id: id }); setFilters({ ...EMPTY, correlation_id: id }); setPage(1); setSelectedId(null)
  }

  return <>
    <div className="page-heading"><div><p className="eyebrow">RASTREABILIDADE</p><h1>Auditoria</h1><p className="lead">Consulte alterações de cadastro, correções manuais e eventos de acesso, do mais recente para o mais antigo. Os registros são imutáveis.</p></div></div>
    <form className="panel admin-editor" onSubmit={apply}><div className="admin-form-grid">
      <label>Entidade<input maxLength={64} placeholder="Ex.: equipamentos" value={draft.entidade} onChange={(e) => field('entidade', e.target.value)}/></label>
      <label>ID da entidade<input type="number" min={1} step={1} value={draft.entidade_id} onChange={(e) => field('entidade_id', e.target.value)}/></label>
      <label>Ação<select value={draft.acao} onChange={(e) => field('acao', e.target.value)}><option value="">Todas</option>{ACTIONS.map((action) => <option key={action} value={action}>{action.replaceAll('_', ' ')}</option>)}</select></label>
      <label>Origem<select value={draft.origem} onChange={(e) => field('origem', e.target.value)}><option value="">Todas</option><option value="usuario">Usuário</option><option value="sistema">Sistema</option><option value="anonimo">Anônimo</option></select></label>
      <label>ID do autor<input type="number" min={1} step={1} value={draft.usuario_id} onChange={(e) => field('usuario_id', e.target.value)}/></label>
      <label>Correlação<input maxLength={64} value={draft.correlation_id} onChange={(e) => field('correlation_id', e.target.value)}/></label>
      <label>Desde (Maceió, inclusivo)<input type="datetime-local" value={draft.desde} onChange={(e) => field('desde', e.target.value)}/></label>
      <label>Até (Maceió, exclusivo)<input type="datetime-local" value={draft.ate} onChange={(e) => field('ate', e.target.value)}/></label>
    </div>{validation && <p className="admin-error" role="alert">{validation}</p>}
      <div className="admin-form-actions"><button className="admin-primary" type="submit">Aplicar filtros</button><button type="button" onClick={() => { setDraft({ ...EMPTY }); setFilters({ ...EMPTY }); setPage(1); setSelectedId(null); setValidation('') }}>Limpar filtros</button></div>
    </form>
    <section className="panel inventory-panel" aria-labelledby="audits-title">
      <div className="panel-heading"><h2 id="audits-title">Trilha de auditoria</h2><span>Horários de Maceió</span></div>
      <AdminQueryState loading={query.loading} error={query.error ? adminErrorMessage(query.error) : null}/>
      {data && <>{data.items.length ? <div className="table-wrap"><table className="equipment-table admin-table"><thead><tr><th>Horário</th><th>Ação / entidade</th><th>Autor / origem</th><th>Motivo</th><th>Registro</th></tr></thead>
        <tbody>{data.items.map((audit) => <tr key={audit.id}>
          <td>{adminDate(audit.registrado_em)}</td><td data-label="Ação / entidade"><div><strong>{audit.acao.replaceAll('_', ' ')}</strong><small>{audit.entidade}{audit.entidade_id !== null ? ` #${audit.entidade_id}` : ''}</small></div></td>
          <td data-label="Autor / origem"><div>{audit.usuario_nome ?? (audit.origem === 'sistema' ? 'Sistema' : 'Anônimo')}<small>{audit.origem}{audit.usuario_id !== null ? ` · #${audit.usuario_id}` : ''}</small></div></td><td data-label="Motivo" className="admin-motive">{audit.motivo ?? '—'}</td>
          <td data-label="Registro"><button type="button" onClick={() => setSelectedId(audit.id)}>Ver registro #{audit.id}</button></td>
        </tr>)}</tbody></table></div> : <p className="empty-panel">Nenhum registro encontrado para estes filtros.</p>}
        <AdminPagination page={page} pages={data.pages} total={data.total} onPage={(next) => { setPage(next); setSelectedId(null) }}/></>}
    </section>
    {selectedId !== null && !accessDenied(query.error) && <AuditDetail id={selectedId} onClose={() => setSelectedId(null)} onCorrelate={correlate}/>}
  </>
}

function AuditDetail({ id, onClose, onCorrelate }: { id: number; onClose: () => void; onCorrelate: (id: string) => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = dialogRef.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog.showModal()
    return () => { dialog.close(); previous?.focus() }
  }, [id])
  const query = useLiveQuery(`audit:${id}`, (signal) => getAudit(id, signal))
  const audit = accessDenied(query.error) ? null : query.data
  return <dialog ref={dialogRef} className="panel admin-editor audit-dialog" aria-labelledby="audit-detail-title"
    onCancel={(event) => { event.preventDefault(); onClose() }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className="audit-dialog-content">
    <div className="panel-heading"><h2 id="audit-detail-title">Registro #{id}</h2><button type="button" onClick={onClose}>Fechar registro</button></div>
    <AdminQueryState loading={query.loading} error={query.error ? adminErrorMessage(query.error) : null}/>
    {audit && <><dl className="admin-audit-meta"><div><dt>Ação</dt><dd>{audit.acao.replaceAll('_', ' ')}</dd></div><div><dt>Entidade</dt><dd>{audit.entidade} {audit.entidade_id !== null ? `#${audit.entidade_id}` : ''}</dd></div>
      <div><dt>Autor</dt><dd>{audit.usuario_nome ?? audit.origem}{audit.usuario_id !== null ? ` (#${audit.usuario_id})` : ''}</dd></div><div><dt>Registrado em (Maceió)</dt><dd>{adminDate(audit.registrado_em)}</dd></div><div><dt>Motivo</dt><dd>{audit.motivo ?? 'Não informado'}</dd></div></dl>
      {audit.correlation_id && <p className="admin-correlation">Correlação: <code>{audit.correlation_id}</code> <button type="button" onClick={() => onCorrelate(audit.correlation_id!)}>Ver eventos relacionados</button></p>}
      <div className="admin-diff"><section><h3>Antes</h3><pre>{audit.dados_antes ? JSON.stringify(audit.dados_antes, null, 2) : 'Sem valores anteriores'}</pre></section><section><h3>Depois</h3><pre>{audit.dados_depois ? JSON.stringify(audit.dados_depois, null, 2) : 'Sem valores posteriores'}</pre></section></div>
    </>}
    </div>
  </dialog>
}
