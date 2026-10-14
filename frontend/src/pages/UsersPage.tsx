import { useState, type FormEvent } from 'react'
import { AdminPagination, AdminQueryState } from '../components/admin/AdminParts'
import { accessDenied, adminDate, adminErrorMessage, changeUserState, createUser, editUser, getUsers, resetUserPassword, type Usuario } from '../services/admin'
import { profileLabel } from '../services/auth'
import { useLiveQuery, useLiveRefresh } from '../services/live'

type Action = { kind: 'create' } | { kind: 'edit' | 'reset' | 'state'; user: Usuario }

export function UsersPage({ currentUserId, onSessionChanged }: { currentUserId: number; onSessionChanged: () => void }) {
  const [active, setActive] = useState('')
  const [profile, setProfile] = useState('')
  const [page, setPage] = useState(1)
  const [action, setAction] = useState<Action | null>(null)
  const [notice, setNotice] = useState('')
  const { refresh } = useLiveRefresh()
  const query = useLiveQuery(`users:${active}:${profile}:${page}`, (signal) => getUsers({ ativo: active, perfil: profile }, page, signal))
  const data = accessDenied(query.error) ? null : query.data

  return <>
    <div className="page-heading"><div><p className="eyebrow">ADMINISTRAÇÃO</p><h1>Usuários</h1><p className="lead">Gerencie contas e perfis de acesso. Contas novas usam uma senha temporária com troca obrigatória no primeiro acesso.</p></div><button type="button" className="admin-primary" onClick={() => { setNotice(''); setAction({ kind: 'create' }) }}>Novo usuário</button></div>
    {notice && <p className="admin-success" role="status">{notice}</p>}
    <form className="panel asset-filters" onSubmit={(event) => event.preventDefault()}>
      <label>Estado da conta<select value={active} onChange={(event) => { setActive(event.target.value); setPage(1) }}><option value="">Todas</option><option value="true">Ativas</option><option value="false">Inativas</option></select></label>
      <label>Perfil de acesso<select value={profile} onChange={(event) => { setProfile(event.target.value); setPage(1) }}><option value="">Todos</option><option value="operacional">Operacional</option><option value="administrador">Administrador</option></select></label>
    </form>
    {action && <UserAction key={`${action.kind}:${'user' in action ? action.user.id : 'new'}`} action={action} currentUserId={currentUserId}
      onCancel={() => setAction(null)} onDone={(message, user) => {
        setAction(null); setNotice(message); refresh()
        if (user.id === currentUserId) onSessionChanged()
      }}/>}
    <section className="panel inventory-panel" aria-labelledby="users-title">
      <div className="panel-heading"><h2 id="users-title">Contas cadastradas</h2></div>
      <AdminQueryState loading={query.loading} error={query.error ? adminErrorMessage(query.error) : null}/>
      {data && <>{data.items.length ? <div className="table-wrap"><table className="equipment-table admin-table"><thead><tr><th>Nome / e-mail</th><th>Perfil</th><th>Estado</th><th>Último login (Maceió)</th><th>Ações</th></tr></thead>
        <tbody>{data.items.map((user) => <tr key={user.id}>
          <td><strong>{user.nome}{user.id === currentUserId ? ' (você)' : ''}</strong><small>{user.email}</small></td>
          <td data-label="Perfil">{profileLabel(user.perfil)}</td><td data-label="Estado"><div>{user.ativo ? 'Ativa' : 'Inativa'}{user.deve_trocar_senha && <small>Troca de senha pendente</small>}{user.bloqueado_ate && new Date(user.bloqueado_ate) > new Date() && <small>Bloqueada até {adminDate(user.bloqueado_ate)}</small>}</div></td>
          <td data-label="Último login">{adminDate(user.ultimo_login_em)}</td>
          <td data-label="Ações"><div className="admin-row-actions"><button type="button" onClick={() => { setNotice(''); setAction({ kind: 'edit', user }) }}>Editar {user.nome}</button>
            <button type="button" disabled={user.id === currentUserId} onClick={() => { setNotice(''); setAction({ kind: 'state', user }) }}>{user.ativo ? 'Desativar' : 'Reativar'} {user.nome}</button>
            <button type="button" disabled={user.id === currentUserId} onClick={() => { setNotice(''); setAction({ kind: 'reset', user }) }}>Redefinir senha de {user.nome}</button></div></td>
        </tr>)}</tbody></table></div> : <p className="empty-panel">Nenhum usuário encontrado para estes filtros.</p>}
        <AdminPagination page={page} pages={data.pages} total={data.total} onPage={setPage}/></>}
    </section>
  </>
}

