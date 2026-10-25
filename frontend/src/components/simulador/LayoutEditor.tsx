import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Icon } from '../layout/Icon'
import { zonaRestritaDoLeitor, type AntenaLayout, type LayoutConfig, type LeitorLayout, type Modelo, type Ponto } from '../../services/simulacao'
import { at, pointFromEvent, SimPlan } from './SimPlan'

type Selection = { kind: 'zona' | 'portal' | 'leitor'; chave: string; antena?: string } | null
type Tool = { kind: 'selecionar' } | { kind: 'zona'; alvo?: string } | { kind: 'leitor' } | { kind: 'posicionar'; alvo: 'leitor' | 'antena' | 'portal'; chave: string; leitor?: string }
type Drag =
  | { kind: 'desenho'; inicio: Ponto; atual: Ponto; alvo?: string }
  | { kind: 'mover-zona' | 'redimensionar-zona'; chave: string; inicio: Ponto; area: { x: number; y: number; largura: number; altura: number } }
  | { kind: 'leitor' | 'portal'; chave: string }
  | { kind: 'antena'; chave: string; leitor: string }

const CORES = ['#2f6fb2', '#1f8a70', '#b26b2f', '#7a3fb2', '#c2413b', '#2a8a9a', '#8a7a1f']
const MODELOS: { id: Modelo; nome: string }[] = [{ id: 'EZ700', nome: 'Identix EZ700' }, { id: 'DR_MAX', nome: 'Identix DR Max (virtual)' }]
const MAX_ANTENAS = 4
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const round = (value: number) => Math.round(value * 10) / 10

function novaChave(prefixo: string, existentes: string[]) {
  let indice = existentes.length + 1
  while (existentes.includes(`${prefixo}-${indice}`)) indice++
  return `${prefixo}-${indice}`
}

/** Leitor de portal pronto: antena A dentro da zona A, B dentro da zona B, sem alcances sobrepostos. */
function leitorDoPortal(draft: LayoutConfig, portal: string, a: string, b: string): LeitorLayout {
  const chave = novaChave('leitor', todasAsChaves(draft))
  const ids = draft.leitores.map((l) => l.reader_id)
  let numero = draft.leitores.length + 1
  while (ids.includes(`sim-${draft.cenario}-${String(numero).padStart(2, '0')}`)) numero++
  const areaA = draft.zonas.find((z) => z.chave === a)?.area, areaB = draft.zonas.find((z) => z.chave === b)?.area
  let posicoes: { leitor: Ponto | null; a: Ponto | null; b: Ponto | null } = { leitor: null, a: null, b: null }
  if (areaA && areaB) {
    // Escala de x (y dividido pela proporção), a mesma do cálculo de alcance.
    const p = draft.proporcao
    const ca = { x: areaA.x + areaA.largura / 2, y: (areaA.y + areaA.altura / 2) / p }
    const cb = { x: areaB.x + areaB.largura / 2, y: (areaB.y + areaB.altura / 2) / p }
    const mx = (ca.x + cb.x) / 2, my = (ca.y + cb.y) / 2
    const dist = Math.hypot(cb.x - ca.x, cb.y - ca.y) || 1
    const ux = (cb.x - ca.x) / dist, uy = (cb.y - ca.y) / dist
    const dentro = (x: number, y: number, area: NonNullable<typeof areaA>) => ({
      x: round(Math.min(area.x + area.largura - 2, Math.max(area.x + 2, x))),
      y: round(Math.min(area.y + area.altura - 2, Math.max(area.y + 2, y * p))),
    })
    const passo = Math.min(7, dist / 2)
    posicoes = {
      a: dentro(mx - ux * passo, my - uy * passo, areaA),
      b: dentro(mx + ux * passo, my + uy * passo, areaB),
      leitor: { x: round(Math.min(97, Math.max(3, mx - uy * 6))), y: round(Math.min(97, Math.max(3, (my + ux * 6) * p))) },
    }
  }
  const antena = (porta: number, lado: 'a' | 'b', posicao: Ponto | null, zona: string): AntenaLayout =>
    ({ chave: `${chave}-antena-${porta}`, nome: `Antena ${lado.toUpperCase()}`, porta, posicao, alcance: 5, portal, lado, zona })
  return { chave, nome: `Leitor ${numero}`, reader_id: `sim-${draft.cenario}-${String(numero).padStart(2, '0')}`, modelo: 'EZ700', posicao: posicoes.leitor,
    antenas: [antena(1, 'a', posicoes.a, a), antena(2, 'b', posicoes.b, b)] }
}

