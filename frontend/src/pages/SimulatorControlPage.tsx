import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { EquipIcon, simboloDoTipo } from '../components/simulador/EquipIcon'
import { TimeControls, useSimClock } from '../components/simulador/RelogioSimulacao'
import { at, pointFromEvent, SimPlan } from '../components/simulador/SimPlan'
import { errorMessage } from '../services/api'
import { epcProblem, getRegistrations, type EquipamentoCadastro } from '../services/cadastro'
import {
  addItem, clearItems, emTrajeto, getSession, posicaoNoTempo, removeItem, runPath, sessionAction, updateItem,
  type ItemVirtual, type MotorEstado, type Ponto, type PontoTrajeto, type Sessao,
} from '../services/simulacao'

const POLL_MS = 500
/** Enquanto o botão segue pressionado e o mouse parado, o tempo parado entra no trajeto. */
const PAUSA_MS = 100
const PASSO_MIN = 0.2
const MAX_PONTOS = 3900
const ESTADO: Record<string, string> = { em_execucao: 'Em execução', pausada: 'Pausada', encerrada: 'Encerrada' }

/** Gesto em andamento: só planejamento. Nada é enviado até soltar o botão esquerdo. */
interface Desenho { itemId: string; pointerId: number; t0: number; pontos: PontoTrajeto[]; ultimo: Ponto; ultimoMovimento: number }

const segundos = (desenho: Desenho) => Math.round(performance.now() - desenho.t0) / 1000

/** Acrescenta o tempo parado: estende o último ponto parado em vez de multiplicar pontos. */
function registrarParada(desenho: Desenho) {
  const t = segundos(desenho)
  const [penultimo, ultimo] = desenho.pontos.slice(-2)
  if (penultimo && ultimo && penultimo.x === ultimo.x && penultimo.y === ultimo.y) ultimo.t = t
  else desenho.pontos.push({ x: desenho.ultimo.x, y: desenho.ultimo.y, t })
}

/** Velocidade de caminhada no trajeto executado, em unidades de largura da planta por segundo. */
export const VELOCIDADE = 5

/**
 * Refaz os tempos do desenho em velocidade constante: o caminho e as paradas (botão
 * pressionado com o mouse parado) são os desenhados, mas o andamento não depende da
 * pressa do mouse. Movimento brusco faria as antenas lerem quase juntas e a passagem
 * ficar ambígua. A distância usa a escala real da planta (y dividido pela proporção).
 */
export function uniformizar(pontos: PontoTrajeto[], proporcao: number): PontoTrajeto[] {
  const saida: PontoTrajeto[] = [{ x: pontos[0].x, y: pontos[0].y, t: 0 }]
  let t = 0
  for (let i = 1; i < pontos.length; i++) {
    const a = pontos[i - 1], b = pontos[i]
    const distancia = Math.hypot(b.x - a.x, (b.y - a.y) / proporcao)
    t += distancia < 1e-6 ? Math.max(0, b.t - a.t) : distancia / VELOCIDADE
    saida.push({ x: b.x, y: b.y, t: Math.round(t * 1000) / 1000 })
  }
  return saida
}

function comprimento(pontos: PontoTrajeto[]) {
  let total = 0
  for (let i = 1; i < pontos.length; i++) total += Math.hypot(pontos[i].x - pontos[i - 1].x, pontos[i].y - pontos[i - 1].y)
  return total
}

