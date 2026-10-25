import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { ageLabel } from '../components/DashboardParts'
import { Icon } from '../components/layout/Icon'
import { linhasAntena, linhasLeitor, Marcador } from '../components/simulador/Marcador'
import { at, PlanLegend, pointFromEvent, SimPlan } from '../components/simulador/SimPlan'
import { errorMessage } from '../services/api'
import { epcProblem, getRegistrations, type EquipamentoCadastro } from '../services/cadastro'
import {
  addItem, clearItems, getMonitor, getSession, inRange, removeItem, sessionAction, updateItem, zoneAt,
  type ItemVirtual, type Monitor, type MotorEstado, type Sessao,
} from '../services/simulacao'
import { AlertasRestritos } from './SimulatorPage'

const POLL_MS = 500
const MONITOR_MS = 1500
const SEND_MS = 80
const ESTADO: Record<string, string> = { em_execucao: 'Em execução', pausada: 'Pausada', encerrada: 'Encerrada' }
const DIRECAO: Record<string, string> = { confirmed: 'confirmada', ambiguous: 'ambígua', unknown: 'desconhecida' }

type Evento = { id: number; texto: string; em: string }
/** Posição enviada e ainda não confirmada pelo servidor (sobrepõe respostas e polling mais antigos). */
type Pendente = { x: number; y: number; seq: number }