function todasAsChaves(config: LayoutConfig) {
  return [...config.zonas.map((z) => z.chave), ...config.portais.map((p) => p.chave), ...config.leitores.map((l) => l.chave),
    ...config.leitores.flatMap((l) => l.antenas.map((a) => a.chave))]
}

export function LayoutEditor({ config, onChange, disabled = false }: { config: LayoutConfig; onChange: (config: LayoutConfig) => void; disabled?: boolean }) {
  const planRef = useRef<HTMLDivElement>(null)
  const [selection, setSelection] = useState<Selection>(null)
  const [tool, setTool] = useState<Tool>({ kind: 'selecionar' })
  const [drag, setDrag] = useState<Drag | null>(null)
  const [aviso, setAviso] = useState('')

  const update = (mutate: (draft: LayoutConfig) => void) => { const draft = clone(config); mutate(draft); onChange(draft) }
  const leitorDe = (draft: LayoutConfig, chave: string) => draft.leitores.find((l) => l.chave === chave)!

  function capture(event: ReactPointerEvent) {
    try { planRef.current?.setPointerCapture(event.pointerId) } catch { /* jsdom */ }
  }

  function onPlanDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (disabled) return
    const ponto = pointFromEvent(planRef.current, event)
    if (tool.kind === 'zona') { capture(event); setDrag({ kind: 'desenho', inicio: ponto, atual: ponto, alvo: tool.alvo }); return }
    if (tool.kind === 'leitor') {
      update((draft) => {
        const chaves = todasAsChaves(draft)
        const chave = novaChave('leitor', chaves)
        const ids = draft.leitores.map((l) => l.reader_id)
        let numero = draft.leitores.length + 1
        while (ids.includes(`sim-${draft.cenario}-${String(numero).padStart(2, '0')}`)) numero++
        draft.leitores.push({ chave, nome: `Leitor ${numero}`, reader_id: `sim-${draft.cenario}-${String(numero).padStart(2, '0')}`, modelo: 'EZ700', posicao: ponto,
          antenas: [{ chave: novaChave(`${chave}-antena`, chaves), nome: 'Antena 1', porta: 1, posicao: { x: Math.min(100, ponto.x + 4), y: ponto.y }, alcance: 6, portal: null, lado: null, zona: draft.zonas[0]?.chave ?? null }] })
        setSelection({ kind: 'leitor', chave })
      })
      setTool({ kind: 'selecionar' }); return
    }
    if (tool.kind === 'posicionar') {
      update((draft) => {
        if (tool.alvo === 'leitor') leitorDe(draft, tool.chave).posicao = ponto
        if (tool.alvo === 'portal') draft.portais.find((p) => p.chave === tool.chave)!.posicao = ponto
        if (tool.alvo === 'antena') leitorDe(draft, tool.leitor!).antenas.find((a) => a.chave === tool.chave)!.posicao = ponto
      })
      setTool({ kind: 'selecionar' }); return
    }
    setSelection(null)
  }

  function onPlanMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag) return
    const ponto = pointFromEvent(planRef.current, event)
    if (drag.kind === 'desenho') { setDrag({ ...drag, atual: ponto }); return }
    update((draft) => {
      if (drag.kind === 'mover-zona' || drag.kind === 'redimensionar-zona') {
        const zona = draft.zonas.find((z) => z.chave === drag.chave)!
        const dx = ponto.x - drag.inicio.x, dy = ponto.y - drag.inicio.y
        if (drag.kind === 'mover-zona') zona.area = { ...drag.area, x: round(Math.min(100 - drag.area.largura, Math.max(0, drag.area.x + dx))), y: round(Math.min(100 - drag.area.altura, Math.max(0, drag.area.y + dy))) }
        else zona.area = { ...drag.area, largura: round(Math.max(2, Math.min(100 - drag.area.x, drag.area.largura + dx))), altura: round(Math.max(2, Math.min(100 - drag.area.y, drag.area.altura + dy))) }
      } else if (drag.kind === 'leitor') leitorDe(draft, drag.chave).posicao = ponto
      else if (drag.kind === 'portal') draft.portais.find((p) => p.chave === drag.chave)!.posicao = ponto
      else if (drag.kind === 'antena') leitorDe(draft, drag.leitor).antenas.find((a) => a.chave === drag.chave)!.posicao = ponto
    })
  }

  function onPlanUp() {
    if (drag?.kind === 'desenho') {
      const x = Math.min(drag.inicio.x, drag.atual.x), y = Math.min(drag.inicio.y, drag.atual.y)
      const largura = round(Math.abs(drag.atual.x - drag.inicio.x)), altura = round(Math.abs(drag.atual.y - drag.inicio.y))
      if (largura >= 2 && altura >= 2) {
        const area = { x: round(x), y: round(y), largura, altura }
        update((draft) => {
          if (drag.alvo) { draft.zonas.find((z) => z.chave === drag.alvo)!.area = area; setSelection({ kind: 'zona', chave: drag.alvo }); return }
          const chave = novaChave('zona', todasAsChaves(draft))
          let numero = draft.zonas.length + 1
          while (draft.zonas.some((z) => z.nome === `Zona ${numero}`)) numero++
          draft.zonas.push({ chave, nome: `Zona ${numero}`, cor: CORES[draft.zonas.length % CORES.length], area, referencia_planta: null, restrita: false })
          setSelection({ kind: 'zona', chave })
        })
        setTool({ kind: 'selecionar' })
      } else setAviso('Arraste para desenhar o retângulo da zona.')
    }
    setDrag(null)
  }

  function startDrag(event: ReactPointerEvent, value: Drag, select: Selection) {
    event.stopPropagation()
    if (disabled || tool.kind !== 'selecionar') return
    capture(event)
    setSelection(select)
    setDrag(value)
  }

  function removeZone(chave: string) {
    if (config.portais.some((p) => p.zona_a === chave || p.zona_b === chave) || config.leitores.some((l) => l.antenas.some((a) => !a.portal && a.zona === chave))) {
      setAviso('Remova antes os portais e antenas ligados a esta zona.'); return
    }
    update((draft) => { draft.zonas = draft.zonas.filter((z) => z.chave !== chave) }); setSelection(null)
  }

  function removePortal(chave: string) {
    update((draft) => {
      const portal = draft.portais.find((p) => p.chave === chave)!
      for (const antena of draft.leitores.flatMap((l) => l.antenas)) {
        if (antena.portal === chave) { antena.zona = antena.lado === 'b' ? portal.zona_b : portal.zona_a; antena.portal = null; antena.lado = null }
      }
      draft.portais = draft.portais.filter((p) => p.chave !== chave)
    })
    setSelection(null)
  }

  function removeSelection() {
    if (!selection || disabled) return
    if (selection.kind === 'zona') removeZone(selection.chave)
    else if (selection.kind === 'portal') removePortal(selection.chave)
    else if (selection.antena) {
      const leitor = config.leitores.find((l) => l.chave === selection.chave)
      if (!leitor || leitor.antenas.length <= 1) { setAviso('Um leitor precisa de pelo menos uma antena.'); return }
      update((d) => { const alvo = leitorDe(d, selection.chave); alvo.antenas = alvo.antenas.filter((a) => a.chave !== selection.antena) })
      setSelection({ kind: 'leitor', chave: selection.chave })
    } else { update((d) => { d.leitores = d.leitores.filter((l) => l.chave !== selection.chave) }); setSelection(null) }
  }

  function clearAll() {
    if (!window.confirm('Apagar todas as zonas, portais, leitores e antenas desta planta? Nada é salvo até você clicar em “Salvar layout”.')) return
    update((draft) => { draft.zonas = []; draft.portais = []; draft.leitores = [] })
    setSelection(null); setTool({ kind: 'selecionar' })
  }

  /** Chip "posicionar": entra no modo de posicionar o primeiro elemento que falta. */
  function placeMissing(leitor: LeitorLayout) {
    if (!leitor.posicao) { setSelection({ kind: 'leitor', chave: leitor.chave }); setTool({ kind: 'posicionar', alvo: 'leitor', chave: leitor.chave }); return }
    const antena = leitor.antenas.find((a) => !a.posicao)
    if (antena) { setSelection({ kind: 'leitor', chave: leitor.chave, antena: antena.chave }); setTool({ kind: 'posicionar', alvo: 'antena', chave: antena.chave, leitor: leitor.chave }) }
  }

  const desenho = drag?.kind === 'desenho' ? { x: Math.min(drag.inicio.x, drag.atual.x), y: Math.min(drag.inicio.y, drag.atual.y), w: Math.abs(drag.atual.x - drag.inicio.x), h: Math.abs(drag.atual.y - drag.inicio.y) } : null
  const alvoPosicionar = tool.kind !== 'posicionar' ? '' : tool.alvo === 'leitor' ? config.leitores.find((l) => l.chave === tool.chave)?.nome
    : tool.alvo === 'portal' ? `portal ${config.portais.find((p) => p.chave === tool.chave)?.nome ?? ''}`
      : config.leitores.find((l) => l.chave === tool.leitor)?.antenas.find((a) => a.chave === tool.chave)?.nome
  const dica = tool.kind === 'zona' ? 'Clique e arraste na planta para delimitar a zona.' : tool.kind === 'leitor' ? 'Clique na planta para posicionar o novo leitor.'
    : tool.kind === 'posicionar' ? `Clique na planta onde fica: ${alvoPosicionar ?? 'o elemento'} (Esc cancela).` : 'Arraste para mover. Selecione e aperte Delete para remover. A alça no canto redimensiona a zona.'

  return <div className="sim-editor" onKeyDown={(event) => {
    if ((event.target as HTMLElement).closest('input, select, textarea')) return
    if (event.key === 'Escape') { setTool({ kind: 'selecionar' }); setSelection(null) }
    if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); removeSelection() }
  }}>
    <div className="sim-toolbar" role="toolbar" aria-label="Ferramentas da planta">
      <button type="button" aria-pressed={tool.kind === 'selecionar'} onClick={() => setTool({ kind: 'selecionar' })}>Selecionar e mover</button>
      <button type="button" aria-pressed={tool.kind === 'zona' && !tool.alvo} disabled={disabled} onClick={() => setTool({ kind: 'zona' })}>Desenhar zona</button>
      <button type="button" aria-pressed={tool.kind === 'leitor'} disabled={disabled} onClick={() => setTool({ kind: 'leitor' })}>Adicionar leitor</button>
      <NewPortal config={config} disabled={disabled || config.zonas.length < 2} onCreate={(nome, a, b, comLeitor) => update((draft) => {
        const chave = novaChave('portal', todasAsChaves(draft))
        const leitor = comLeitor ? leitorDoPortal(draft, chave, a, b) : null
        const [pa, pb] = [leitor?.antenas[0].posicao, leitor?.antenas[1].posicao]
        draft.portais.push({ chave, nome, zona_a: a, zona_b: b, posicao: pa && pb ? { x: round((pa.x + pb.x) / 2), y: round((pa.y + pb.y) / 2) } : null })
        if (leitor) { draft.leitores.push(leitor); setSelection({ kind: 'leitor', chave: leitor.chave }) } else setSelection({ kind: 'portal', chave })
      })}/>
      <button type="button" className="danger" disabled={disabled || (!config.zonas.length && !config.leitores.length)} onClick={clearAll}>Limpar planta</button>
      <span className="sim-hint" role="status">{dica}</span>
    </div>
    {aviso && <p className="admin-warning" role="alert" onClick={() => setAviso('')}>{aviso}</p>}
    <div className="sim-editor-body">
      <SimPlan ref={planRef} layout={config} label="Planta editável da simulação" className={`sim-plan-editor tool-${tool.kind}`} options={{ selected: selection?.chave }}
        onPointerDown={onPlanDown} onPointerMove={onPlanMove} onPointerUp={onPlanUp}>
        {config.zonas.map((zona) => zona.area && <div key={zona.chave} className={`sim-zone-hit ${selection?.chave === zona.chave ? 'selected' : ''}`}
          style={{ left: `${zona.area.x}%`, top: `${zona.area.y}%`, width: `${zona.area.largura}%`, height: `${zona.area.altura}%` }}
          onPointerDown={(e) => startDrag(e, { kind: 'mover-zona', chave: zona.chave, inicio: pointFromEvent(planRef.current, e), area: zona.area! }, { kind: 'zona', chave: zona.chave })}>
          {selection?.chave === zona.chave && <span className="sim-resize" aria-label={`Redimensionar ${zona.nome}`}
            onPointerDown={(e) => startDrag(e, { kind: 'redimensionar-zona', chave: zona.chave, inicio: pointFromEvent(planRef.current, e), area: zona.area! }, { kind: 'zona', chave: zona.chave })}/>}
        </div>)}
        {desenho && <div className="sim-drawing" style={{ left: `${desenho.x}%`, top: `${desenho.y}%`, width: `${desenho.w}%`, height: `${desenho.h}%` }}/>}
        {config.portais.map((portal) => portal.posicao && <button key={portal.chave} type="button" className={`sim-marker sim-portal ${selection?.chave === portal.chave ? 'selected' : ''}`} style={at(portal.posicao)}
          aria-label={`Portal ${portal.nome}`} onPointerDown={(e) => startDrag(e, { kind: 'portal', chave: portal.chave }, { kind: 'portal', chave: portal.chave })}><Icon name="portal" size={16}/><span>{portal.nome}</span></button>)}
        {config.leitores.map((leitor) => <div key={leitor.chave}>
          {leitor.posicao && <button type="button" className={`sim-marker sim-reader ${zonaRestritaDoLeitor(config, leitor) ? 'restrita' : ''} ${selection?.chave === leitor.chave ? 'selected' : ''}`} style={at(leitor.posicao)} aria-label={`${leitor.nome} (${leitor.reader_id})`}
            onPointerDown={(e) => startDrag(e, { kind: 'leitor', chave: leitor.chave }, { kind: 'leitor', chave: leitor.chave })}><Icon name="reader" size={16}/><span>{leitor.nome}</span></button>}
          {leitor.antenas.map((antena) => antena.posicao && <button key={antena.chave} type="button" className={`sim-marker sim-antenna ${selection?.antena === antena.chave ? 'selected' : ''}`} style={at(antena.posicao)}
            aria-label={`${leitor.nome} · ${antena.nome}`} onPointerDown={(e) => startDrag(e, { kind: 'antena', chave: antena.chave, leitor: leitor.chave }, { kind: 'leitor', chave: leitor.chave, antena: antena.chave })}>
            <Icon name="antenna" size={14}/><span>{antena.nome}{antena.lado ? ` · ${antena.lado.toUpperCase()}` : ''}</span></button>)}
        </div>)}
      </SimPlan>
      <aside className="sim-side panel" aria-label="Propriedades">
        {!selection && <Overview config={config} onSelect={setSelection} onPlace={disabled ? undefined : placeMissing}/>}
        {selection?.kind === 'zona' && (() => {
          const zona = config.zonas.find((z) => z.chave === selection.chave)
          if (!zona) return null
          return <div className="sim-form"><h3>Zona</h3>
            <label>Nome<input value={zona.nome} maxLength={80} disabled={disabled} onChange={(e) => update((d) => { d.zonas.find((z) => z.chave === zona.chave)!.nome = e.target.value })}/></label>
            <label>Cor<input type="color" value={zona.cor} disabled={disabled} onChange={(e) => update((d) => { d.zonas.find((z) => z.chave === zona.chave)!.cor = e.target.value })}/></label>
            <label className="checkbox-label"><input type="checkbox" checked={zona.restrita} disabled={disabled} onChange={(e) => update((d) => { d.zonas.find((z) => z.chave === zona.chave)!.restrita = e.target.checked })}/> Área restrita (ex.: circulação vertical)</label>
            <p className="muted-text">{zona.area ? `Delimitação: x ${zona.area.x}, y ${zona.area.y}, ${zona.area.largura} × ${zona.area.altura}` : 'Ainda não delimitada na planta.'}</p>
            <div className="sim-form-actions"><button type="button" disabled={disabled} onClick={() => setTool({ kind: 'zona', alvo: zona.chave })}>{zona.area ? 'Redesenhar' : 'Delimitar no mapa'}</button>
              <button type="button" className="danger" disabled={disabled} onClick={() => removeZone(zona.chave)}>Remover zona</button></div>
            <button type="button" className="link-button" onClick={() => setSelection(null)}>← Visão geral</button>
          </div>
        })()}
        {selection?.kind === 'portal' && (() => {
          const portal = config.portais.find((p) => p.chave === selection.chave)
          if (!portal) return null
          const set = (mutate: (p: NonNullable<typeof portal>) => void) => update((d) => mutate(d.portais.find((p) => p.chave === portal.chave)!))
          return <div className="sim-form"><h3>Portal</h3>
            <label>Nome<input value={portal.nome} maxLength={120} disabled={disabled} onChange={(e) => set((p) => { p.nome = e.target.value })}/></label>
            <label>Zona do lado A<select value={portal.zona_a} disabled={disabled} onChange={(e) => update((d) => {
              d.portais.find((p) => p.chave === portal.chave)!.zona_a = e.target.value
              d.leitores.flatMap((l) => l.antenas).filter((a) => a.portal === portal.chave && a.lado === 'a').forEach((a) => { a.zona = e.target.value })
            })}>{config.zonas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}</option>)}</select></label>
            <label>Zona do lado B<select value={portal.zona_b} disabled={disabled} onChange={(e) => update((d) => {
              d.portais.find((p) => p.chave === portal.chave)!.zona_b = e.target.value
              d.leitores.flatMap((l) => l.antenas).filter((a) => a.portal === portal.chave && a.lado === 'b').forEach((a) => { a.zona = e.target.value })
            })}>{config.zonas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}</option>)}</select></label>
            {portal.zona_a === portal.zona_b && <small className="field-error">O portal precisa ligar duas zonas diferentes.</small>}
            <p className="muted-text">Antenas: {config.leitores.flatMap((l) => l.antenas.filter((a) => a.portal === portal.chave).map((a) => `${l.nome}/${a.nome} (${(a.lado ?? '?').toUpperCase()})`)).join(', ') || 'nenhuma'}</p>
            <div className="sim-form-actions"><button type="button" disabled={disabled} onClick={() => setTool({ kind: 'posicionar', alvo: 'portal', chave: portal.chave })}>{portal.posicao ? 'Reposicionar marcador' : 'Posicionar no mapa'}</button>
              <button type="button" className="danger" disabled={disabled} onClick={() => removePortal(portal.chave)}>Remover portal</button></div>
            <button type="button" className="link-button" onClick={() => setSelection(null)}>← Visão geral</button>
          </div>
        })()}
        {selection?.kind === 'leitor' && (() => {
          const leitor = config.leitores.find((l) => l.chave === selection.chave)
          if (!leitor) return null
          return <ReaderForm config={config} leitor={leitor} focus={selection.antena} disabled={disabled}
            onChange={(mutate) => update((d) => mutate(leitorDe(d, leitor.chave)))}
            onPosition={(alvo, chave) => setTool(alvo === 'leitor' ? { kind: 'posicionar', alvo, chave } : { kind: 'posicionar', alvo, chave, leitor: leitor.chave })}
            onRemove={() => { update((d) => { d.leitores = d.leitores.filter((l) => l.chave !== leitor.chave) }); setSelection(null) }}
            onBack={() => setSelection(null)} newKey={(prefixo) => novaChave(prefixo, todasAsChaves(config))}/>
        })()}
      </aside>
    </div>
  </div>
}