export function SimulatorControlPage({ codigo, canEdit }: { codigo: string; canEdit: boolean }) {
  const planRef = useRef<HTMLDivElement>(null)
  const clock = useSimClock()
  const [session, setSession] = useState<Sessao | null>(null)
  const [motor, setMotor] = useState<MotorEstado | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ itemId: string; pontos: PontoTrajeto[] } | null>(null)
  const [, setFrame] = useState(0)
  const versao = useRef<number | undefined>(undefined)
  const desenho = useRef<Desenho | null>(null)
  const pausa = useRef<number | null>(null)

  const aplicar = useCallback((dados: Pick<Sessao, 'versao' | 'itens'> & Partial<Sessao>) => {
    if (versao.current !== undefined && dados.versao < versao.current) return
    versao.current = dados.versao
    setSession((old) => old ? { ...old, ...dados } : (dados as Sessao))
  }, [])

  const reload = useCallback(async (full = false) => {
    try {
      const result = await getSession(codigo, full ? undefined : versao.current)
      setMotor(result.motor)
      if (!('inalterada' in result)) {
        if (full) versao.current = undefined
        aplicar(result)
      }
      setError('')
    } catch (failure) { setError(errorMessage(failure)) }
  }, [codigo, aplicar])

  useEffect(() => {
    void reload(true)
    const timer = window.setInterval(() => { void reload() }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [reload])

  const itens = useMemo(() => session?.itens ?? [], [session])
  const animando = !!preview || itens.some((item) => emTrajeto(item, clock.agora()))
  // Animação fluida só enquanto algo se move; parado, um quadro por segundo basta.
  useEffect(() => {
    if (!animando) { const timer = window.setInterval(() => setFrame((n) => n + 1), 1000); return () => window.clearInterval(timer) }
    let pedido = 0
    const passo = () => { setFrame((n) => n + 1); pedido = window.requestAnimationFrame(passo) }
    pedido = window.requestAnimationFrame(passo)
    return () => window.cancelAnimationFrame(pedido)
  }, [animando])

  const pararPausa = () => { if (pausa.current !== null) { window.clearInterval(pausa.current); pausa.current = null } }
  const soltarCaptura = (pointerId: number) => { try { planRef.current?.releasePointerCapture(pointerId) } catch { /* já liberada */ } }

  /** Cancela o desenho sem executar nada (perda de captura, Esc, janela sem foco). */
  const cancelar = useCallback((motivo: string) => {
    const atual = desenho.current
    if (!atual) return
    desenho.current = null
    pararPausa()
    soltarCaptura(atual.pointerId)
    setPreview(null)
    setNotice(`Desenho cancelado (${motivo}). Nada foi executado nem lido.`)
  }, [])

  useEffect(() => {
    const semFoco = () => cancelar('a janela perdeu o foco')
    const tecla = (event: KeyboardEvent) => { if (event.key === 'Escape') cancelar('Esc') }
    window.addEventListener('blur', semFoco)
    window.addEventListener('keydown', tecla)
    return () => { window.removeEventListener('blur', semFoco); window.removeEventListener('keydown', tecla); pararPausa() }
  }, [cancelar])

  function onItemDown(event: ReactPointerEvent, item: ItemVirtual) {
    event.stopPropagation()
    if (event.button !== 0) return
    setSelected(item.id)
    setNotice('')
    if (!canEdit || !session || session.estado !== 'em_execucao') {
      if (canEdit && session?.estado === 'pausada') setNotice('Simulação pausada: retome para executar trajetos.')
      return
    }
    if (emTrajeto(item, clock.agora())) { setNotice(`${item.nome} ainda está percorrendo o trajeto anterior.`); return }
    event.preventDefault()
    try { planRef.current?.setPointerCapture(event.pointerId) } catch { /* jsdom */ }
    const inicio = posicaoNoTempo(item, clock.agora())
    const novo: Desenho = { itemId: item.id, pointerId: event.pointerId, t0: performance.now(), pontos: [{ ...inicio, t: 0 }], ultimo: inicio, ultimoMovimento: performance.now() }
    desenho.current = novo
    setPreview({ itemId: item.id, pontos: [...novo.pontos] })
    pararPausa()
    pausa.current = window.setInterval(() => {
      const atual = desenho.current
      if (atual && performance.now() - atual.ultimoMovimento >= PAUSA_MS) { registrarParada(atual); setPreview({ itemId: atual.itemId, pontos: [...atual.pontos] }) }
    }, PAUSA_MS)
  }

  function onMove(event: ReactPointerEvent<HTMLDivElement>) {
    const atual = desenho.current
    if (!atual || event.pointerId !== atual.pointerId) return
    // Botão esquerdo já solto sem o pointerup chegar: vale como soltar.
    if ((event.buttons & 1) === 0) { void finalizar(event.pointerId); return }
    const ponto = pointFromEvent(planRef.current, event)
    if (Math.hypot(ponto.x - atual.ultimo.x, ponto.y - atual.ultimo.y) < PASSO_MIN) return
    // Retomada após parada: fecha a parada no instante atual antes do novo trecho.
    if (performance.now() - atual.ultimoMovimento >= PAUSA_MS) registrarParada(atual)
    if (atual.pontos.length < MAX_PONTOS) atual.pontos.push({ ...ponto, t: segundos(atual) })
    atual.ultimo = ponto
    atual.ultimoMovimento = performance.now()
    setPreview({ itemId: atual.itemId, pontos: [...atual.pontos] })
  }

  async function finalizar(pointerId: number) {
    const atual = desenho.current
    if (!atual || pointerId !== atual.pointerId) return
    desenho.current = null
    pararPausa()
    soltarCaptura(pointerId)
    registrarParada(atual)
    const pontos = uniformizar(atual.pontos, session?.layout.proporcao ?? 1)
    if (comprimento(pontos) < 0.5) { setPreview(null); return }  // clique: só seleciona
    setNotice('Executando o trajeto desenhado…')
    try {
      const result = await runPath(codigo, atual.itemId, pontos)
      clock.aplicar(result.relogio)
      aplicar({ versao: result.versao, itens: result.itens })
      setNotice('')
    } catch (failure) { setError(errorMessage(failure)); setNotice('') } finally { setPreview(null) }
  }

  async function act(action: () => Promise<unknown>) {
    setError('')
    try { await action(); await reload(true) } catch (failure) { setError(errorMessage(failure)) }
  }

  if (!session) return <main className="sim-control-shell" id="conteudo"><div className="state-panel" role={error ? 'alert' : 'status'}>{error || 'Carregando simulação…'}<p><a href="#/simulador">Voltar ao simulador</a></p></div></main>
  const agora = clock.agora()
  const chosen = itens.find((item) => item.id === selected) ?? null
  const closed = session.estado === 'encerrada'
  const running = session.estado === 'em_execucao'
  const desenhando = preview?.itemId

  return <main className="sim-control-shell sim-control-limpo" id="conteudo">
    <header className="sim-control-header">
      <div><p className="eyebrow">SIMULADOR · {session.cenario === 'easy' ? 'LABORATÓRIO EASY' : 'HOSPITAL HUPAA'}</p><h1>Movimentar equipamentos</h1></div>
      <div className="sim-control-status">
        <span className={`sim-state sim-state-${session.estado}`}>{ESTADO[session.estado]}</span>
        <TimeControls clock={clock} canEdit={canEdit && !closed}/>
        {canEdit && !closed && (running ? <button type="button" onClick={() => act(() => sessionAction(codigo, 'pausar'))}>Pausar</button>
          : <button type="button" className="admin-primary" onClick={() => act(() => sessionAction(codigo, 'retomar'))}>Retomar</button>)}
      </div>
    </header>
    {/* Mensagens flutuam sobre a página: nunca empurram o mapa enquanto se desenha um trajeto. */}
    <div className="sim-mensagens">
      {error && <p className="admin-error" role="alert">{error}</p>}
      {(motor?.erro || motor?.sessao?.erro) && <p className="admin-error" role="alert">Falha na publicação das leituras: {motor?.erro ?? motor?.sessao?.erro}</p>}
      {closed && <p className="admin-warning" role="note">Esta sessão foi encerrada. Inicie outra no painel do simulador.</p>}
      {notice && <p className="sim-notice" role="status">{notice}</p>}
    </div>
    <div className="sim-control-plan">
      <SimPlan ref={planRef} layout={session.layout} label="Planta do hospital com os equipamentos da simulação" options={{ showCoverage: false }}
        className="sim-plan-control" onPointerMove={onMove} onPointerUp={(event) => { void finalizar(event.pointerId) }}
        onPointerCancel={() => cancelar('o navegador cancelou o gesto')}
        onLostPointerCapture={(event) => { if (desenho.current?.pointerId === event.pointerId) cancelar('o ponteiro perdeu a captura') }}
        onPointerDown={() => setSelected(null)}>
        <svg className="sim-path-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {itens.filter((item) => item.trajeto && emTrajeto(item, agora)).map((item) => <polyline key={`exec-${item.id}`} className="sim-path-exec"
            points={item.trajeto!.pontos.map((p) => `${p.x},${p.y}`).join(' ')} vectorEffect="non-scaling-stroke"/>)}
          {preview && <polyline className="sim-path-preview" points={preview.pontos.map((p) => `${p.x},${p.y}`).join(' ')} vectorEffect="non-scaling-stroke"/>}
        </svg>
        {preview && preview.pontos.length > 1 && <span className="sim-path-ghost" style={at(preview.pontos[preview.pontos.length - 1])} aria-hidden="true"/>}
        {itens.map((item) => {
          const posicao = posicaoNoTempo(item, agora)
          const movendo = emTrajeto(item, agora)
          return <button key={item.id} type="button" style={at(posicao)}
            className={`sim-dot ${item.epc ? '' : 'sim-dot-sem-tag'} ${selected === item.id ? 'selected' : ''} ${movendo ? 'moving' : ''} ${desenhando === item.id ? 'drawing' : ''}`}
            aria-label={`${item.nome}${item.epc ? '' : ' (sem etiqueta)'}${movendo ? ', percorrendo trajeto' : ''}`}
            onPointerDown={(event) => onItemDown(event, item)}>
            <EquipIcon tipo={simboloDoTipo(item.tipo, item.nome)}/>
            <span className="sim-dot-nome">{item.nome}{!item.epc && ' · sem etiqueta'}</span>
          </button>
        })}
      </SimPlan>
      <p className="muted-text sim-legend">Pressione o botão esquerdo sobre um equipamento e desenhe o caminho; parar com o botão pressionado vira tempo parado. Ao soltar, o equipamento percorre o desenho e só então é lido. Esc cancela.</p>
    </div>
    <div className="sim-control-bar">
      {canEdit && !closed && <AddItem codigo={codigo} onDone={() => reload(true)} onError={setError}/>}
      {chosen && <section className="panel sim-selected" aria-labelledby="sim-selected-title"><h2 id="sim-selected-title">{chosen.nome}</h2>
        <p>{chosen.tipo ?? 'Sem tipo'} · {chosen.epc ? <>EPC <code>{chosen.epc}</code></> : 'sem etiqueta (não gera leituras)'}</p>
        {canEdit && !closed && <div className="sim-form-actions">
          {chosen.epc ? <button type="button" onClick={() => act(() => updateItem(codigo, chosen.id, { remover_epc: true }))}>Remover etiqueta</button>
            : <button type="button" onClick={() => act(() => updateItem(codigo, chosen.id, { gerar_epc: true }))}>Etiquetar</button>}
          <button type="button" className="danger" onClick={() => act(async () => { await removeItem(codigo, chosen.id); setSelected(null) })}>Remover da planta</button>
        </div>}
      </section>}
      {canEdit && !closed && itens.length > 0 && <button type="button" className="danger sim-remove-all" onClick={() => {
        if (window.confirm(`Remover os ${itens.length} equipamentos da planta? Cadastros no banco não mudam.`)) void act(async () => { await clearItems(codigo); setSelected(null) })
      }}>Remover todos</button>}
    </div>
  </main>
}

