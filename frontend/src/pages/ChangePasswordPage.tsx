import { useState, type FormEvent } from 'react'
import { AuthBrand } from '../components/auth/AuthBrand'
import { AuthError, changePassword, MIN_PASSWORD_LENGTH, type Session } from '../services/auth'

interface Props { session: Session; onChanged: () => void; onLogout: () => void; onCancel?: () => void }

export function ChangePasswordPage({ session, onChanged, onLogout, onCancel }: Props) {
  const mandatory = session.usuario.deve_trocar_senha
  const [atual, setAtual] = useState('')
  const [nova, setNova] = useState('')
  const [confirmacao, setConfirmacao] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    // Conferências locais ANTES de chamar a API (mesma política do servidor).
    if (nova.length < MIN_PASSWORD_LENGTH) {
      setError(`A nova senha precisa ter pelo menos ${MIN_PASSWORD_LENGTH} caracteres.`)
      return
    }
    if (nova !== confirmacao) {
      setError('A confirmação não confere com a nova senha.')
      return
    }
    setSubmitting(true)
    try {
      await changePassword(atual, nova)
      onChanged()
    } catch (failure) {
      setAtual('')
      setError(failure instanceof AuthError ? failure.message : 'Não foi possível trocar a senha agora.')
      setSubmitting(false)
    }
  }

  return <main className="auth-screen" id="conteudo">
    <section className="auth-card" aria-labelledby="troca-titulo">
      <AuthBrand/>
      <h1 id="troca-titulo">{mandatory ? 'Troca de senha obrigatória' : 'Trocar minha senha'}</h1>
      <p className="auth-lead">{mandatory ? `Olá, ${session.usuario.nome}. Sua senha é temporária: defina uma senha própria para continuar.` : 'Informe a senha atual e escolha uma nova. As outras sessões da sua conta serão encerradas.'}</p>
      <form className="auth-form" onSubmit={submit} noValidate>
        <input type="email" autoComplete="username" value={session.usuario.email} readOnly hidden/>
        <label htmlFor="troca-atual">{mandatory ? 'Senha temporária' : 'Senha atual'}</label>
        <input id="troca-atual" type="password" autoComplete="current-password" required value={atual}
          onChange={(event) => setAtual(event.target.value)}/>
        <label htmlFor="troca-nova">Nova senha</label>
        <input id="troca-nova" type="password" autoComplete="new-password" required minLength={MIN_PASSWORD_LENGTH} maxLength={128}
          aria-describedby="troca-regra" value={nova} onChange={(event) => setNova(event.target.value)}/>
        <p className="auth-hint" id="troca-regra">Mínimo de {MIN_PASSWORD_LENGTH} caracteres, diferente da atual.</p>
        <label htmlFor="troca-confirmacao">Confirmar nova senha</label>
        <input id="troca-confirmacao" type="password" autoComplete="new-password" required value={confirmacao}
          onChange={(event) => setConfirmacao(event.target.value)}/>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" className="auth-primary" disabled={submitting}>{submitting ? 'Salvando…' : 'Trocar senha'}</button>
        {!mandatory && onCancel && <button type="button" className="auth-secondary" disabled={submitting} onClick={onCancel}>Cancelar</button>}
        <button type="button" className="auth-secondary" onClick={onLogout}>Sair</button>
      </form>
    </section>
  </main>
}