function Overview({ config, onSelect, onPlace }: { config: LayoutConfig; onSelect: (selection: Selection) => void; onPlace?: (leitor: LeitorLayout) => void }) {
  return <div className="sim-overview">
    {!config.portais.length && <ol className="sim-steps">
      <li><strong>Desenhe as zonas</strong> (salas, corredores) com “Desenhar zona”.</li>
      <li><strong>Crie um portal</strong> entre duas zonas: ele já vem com um leitor e as antenas A e B posicionadas.</li>
      <li><strong>Ajuste</strong> arrastando o que quiser e clique em “Salvar layout”.</li>
      <li><strong>Inicie a simulação</strong> e arraste os equipamentos na aba de controle.</li>
    </ol>}
    <h3>Zonas ({config.zonas.length})</h3>
    <ul>{config.zonas.map((zona) => <li key={zona.chave}><button type="button" className="link-button" onClick={() => onSelect({ kind: 'zona', chave: zona.chave })}><span className="sim-swatch" style={{ background: zona.cor }}/>{zona.nome}</button>{!zona.area && <span className="tag-chip tag-unknown">não delimitada</span>}</li>)}</ul>
    <h3>Portais ({config.portais.length})</h3>
    <ul>{config.portais.map((portal) => <li key={portal.chave}><button type="button" className="link-button" onClick={() => onSelect({ kind: 'portal', chave: portal.chave })}>{portal.nome}</button>{!portal.posicao && <span className="tag-chip tag-unknown">sem marcador</span>}</li>)}</ul>
    <h3>Leitores ({config.leitores.length})</h3>
    <ul>{config.leitores.map((leitor) => <li key={leitor.chave}><button type="button" className="link-button" onClick={() => onSelect({ kind: 'leitor', chave: leitor.chave })}>{leitor.nome} · {leitor.modelo === 'DR_MAX' ? 'DR Max' : 'EZ700'} · {leitor.antenas.length} antena(s)</button>
      {zonaRestritaDoLeitor(config, leitor) && <span className="tag-chip tag-restricted" title={`Detecta a entrada em ${zonaRestritaDoLeitor(config, leitor)!.nome}`}>zona restrita</span>}
      {(!leitor.posicao || leitor.antenas.some((a) => !a.posicao)) && (onPlace
        ? <button type="button" className="tag-chip tag-unknown sim-chip-action" title="Clique aqui e depois na planta" onClick={() => onPlace(leitor)}>posicionar</button>
        : <span className="tag-chip tag-unknown">posicionar</span>)}</li>)}</ul>
    <p className="muted-text">Os alcances são ilustrativos. Uma leitura isolada não muda a zona: a passagem é confirmada pelo motor de inferência quando a tag é lida dos dois lados de um portal.</p>
  </div>
}