function AddItem({ codigo, onDone, onError }: { codigo: string; onDone: () => void; onError: (message: string) => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('Maca')
  const [mode, setMode] = useState<'gerar' | 'informar' | 'cadastrado' | 'sem'>('cadastrado')
  const [epc, setEpc] = useState('')
  const [registered, setRegistered] = useState<EquipamentoCadastro[]>([])
  useEffect(() => {
    if (mode !== 'cadastrado') return
    const controller = new AbortController()
    getRegistrations('com_tag', '', 1, controller.signal).then((page) => setRegistered(page.items ?? [])).catch(() => setRegistered([]))
    return () => controller.abort()
  }, [mode])
  async function submit(event: FormEvent) {
    event.preventDefault()
    const chosen = registered.find((item) => item.epc === epc)
    const nome = name.trim() || chosen?.nome || `${type} ${Math.floor(Math.random() * 900 + 100)}`
    if ((mode === 'informar' || mode === 'cadastrado') && (!epc.trim() || epcProblem(epc))) { onError(epcProblem(epc) ?? 'Informe o EPC.'); return }
    try {
      await addItem(codigo, { nome, tipo: chosen?.tipo_nome ?? type, gerar_epc: mode === 'gerar', epc: mode === 'informar' || mode === 'cadastrado' ? epc.trim() : undefined })
      setName(''); setEpc(''); onDone()
    } catch (failure) { onError(errorMessage(failure)) }
  }
  async function quickAdd(tipo: string) {
    try { await addItem(codigo, { nome: `${tipo} ${Math.floor(Math.random() * 90 + 10)}`, tipo, gerar_epc: true }); onDone() } catch (failure) { onError(errorMessage(failure)) }
  }
  return <form className="panel sim-add" onSubmit={submit} aria-labelledby="sim-add-title"><h2 id="sim-add-title">Adicionar equipamento</h2>
    <div className="sim-quick-add" aria-label="Adicionar com etiqueta gerada">{['Maca', 'Cadeira de rodas', 'Bomba de infusão', 'Monitor'].map((tipo) =>
      <button key={tipo} type="button" onClick={() => { void quickAdd(tipo) }}>+ {tipo}</button>)}</div>
    <details><summary>Equipamento cadastrado, EPC ou sem etiqueta</summary>
    <fieldset className="sim-tag-mode"><legend>Etiqueta RFID</legend>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'cadastrado'} onChange={() => setMode('cadastrado')}/> Equipamento cadastrado</label>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'gerar'} onChange={() => setMode('gerar')}/> Etiqueta nova, não cadastrada</label>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'informar'} onChange={() => setMode('informar')}/> Informar EPC</label>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'sem'} onChange={() => setMode('sem')}/> Sem etiqueta</label>
    </fieldset>
    {mode === 'cadastrado' ? <label>Equipamento<select value={epc} onChange={(e) => setEpc(e.target.value)}><option value="">Selecione…</option>{registered.map((item) => <option key={item.id} value={item.epc ?? ''}>{item.nome} · {item.epc}</option>)}</select></label>
      : <><label>Nome<input value={name} maxLength={80} placeholder="Ex.: Maca 1" onChange={(e) => setName(e.target.value)}/></label>
        <label>Tipo<input value={type} maxLength={60} list="sim-tipos" onChange={(e) => setType(e.target.value)}/></label>
        <datalist id="sim-tipos"><option value="Maca"/><option value="Cadeira de rodas"/><option value="Bomba de infusão"/><option value="Monitor multiparamétrico"/></datalist></>}
    {mode === 'informar' && <label>EPC<input value={epc} maxLength={32} spellCheck={false} onChange={(e) => setEpc(e.target.value.toUpperCase())}/></label>}
    <button type="submit" className="admin-primary">Adicionar à planta</button>
    </details>
  </form>
}