export function SimulatorControlPage({ codigo, canEdit }: { codigo: string; canEdit: boolean }) {
  const planRef = useRef<HTMLDivElement>(null)
  const [session, setSession] = useState<Sessao | null>(null)
  const [motor, setMotor] = useState<MotorEstado | null>(null)
  const [monitor, setMonitor] = useState<Monitor | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null)
  const [events, setEvents] = useState<Evento[]>([])
  const [, forceRender] = useState(0)
  const lastSent = useRef(0)
  const versao = useRef<number | undefined>(undefined)
  const seq = useRef(0)
  const pendentes = useRef(new Map<string, Pendente>())
  const previousRange = useRef(new Map<string, Set<string>>())
  const eventId = useRef(0)

  /** Aplica uma versão do servidor só se não for mais antiga; posições locais pendentes continuam valendo. */
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
        if (full) versao.current = undefined  // recarga completa (reiniciar, etiquetar): aceita o estado do servidor
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

  // O que o pipeline confirmou (leituras gravadas, passagens, alertas): nunca calculado no navegador.
  useEffect(() => {
    let vivo = true
    const buscar = () => { getMonitor(codigo).then((dados) => { if (vivo) setMonitor(dados) }).catch(() => undefined) }
    buscar()
    const timer = window.setInterval(buscar, MONITOR_MS)
    return () => { vivo = false; window.clearInterval(timer) }
  }, [codigo])

  const items = useMemo(() => (session?.itens ?? []).map((item) => {
    if (drag?.id === item.id) return { ...item, x: drag.x, y: drag.y }
    const pendente = pendentes.current.get(item.id)
    return pendente ? { ...item, x: pendente.x, y: pendente.y } : item
  }), [session, drag])
  const antennas = useMemo(() => session?.layout.leitores.flatMap((leitor) => leitor.antenas.map((antena) => ({ leitor, antena }))) ?? [], [session])
  const running = session?.estado === 'em_execucao'

  // Detecção local só para destacar a área de leitura; a leitura de verdade é publicada pelo servidor.
  const ranges = useMemo(() => {
    const result = new Map<string, Set<string>>()
    if (!session) return result
    for (const item of items) result.set(item.id, new Set(antennas.filter(({ antena }) => inRange(item, antena, session.layout.proporcao)).map(({ antena }) => antena.chave)))
    return result
  }, [items, antennas, session])
  const active = useMemo(() => new Set(running ? items.filter((item) => item.epc).flatMap((item) => [...(ranges.get(item.id) ?? [])]) : []), [items, ranges, running])

  useEffect(() => {
    if (!session) return
    const novos: Evento[] = []
    for (const item of items) {
      const now = ranges.get(item.id) ?? new Set()
      const before = previousRange.current.get(item.id) ?? new Set()
      for (const chave of now) if (!before.has(chave)) {
        const alvo = antennas.find(({ antena }) => antena.chave === chave)
        if (!alvo) continue
        const texto = !item.epc ? `${item.nome} na área da ${alvo.leitor.nome}/${alvo.antena.nome}, mas sem etiqueta: nenhuma leitura.`
          : running ? `${item.nome} entrou na área da ${alvo.leitor.nome}/${alvo.antena.nome}: leituras sendo publicadas.`
            : `${item.nome} na área da ${alvo.leitor.nome}/${alvo.antena.nome} (simulação pausada: sem leitura).`
        novos.push({ id: ++eventId.current, texto, em: new Date().toLocaleTimeString('pt-BR') })
      }
    }
    previousRange.current = ranges
    if (novos.length) setEvents((old) => [...novos.reverse(), ...old].slice(0, 30))
  }, [ranges, items, antennas, running, session])

  function send(id: string, x: number, y: number, force = false) {
    const now = Date.now()
    if (!force && now - lastSent.current < SEND_MS) return
    lastSent.current = now
    const meu = ++seq.current
    pendentes.current.set(id, { x, y, seq: meu })
    updateItem(codigo, id, { x, y }).then((result) => {
      // Só a resposta do ÚLTIMO envio deste item libera a posição local; respostas antigas não a desfazem.
      if (pendentes.current.get(id)?.seq === meu) pendentes.current.delete(id)
      aplicar({ versao: result.versao, itens: result.itens })
      forceRender((n) => n + 1)
    }).catch((failure) => { if (pendentes.current.get(id)?.seq === meu) pendentes.current.delete(id); setError(errorMessage(failure)) })
  }

  function onItemDown(event: ReactPointerEvent, item: ItemVirtual) {
    event.stopPropagation()
    setSelected(item.id)
    if (!canEdit || session?.estado === 'encerrada') return
    try { planRef.current?.setPointerCapture(event.pointerId) } catch { /* jsdom */ }
    setDrag({ id: item.id, x: item.x, y: item.y })
  }
  function onMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag) return
    const point = pointFromEvent(planRef.current, event)
    setDrag({ ...drag, ...point })
    send(drag.id, point.x, point.y)
  }
  function onUp() {
    if (!drag) return
    send(drag.id, drag.x, drag.y, true)  // a posição final sempre vai, mesmo dentro do intervalo
    setDrag(null)
  }

  async function act(action: () => Promise<unknown>) {
    setError('')
    try { await action(); await reload(true) } catch (failure) { setError(errorMessage(failure)) }
  }

  if (!session) return <main className="sim-control-shell" id="conteudo"><div className="state-panel" role={error ? 'alert' : 'status'}>{error || 'Carregando simulação…'}<p><a href="#/simulador">Voltar ao simulador</a></p></div></main>
  const chosen = items.find((item) => item.id === selected) ?? null
  const virtualZone = chosen ? zoneAt(session.layout, chosen) : null
  const closed = session.estado === 'encerrada'
  const lendoAgora = items.filter((item) => running && item.epc && (ranges.get(item.id)?.size ?? 0) > 0).length
  const alertas = monitor?.alertas_restritos ?? []
  const publicadas = motor?.sessao?.publicadas ?? 0
  const confirmadas = monitor?.passagens.filter((p) => p.direcao_status === 'confirmed').length ?? 0

  return <main className="sim-control-shell" id="conteudo">
    <header className="sim-control-header">
      <div><p className="eyebrow">CONTROLE DA SIMULAÇÃO · {session.cenario === 'easy' ? 'LABORATÓRIO EASY' : 'HOSPITAL HUPAA'}</p><h1>Movimentar equipamentos</h1></div>
      <div className="sim-control-status">
        <span className={`sim-state sim-state-${session.estado}`}>{ESTADO[session.estado]}</span>
        {motor && <span className={`sim-pub ${motor.conectado && !motor.erro ? 'ok' : 'off'}`} title={motor.destino ?? ''}>{motor.conectado && !motor.erro ? 'MQTT conectado' : 'MQTT com falha'} · {publicadas} publicada(s)</span>}
        {canEdit && !closed && <>{running ? <button type="button" onClick={() => act(() => sessionAction(codigo, 'pausar'))}>Pausar</button> : <button type="button" className="admin-primary" onClick={() => act(() => sessionAction(codigo, 'retomar'))}>Retomar</button>}
          <button type="button" onClick={() => act(() => sessionAction(codigo, 'reiniciar'))}>Reiniciar</button></>}
        <a href="#/simulador" className="link-button">Painel do simulador</a>
      </div>
    </header>
    {error && <p className="admin-error" role="alert">{error}</p>}
    {motor?.erro && <p className="admin-error" role="alert">Falha na publicação MQTT: {motor.erro}</p>}
    {closed && <p className="admin-warning" role="note">Esta sessão foi encerrada. Inicie outra no painel do simulador.</p>}
    <AlertasRestritos alertas={alertas} compacto/>
    <ol className="sim-stages" aria-label="Etapas da detecção">
      <li className="on"><strong>1. Movimento virtual</strong><span>{items.length} equipamento(s) na planta</span></li>
      <li className={lendoAgora ? 'on' : ''}><strong>2. Na área de leitura</strong><span>{lendoAgora} agora (cálculo da tela)</span></li>
      <li className={publicadas ? 'on' : ''}><strong>3. Publicado no MQTT</strong><span>{publicadas} leitura(s) enviada(s)</span></li>
      <li className={confirmadas || alertas.length ? 'on' : ''}><strong>4. Confirmado pelo sistema</strong><span>{monitor ? `${monitor.leituras_total} gravada(s) · ${confirmadas} passagem(ns)` : 'aguardando'}</span></li>
    </ol>
    <div className="sim-control-body">
      <div className="sim-control-plan">
        <SimPlan ref={planRef} layout={session.layout} label="Planta da simulação com equipamentos virtuais" options={{ activeAntennas: active }} className="sim-plan-control" onPointerMove={onMove} onPointerUp={onUp}
          onPointerDown={() => setSelected(null)}>
          {session.layout.portais.map((portal) => portal.posicao && <Marcador key={portal.chave} tipo="portal" estatico posicao={portal.posicao} titulo={`Portal ${portal.nome}`} linhas={[]}/>)}
          {session.layout.leitores.map((leitor) => <div key={leitor.chave}>
            {leitor.posicao && <Marcador tipo="leitor" estatico posicao={leitor.posicao} titulo={leitor.nome} linhas={linhasLeitor(leitor)} restrito={!!leitor.alerta_area_restrita}/>}
            {leitor.antenas.map((antena) => antena.posicao && <Marcador key={antena.chave} tipo="antena" estatico posicao={antena.posicao} titulo={antena.nome}
              linhas={linhasAntena(leitor, antena, session.layout.portais)} orientacao={antena.orientacao} lendo={active.has(antena.chave)}/>)}
          </div>)}
          {items.map((item) => {
            const reading = running && !!item.epc && (ranges.get(item.id)?.size ?? 0) > 0
            return <button key={item.id} type="button" className={`sim-item ${item.epc ? 'tagged' : 'untagged'} ${reading ? 'reading' : ''} ${selected === item.id ? 'selected' : ''} ${drag?.id === item.id ? 'dragging' : ''}`}
              style={at(item)} aria-label={`${item.nome}${item.epc ? '' : ' (sem etiqueta)'}${reading ? ', sendo lido' : ''}`} onPointerDown={(e) => onItemDown(e, item)}>
              <Icon name="equipment" size={13}/><span>{item.nome}{!item.epc && ' · sem tag'}</span></button>
          })}
        </SimPlan>
        <p className="muted-text sim-legend"><span className="legend-dot tagged"/> etiquetado <span className="legend-dot untagged"/> sem etiqueta <span className="legend-dot reading"/> na área de leitura. Passe o mouse nos pontos para ver leitor, antena, porta e visada. A zona só muda depois que o sistema confirma a passagem.</p>
        {session.layout.cenario === 'hupaa' && <PlanLegend/>}
      </div>
      <aside className="sim-control-side">
        {canEdit && !closed && <AddItem codigo={codigo} onDone={() => reload(true)} onError={setError}/>}
        {chosen && <section className="panel sim-selected" aria-labelledby="sim-selected-title"><h2 id="sim-selected-title">{chosen.nome}</h2>
          <p>{chosen.tipo ?? 'Sem tipo'} · posição virtual {chosen.x.toFixed(1)}, {chosen.y.toFixed(1)}{virtualZone ? ` (dentro de ${virtualZone.nome})` : ''}</p>
          <p>{chosen.epc ? <>EPC <code>{chosen.epc}</code> <button type="button" className="link-button" onClick={() => { void navigator.clipboard?.writeText(chosen.epc!) }}>copiar</button></> : 'Sem etiqueta: não produz leituras RFID.'}</p>
          {canEdit && !closed && <div className="sim-form-actions">
            {chosen.epc ? <button type="button" onClick={() => act(() => updateItem(codigo, chosen.id, { remover_epc: true }))}>Remover etiqueta</button>
              : <button type="button" className="admin-primary" onClick={() => act(() => updateItem(codigo, chosen.id, { gerar_epc: true }))}>Etiquetar (gerar EPC)</button>}
            <button type="button" className="danger" onClick={() => act(async () => { await removeItem(codigo, chosen.id); setSelected(null) })}>Remover da planta</button>
          </div>}
          {chosen.epc && <p className="muted-text">Tag ainda não cadastrada? Selecione este EPC em <a href="#/cadastro" target="_blank" rel="noopener">Cadastro → por leitura RFID</a> depois que ele for lido.</p>}
        </section>}
        <section className="panel" aria-labelledby="sim-items-title"><div className="sim-items-heading"><h2 id="sim-items-title">Equipamentos virtuais ({items.length})</h2>
          {canEdit && !closed && items.length > 0 && <button type="button" className="danger" onClick={() => {
            if (window.confirm(`Remover os ${items.length} equipamentos da planta? Cadastros no banco não mudam.`)) void act(async () => { await clearItems(codigo); setSelected(null) })
          }}>Remover todos</button>}</div>
          {items.length ? <ul className="sim-item-list">{items.map((item) => <li key={item.id}><button type="button" className="link-button" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>{item.nome}</button>
            <span className={`tag-chip ${item.epc ? 'tag-known' : 'tag-unknown'}`}>{item.epc ? 'etiquetado' : 'sem tag'}</span>
            {running && item.epc && (ranges.get(item.id)?.size ?? 0) > 0 && <span className="tag-chip tag-reading">na área</span>}</li>)}</ul>
            : <p className="muted-text">Adicione equipamentos e arraste-os pela planta.</p>}
        </section>
        <section className="panel" aria-labelledby="sim-confirmed-title"><h2 id="sim-confirmed-title">Confirmado pelo sistema</h2>
          {monitor?.passagens.length ? <ol className="sim-events">{monitor.passagens.slice(0, 6).map((passagem) => <li key={passagem.id}><time>{ageLabel(passagem.detectada_em)}</time> {passagem.equipamento ?? 'Tag não cadastrada'} · {passagem.portal} · {passagem.direcao_status ? DIRECAO[passagem.direcao_status] : 'em análise'}{passagem.zona_destino ? ` → ${passagem.zona_destino}` : ''}</li>)}</ol>
            : <p className="muted-text">Nenhuma passagem gravada ainda. Leve um item etiquetado de um lado do portal ao outro.</p>}
        </section>
        <section className="panel" aria-labelledby="sim-events-title"><h2 id="sim-events-title">Na área de leitura (tela)</h2>
          {events.length ? <ol className="sim-events">{events.map((event) => <li key={event.id}><time>{event.em}</time> {event.texto}</li>)}</ol> : <p className="muted-text">Quando um equipamento entrar numa área de leitura, aparece aqui.</p>}
        </section>
      </aside>
    </div>
  </main>
}