function NewPortal({ config, disabled, onCreate }: { config: LayoutConfig; disabled: boolean; onCreate: (nome: string, a: string, b: string, comLeitor: boolean) => void }) {
  const [open, setOpen] = useState(false)
  const [comLeitor, setComLeitor] = useState(true)
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  if (!open) return <button type="button" disabled={disabled} onClick={() => { setOpen(true); setA(config.zonas[0]?.chave ?? ''); setB(config.zonas[1]?.chave ?? '') }}>Novo portal</button>
  const nome = (chave: string) => config.zonas.find((z) => z.chave === chave)?.nome ?? '?'
  return <span className="sim-new-portal">
    <select aria-label="Zona do lado A" value={a} onChange={(e) => setA(e.target.value)}>{config.zonas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}</option>)}</select>
    <span aria-hidden="true">↔</span>
    <select aria-label="Zona do lado B" value={b} onChange={(e) => setB(e.target.value)}>{config.zonas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}</option>)}</select>
    <label className="checkbox-label"><input type="checkbox" checked={comLeitor} onChange={(e) => setComLeitor(e.target.checked)}/> com leitor e antenas</label>
    <button type="button" className="admin-primary" disabled={!a || a === b} onClick={() => { onCreate(`${nome(a)} ↔ ${nome(b)}`, a, b, comLeitor); setOpen(false) }}>Criar portal</button>
    <button type="button" onClick={() => setOpen(false)}>Cancelar</button>
  </span>
}

