import { useState, type FormEvent } from 'react'
import { AuthBrand } from '../components/auth/AuthBrand'
import { AuthError, login, type Session } from '../services/auth'

interface Props { notice?: string; onAuthenticated: (session: Session) => void }

export function LoginPage({ notice, onAuthenticated }: Props) {
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      onAuthenticated(await login(email, senha))
    } catch (failure) {
      setSenha('')
      setError(failure instanceof AuthError ? failure.message : 'Não foi possível entrar agora.')
      setSubmitting(false)
    }
  }

  return <main className="auth-screen" id="conteudo">
    <section className="auth-card" aria-labelledby="login-titulo">
      <AuthBrand/>
      <h1 id="login-titulo">Entrar</h1>
      <p className="auth-lead">Use o e-mail e a senha cadastrados pela administração.</p>
      {notice && <p className="auth-notice" role="status">{notice}</p>}
      <form className="auth-form" onSubmit={submit} noValidate>
        <label htmlFor="login-email">E-mail</label>
        <input id="login-email" type="email" autoComplete="username" required value={email}
          onChange={(event) => setEmail(event.target.value)}/>
        <label htmlFor="login-senha">Senha</label>
        <input id="login-senha" type="password" autoComplete="current-password" required value={senha}
          onChange={(event) => setSenha(event.target.value)}/>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" className="auth-primary" disabled={submitting}>{submitting ? 'Entrando…' : 'Entrar'}</button>
      </form>
    </section>
  </main>
}