function UserAction({ action, currentUserId, onCancel, onDone }: { action: Action; currentUserId: number; onCancel: () => void; onDone: (message: string, user: Usuario) => void }) {
  const user = 'user' in action ? action.user : null
  const [name, setName] = useState(user?.nome ?? '')
  const [email, setEmail] = useState('')
  const [profile, setProfile] = useState(user?.perfil ?? 'operacional')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const title = action.kind === 'create' ? 'Novo usuário' : action.kind === 'edit' ? 'Editar usuário' : action.kind === 'reset' ? 'Redefinir senha' : user?.ativo ? 'Desativar usuário' : 'Reativar usuário'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setError('')
    const needsPassword = action.kind === 'create' || action.kind === 'reset'
    if (needsPassword && !password.trim()) { setError('A senha não pode conter apenas espaços.'); return }
    if ((action.kind === 'create' || action.kind === 'edit') && !name.trim()) { setError('Preencha o nome.'); return }
    setBusy(true)
    try {
      let result: Usuario
      if (action.kind === 'create') result = await createUser({ nome: name.trim(), email: email.trim(), perfil: profile, senha_temporaria: password })
      else if (action.kind === 'edit') {
        const changes = { ...(name.trim() !== user!.nome ? { nome: name.trim() } : {}), ...(profile !== user!.perfil ? { perfil: profile } : {}) }
        if (!Object.keys(changes).length) { setError('Nenhuma alteração foi informada.'); return }
        result = await editUser(user!.id, changes)
      } else if (action.kind === 'reset') result = await resetUserPassword(user!.id, password)
      else result = await changeUserState(user!.id, !user!.ativo)
      setPassword('')
      onDone(action.kind === 'reset' ? 'Senha redefinida. As sessões anteriores foram encerradas; a conta deverá trocar a senha ao entrar.' : 'Usuário atualizado com sucesso.', result)
    } catch (failure) { setError(adminErrorMessage(failure)); if (needsPassword) setPassword('') }
    finally { setBusy(false) }
  }

  return <section className="panel admin-editor" aria-labelledby="user-action-title">
    <h2 id="user-action-title">{title}</h2>{user && <p>{user.nome} · {user.email}</p>}
    <form onSubmit={submit}><fieldset disabled={busy}>
      {(action.kind === 'create' || action.kind === 'edit') && <div className="admin-form-grid">
        <label>Nome<input required maxLength={255} value={name} onChange={(event) => setName(event.target.value)}/></label>
        {action.kind === 'create' && <label>E-mail<input type="email" required maxLength={320} autoComplete="off" value={email} onChange={(event) => setEmail(event.target.value)}/></label>}
        <label>Perfil<select value={profile} onChange={(event) => setProfile(event.target.value)}>{!['operacional', 'administrador'].includes(profile) && <option value={profile}>{profileLabel(profile)}</option>}<option value="operacional">Operacional</option><option value="administrador">Administrador</option></select></label>
      </div>}
      {action.kind === 'edit' && user?.id === currentUserId && profile !== user.perfil && <p className="admin-warning">Ao mudar seu próprio perfil, seus acessos serão recarregados após salvar. A API impede remover o último administrador ativo.</p>}
      {(action.kind === 'create' || action.kind === 'reset') && <div><label>Senha temporária<input type="password" required minLength={8} maxLength={128} autoComplete="new-password" aria-describedby="temporary-password-help" value={password} onChange={(event) => setPassword(event.target.value)}/></label><small id="temporary-password-help">De 8 a 128 caracteres. A troca será obrigatória no próximo acesso.</small></div>}
      {action.kind === 'reset' && <p>Confirmar encerra todas as sessões desta conta.</p>}
      {action.kind === 'state' && <p>{user?.ativo ? 'Confirmar desativa esta conta e encerra suas sessões.' : 'Confirmar reativa esta conta e remove o bloqueio de login. Sessões antigas continuam encerradas.'}</p>}
      {error && <p className="admin-error" role="alert">{error}</p>}
      <div className="admin-form-actions"><button className="admin-primary" type="submit">{busy ? 'Salvando…' : action.kind === 'create' ? 'Criar usuário' : action.kind === 'edit' ? 'Salvar alterações' : 'Confirmar'}</button><button type="button" onClick={onCancel}>Cancelar</button></div>
    </fieldset></form>
  </section>
}