function ReaderForm({ config, leitor, focus, disabled, onChange, onPosition, onRemove, onBack, newKey }: {
  config: LayoutConfig; leitor: LeitorLayout; focus?: string; disabled: boolean
  onChange: (mutate: (leitor: LeitorLayout) => void) => void
  onPosition: (alvo: 'leitor' | 'antena', chave: string) => void
  onRemove: () => void; onBack: () => void; newKey: (prefixo: string) => string
}) {
  const portasLivres = (atual: number) => [1, 2, 3, 4].filter((porta) => porta === atual || !leitor.antenas.some((a) => a.porta === porta))
  const setAntena = (chave: string, mutate: (antena: AntenaLayout) => void) => onChange((l) => mutate(l.antenas.find((a) => a.chave === chave)!))
  const restrita = zonaRestritaDoLeitor(config, leitor)
  return <div className="sim-form"><h3>Leitor virtual</h3>
    {restrita && <p className="sim-restricted-note" role="note"><strong>Leitor da zona restrita.</strong> As antenas dele ficam dentro de “{restrita.nome}”, uma em cada entrada, como lado B do portal. A tag lida no lado A e depois aqui confirma que o item entrou na área restrita. Não deixe as antenas no mesmo ponto.</p>}
    <label>Nome<input value={leitor.nome} maxLength={60} disabled={disabled} onChange={(e) => onChange((l) => { l.nome = e.target.value })}/></label>
    <label>Identificador lógico (MQTT)<input value={leitor.reader_id} maxLength={45} disabled={disabled} spellCheck={false} onChange={(e) => onChange((l) => { l.reader_id = e.target.value.toLowerCase() })}/>
      <small>Sempre com prefixo <code>sim-</code>: separa a fonte simulada dos leitores físicos.</small></label>
    <label>Modelo<select value={leitor.modelo} disabled={disabled} onChange={(e) => onChange((l) => { l.modelo = e.target.value as Modelo })}>{MODELOS.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}</select></label>
    {leitor.modelo === 'DR_MAX' && <small className="muted-text">DR Max existe apenas no ambiente simulado: a integração física ao MQTT ainda não foi validada.</small>}
    <div className="sim-form-actions"><button type="button" disabled={disabled} onClick={() => onPosition('leitor', leitor.chave)}>{leitor.posicao ? 'Reposicionar leitor' : 'Posicionar leitor'}</button></div>
    <h4>Antenas ({leitor.antenas.length}/{MAX_ANTENAS})</h4>
    {leitor.antenas.map((antena) => <fieldset key={antena.chave} className={`sim-antenna-form ${focus === antena.chave ? 'focused' : ''}`} disabled={disabled}>
      <legend>{antena.nome}</legend>
      <div className="sim-grid-2">
        <label>Nome<input value={antena.nome} maxLength={60} onChange={(e) => setAntena(antena.chave, (a) => { a.nome = e.target.value })}/></label>
        <label>Porta física<select value={antena.porta} onChange={(e) => setAntena(antena.chave, (a) => { a.porta = Number(e.target.value) })}>{portasLivres(antena.porta).map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
        <label>Portal<select value={antena.portal ?? ''} onChange={(e) => setAntena(antena.chave, (a) => {
          a.portal = e.target.value || null
          if (a.portal) { a.lado = a.lado ?? 'a'; const portal = config.portais.find((p) => p.chave === a.portal)!; a.zona = a.lado === 'a' ? portal.zona_a : portal.zona_b }
          else { a.lado = null; a.zona = a.zona ?? config.zonas[0]?.chave ?? null }
        })}><option value="">Sem portal</option>{config.portais.map((p) => <option key={p.chave} value={p.chave}>{p.nome}</option>)}</select></label>
        {antena.portal ? <label>Lado lógico<select value={antena.lado ?? 'a'} onChange={(e) => setAntena(antena.chave, (a) => {
          a.lado = e.target.value as 'a' | 'b'; const portal = config.portais.find((p) => p.chave === a.portal)!; a.zona = a.lado === 'a' ? portal.zona_a : portal.zona_b
        })}><option value="a">A — {config.zonas.find((z) => z.chave === config.portais.find((p) => p.chave === antena.portal)?.zona_a)?.nome}</option><option value="b">B — {config.zonas.find((z) => z.chave === config.portais.find((p) => p.chave === antena.portal)?.zona_b)?.nome}</option></select></label>
          : <label>Zona<select value={antena.zona ?? ''} onChange={(e) => setAntena(antena.chave, (a) => { a.zona = e.target.value })}>{config.zonas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}</option>)}</select></label>}
      </div>
      <label>Alcance ilustrativo: {antena.alcance}<input type="range" min={1} max={40} step={0.5} value={antena.alcance} onChange={(e) => setAntena(antena.chave, (a) => { a.alcance = Number(e.target.value) })}/></label>
      <div className="sim-form-actions"><button type="button" onClick={() => onPosition('antena', antena.chave)}>{antena.posicao ? 'Reposicionar' : 'Posicionar antena'}</button>
        <button type="button" className="danger" disabled={leitor.antenas.length <= 1} onClick={() => onChange((l) => { l.antenas = l.antenas.filter((a) => a.chave !== antena.chave) })}>Remover antena</button></div>
    </fieldset>)}
    <div className="sim-form-actions">
      <button type="button" disabled={disabled || leitor.antenas.length >= MAX_ANTENAS} onClick={() => onChange((l) => {
        const porta = [1, 2, 3, 4].find((p) => !l.antenas.some((a) => a.porta === p))!
        l.antenas.push({ chave: newKey(`${l.chave}-antena`), nome: `Antena ${porta}`, porta, posicao: null, alcance: 6, portal: null, lado: null, zona: config.zonas[0]?.chave ?? null })
      })}>Adicionar antena</button>
      <button type="button" className="danger" disabled={disabled} onClick={onRemove}>Remover leitor</button>
    </div>
    <button type="button" className="link-button" onClick={onBack}>← Visão geral</button>
  </div>
}