function AddItem({ codigo, onDone, onError }: { codigo: string; onDone: () => void; onError: (message: string) => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('Maca')
  const [mode, setMode] = useState<'gerar' | 'informar' | 'cadastrado' | 'sem'>('gerar')
  const [epc, setEpc] = useState('')
  const [registered, setRegistered] = useState<EquipamentoCadastro[]>([])
  useEffect(() => {
    if (mode !== 'cadastrado') return
    const controller = new AbortController()
    getRegistrations('com_tag', '', 1, controller.signal).then((page) => setRegistered(page.items)).catch(() => setRegistered([]))
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
    <div className="sim-quick-add" aria-label="Adicionar com etiqueta gerada">{['Maca', 'Cadeira de rodas', 'Bomba de infusão'].map((tipo) =>
      <button key={tipo} type="button" onClick={() => { void quickAdd(tipo) }}>+ {tipo}</button>)}</div>
    <details><summary>Mais opções (nome, EPC, sem etiqueta)</summary>
    <label>Nome<input value={name} maxLength={80} placeholder="Ex.: Maca 1" onChange={(e) => setName(e.target.value)}/></label>
    <label>Tipo<input value={type} maxLength={60} list="sim-tipos" onChange={(e) => setType(e.target.value)}/></label>
    <datalist id="sim-tipos"><option value="Maca"/><option value="Cadeira de rodas"/><option value="Bomba de infusão"/><option value="Monitor multiparamétrico"/></datalist>
    <fieldset className="sim-tag-mode"><legend>Etiqueta RFID</legend>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'gerar'} onChange={() => setMode('gerar')}/> Etiquetado, não cadastrado (gerar EPC)</label>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'cadastrado'} onChange={() => setMode('cadastrado')}/> Usar EPC de equipamento cadastrado</label>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'informar'} onChange={() => setMode('informar')}/> Informar EPC</label>
      <label className="checkbox-label"><input type="radio" name="modo" checked={mode === 'sem'} onChange={() => setMode('sem')}/> Sem etiqueta (não gera leituras)</label>
    </fieldset>
    {mode === 'informar' && <label>EPC<input value={epc} maxLength={32} spellCheck={false} onChange={(e) => setEpc(e.target.value.toUpperCase())}/></label>}
    {mode === 'cadastrado' && <label>Equipamento cadastrado<select value={epc} onChange={(e) => setEpc(e.target.value)}><option value="">Selecione…</option>{registered.map((item) => <option key={item.id} value={item.epc ?? ''}>{item.nome} · {item.epc}</option>)}</select></label>}
    <button type="submit" className="admin-primary">Adicionar à planta</button>
    </details>
  </form>
}
