import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../../services/api'
import { getClock, setClock, type Relogio } from '../../services/simulacao'

const POLL_MS = 2000

/** Relógio da simulação no navegador: o servidor manda o instante e o fator; entre as
 *  consultas o tempo anda localmente no mesmo ritmo. Simulador e dashboard leem o mesmo. */
export function useSimClock() {
  const [relogio, setRelogio] = useState<Relogio | null>(null)
  const ancora = useRef<{ simMs: number; realMs: number; fator: number } | null>(null)
  const aplicar = useCallback((dados: Relogio) => {
    ancora.current = { simMs: Date.parse(dados.agora), realMs: Date.now(), fator: dados.fator }
    setRelogio(dados)
  }, [])
  useEffect(() => {
    let vivo = true
    const buscar = () => { getClock().then((dados) => { if (vivo) aplicar(dados) }).catch(() => undefined) }
    buscar()
    const timer = window.setInterval(buscar, POLL_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [aplicar])
  const agora = useCallback(() => {
    const a = ancora.current
    return a ? a.simMs + (Date.now() - a.realMs) * a.fator : Date.now()
  }, [])
  return { relogio, agora, aplicar }
}

const hora = (ms: number) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

function adiantamento(segundos: number) {
  if (segundos < 60) return `${Math.round(segundos)} s`
  if (segundos < 3600) return `${Math.round(segundos / 60)} min`
  return `${Math.floor(segundos / 3600)} h ${Math.round((segundos % 3600) / 60)} min`
}

const AVANCOS = [{ s: 300, rotulo: '+5 min' }, { s: 1800, rotulo: '+30 min' }, { s: 3600, rotulo: '+1 h' }]

/** Selo do tempo simulado e, para quem pode alterar, acelerar e avançar. Discreto de propósito. */
export function TimeControls({ clock, canEdit }: { clock: ReturnType<typeof useSimClock>; canEdit: boolean }) {
  const { relogio, agora, aplicar } = clock
  const [, tick] = useState(0)
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => { const timer = window.setInterval(() => tick((n) => n + 1), 500); return () => window.clearInterval(timer) }, [])
  async function mudar(mudanca: { fator?: number; avancar_s?: number }) {
    setOcupado(true)
    try { aplicar(await setClock(mudanca)); setErro('') } catch (falha) { setErro(errorMessage(falha)) } finally { setOcupado(false) }
  }
  if (!relogio) return null
  const acelerado = relogio.acelerado
  return <div className={`sim-clock${acelerado ? ' sim-clock-acelerado' : ''}`} role="group" aria-label="Tempo da simulação">
    <span className="sim-clock-hora" aria-live="off" title="Relógio da simulação (o do computador não muda)">⏱ {hora(agora())}</span>
    {acelerado && <span className="sim-clock-selo" role="status">
      {relogio.fator !== 1 ? `acelerado ×${relogio.fator}` : 'tempo simulado'}
      {relogio.adiantado_s > 1 ? ` · +${adiantamento(relogio.adiantado_s)}` : ''}
    </span>}
    {canEdit && <>
      <label className="sim-clock-fator">Velocidade
        <select value={relogio.fator} disabled={ocupado} onChange={(event) => { void mudar({ fator: Number(event.target.value) }) }}>
          {relogio.fatores.map((fator) => <option key={fator} value={fator}>×{fator}</option>)}
        </select>
      </label>
      {AVANCOS.map((avanco) => <button key={avanco.s} type="button" className="sim-clock-avanco" disabled={ocupado}
        title={`Avança o tempo simulado em ${avanco.rotulo.slice(1)} (não volta atrás)`} onClick={() => { void mudar({ avancar_s: avanco.s }) }}>{avanco.rotulo}</button>)}
    </>}
    {erro && <span className="sim-clock-erro" role="alert">{erro}</span>}
  </div>
}
