import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import {
  ALCANCE_PADRAO, aplicarPadroesDeAntena, DIRECOES, FATOR_TRASEIRO_PADRAO, nomeDirecao, zoneAt, zonaRestritaDoLeitor,
  type AntenaLayout, type Area, type LayoutConfig, type LeitorLayout, type Modelo, type Ponto,
} from '../../services/simulacao'
import { linhasAntena, linhasLeitor, Marcador } from './Marcador'
import { pointFromEvent, PlanLegend, SimPlan } from './SimPlan'

type Selection = { kind: 'zona' | 'portal' | 'leitor'; chave: string; antena?: string } | null
type Tool = { kind: 'selecionar' } | { kind: 'zona'; alvo?: string } | { kind: 'leitor' } | { kind: 'posicionar'; alvo: 'leitor' | 'antena' | 'portal'; chave: string; leitor?: string }
type Borda = 'mover' | 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
type Drag = { grupo: string; original: LayoutConfig } & (
  | { kind: 'desenho'; inicio: Ponto; atual: Ponto; alvo?: string }
  | { kind: 'zona'; chave: string; borda: Borda; inicio: Ponto; area: Area }
  | { kind: 'leitor' | 'portal'; chave: string }
  | { kind: 'antena'; chave: string; leitor: string })

/** O pai agrupa no desfazer as mudanças com o mesmo `grupo` (um arraste = um passo). */
export type EditorChange = (config: LayoutConfig, grupo?: string) => void

const CORES = ['#2f6fb2', '#1f8a70', '#b26b2f', '#7a3fb2', '#c2413b', '#2a8a9a', '#8a7a1f']
const MODELOS: { id: Modelo; nome: string }[] = [{ id: 'EZ700', nome: 'Identix EZ700' }, { id: 'DR_MAX', nome: 'Identix DR Max (virtual)' }]
const BORDAS: Borda[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
/** Rosa dos ventos 3×3 na orientação da tela; null no centro = todas as direções. */
const GRADE_VISADA = [225, 270, 315, 180, null, 0, 135, 90, 45]
const MAX_ANTENAS = 4
const MIN_AREA = 2
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const round = (value: number) => Math.round(value * 10) / 10
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
const graus = (dx: number, dy: number) => Math.round(((Math.atan2(dy, dx) * 180) / Math.PI + 360) % 360)

function novaChave(prefixo: string, existentes: string[]) {
  let indice = existentes.length + 1
  while (existentes.includes(`${prefixo}-${indice}`)) indice++
  return `${prefixo}-${indice}`
}

function todasAsChaves(config: LayoutConfig) {
  return [...config.zonas.map((z) => z.chave), ...config.portais.map((p) => p.chave), ...config.leitores.map((l) => l.chave),
    ...config.leitores.flatMap((l) => l.antenas.map((a) => a.chave))]
}

function proximoReaderId(draft: LayoutConfig) {
  const ids = draft.leitores.map((l) => l.reader_id)
  let numero = draft.leitores.length + 1
  while (ids.includes(`sim-${draft.cenario}-${String(numero).padStart(2, '0')}`)) numero++
  return { numero, readerId: `sim-${draft.cenario}-${String(numero).padStart(2, '0')}` }
}

/** Nova área a partir da original e do deslocamento, pela borda/canto arrastado, sempre dentro da planta. */
export function redimensionar(area: Area, borda: Borda, dx: number, dy: number): Area {
  if (borda === 'mover') return { ...area, x: round(clamp(area.x + dx, 0, 100 - area.largura)), y: round(clamp(area.y + dy, 0, 100 - area.altura)) }
  let { x, y, largura, altura } = area
  if (borda.includes('w')) { x = clamp(area.x + dx, 0, area.x + area.largura - MIN_AREA); largura = area.x + area.largura - x }
  if (borda.includes('e')) largura = clamp(area.largura + dx, MIN_AREA, 100 - area.x)
  if (borda.includes('n')) { y = clamp(area.y + dy, 0, area.y + area.altura - MIN_AREA); altura = area.y + area.altura - y }
  if (borda.includes('s')) altura = clamp(area.altura + dy, MIN_AREA, 100 - area.y)
  return { x: round(x), y: round(y), largura: round(largura), altura: round(altura) }
}

/** Leitor de portal pronto: antena A dentro da zona A, B dentro da zona B, cada uma olhando para a própria zona. */
function leitorDoPortal(draft: LayoutConfig, portal: string, a: string, b: string): LeitorLayout {
  const chave = novaChave('leitor', todasAsChaves(draft))
  const { numero, readerId } = proximoReaderId(draft)
  const areaA = draft.zonas.find((z) => z.chave === a)?.area, areaB = draft.zonas.find((z) => z.chave === b)?.area
  let posicoes: { leitor: Ponto | null; a: Ponto | null; b: Ponto | null } = { leitor: null, a: null, b: null }
  let visadas = { a: 180, b: 0 }
  if (areaA && areaB) {
    // Escala de x (y dividido pela proporção), a mesma do cálculo de alcance.
    const p = draft.proporcao
    const ca = { x: areaA.x + areaA.largura / 2, y: (areaA.y + areaA.altura / 2) / p }
    const cb = { x: areaB.x + areaB.largura / 2, y: (areaB.y + areaB.altura / 2) / p }
    const mx = (ca.x + cb.x) / 2, my = (ca.y + cb.y) / 2
    const dist = Math.hypot(cb.x - ca.x, cb.y - ca.y) || 1
    const ux = (cb.x - ca.x) / dist, uy = (cb.y - ca.y) / dist
    const dentro = (x: number, y: number, area: Area) => ({
      x: round(clamp(x, area.x + 2, area.x + area.largura - 2)), y: round(clamp(y * p, area.y + 2, area.y + area.altura - 2)) })
    const passo = Math.min(6, dist / 2)
    posicoes = { a: dentro(mx - ux * passo, my - uy * passo, areaA), b: dentro(mx + ux * passo, my + uy * passo, areaB),
      leitor: { x: round(clamp(mx - uy * 5, 3, 97)), y: round(clamp((my + ux * 5) * p, 3, 97)) } }
    visadas = { a: graus(-ux, -uy), b: graus(ux, uy) }
  }
  const antena = (porta: number, lado: 'a' | 'b', posicao: Ponto | null, zona: string): AntenaLayout =>
    ({ chave: `${chave}-antena-${porta}`, nome: `Antena ${lado.toUpperCase()}`, porta, posicao, alcance: ALCANCE_PADRAO, orientacao: visadas[lado],
      fator_traseiro: FATOR_TRASEIRO_PADRAO, portal, lado, zona })
  return { chave, nome: `Leitor ${numero}`, reader_id: readerId, modelo: 'EZ700', posicao: posicoes.leitor,
    antenas: [antena(1, 'a', posicoes.a, a), antena(2, 'b', posicoes.b, b)] }
}

export function LayoutEditor({ config, onChange, disabled = false }: { config: LayoutConfig; onChange: EditorChange; disabled?: boolean }) {
  const planRef = useRef<HTMLDivElement>(null)
  const [selection, setSelection] = useState<Selection>(null)
  const [tool, setTool] = useState<Tool>({ kind: 'selecionar' })
  const [drag, setDrag] = useState<Drag | null>(null)
  const [aviso, setAviso] = useState('')
  const [ver, setVer] = useState({ cobertura: true, cabos: false, nomes: false })

  const update = (mutate: (draft: LayoutConfig) => void, grupo?: string) => { const draft = clone(config); mutate(draft); onChange(draft, grupo) }
  const leitorDe = (draft: LayoutConfig, chave: string) => draft.leitores.find((l) => l.chave === chave)!

  function capture(event: ReactPointerEvent) {
    try { planRef.current?.setPointerCapture(event.pointerId) } catch { /* jsdom */ }
  }
  const novoGrupo = () => `arraste-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`

  function onPlanDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (disabled) return
    const ponto = pointFromEvent(planRef.current, event)
    if (tool.kind === 'zona') { capture(event); setDrag({ kind: 'desenho', inicio: ponto, atual: ponto, alvo: tool.alvo, grupo: novoGrupo(), original: config }); return }
    if (tool.kind === 'leitor') {
      update((draft) => {
        const chaves = todasAsChaves(draft)
        const chave = novaChave('leitor', chaves)
        const { numero, readerId } = proximoReaderId(draft)
        const zona = zoneAt(draft, ponto)?.chave ?? draft.zonas[0]?.chave ?? null
        draft.leitores.push({ chave, nome: `Leitor ${numero}`, reader_id: readerId, modelo: 'EZ700', posicao: ponto,
          antenas: [{ chave: novaChave(`${chave}-antena`, chaves), nome: 'Antena 1', porta: 1, posicao: { x: clamp(ponto.x + 3, 0, 100), y: ponto.y },
            alcance: ALCANCE_PADRAO, orientacao: 0, fator_traseiro: FATOR_TRASEIRO_PADRAO, portal: null, lado: null, zona }] })
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
    // Clique dentro de áreas: seleciona a MENOR que contém o ponto (sobreposição não bloqueia as outras).
    const candidatas = config.zonas.filter((z) => z.area && ponto.x >= z.area.x && ponto.x <= z.area.x + z.area.largura && ponto.y >= z.area.y && ponto.y <= z.area.y + z.area.altura)
      .sort((a, b) => a.area!.largura * a.area!.altura - b.area!.largura * b.area!.altura)
    const zona = candidatas.find((z) => z.chave === selection?.chave) ?? candidatas[0]
    if (zona) {
      setSelection({ kind: 'zona', chave: zona.chave })
      if (zona.chave === selection?.chave) { capture(event); setDrag({ kind: 'zona', chave: zona.chave, borda: 'mover', inicio: ponto, area: zona.area!, grupo: novoGrupo(), original: config }) }
      return
    }
    setSelection(null)
  }

  function onPlanMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag) return
    const ponto = pointFromEvent(planRef.current, event)
    if (drag.kind === 'desenho') { setDrag({ ...drag, atual: ponto }); return }
    update((draft) => {
      if (drag.kind === 'zona') draft.zonas.find((z) => z.chave === drag.chave)!.area = redimensionar(drag.area, drag.borda, ponto.x - drag.inicio.x, ponto.y - drag.inicio.y)
      else if (drag.kind === 'leitor') leitorDe(draft, drag.chave).posicao = ponto
      else if (drag.kind === 'portal') draft.portais.find((p) => p.chave === drag.chave)!.posicao = ponto
      else if (drag.kind === 'antena') leitorDe(draft, drag.leitor).antenas.find((a) => a.chave === drag.chave)!.posicao = ponto
    }, drag.grupo)
  }

  function onPlanUp() {
    if (drag?.kind === 'desenho') {
      const x = Math.min(drag.inicio.x, drag.atual.x), y = Math.min(drag.inicio.y, drag.atual.y)
      const largura = round(Math.abs(drag.atual.x - drag.inicio.x)), altura = round(Math.abs(drag.atual.y - drag.inicio.y))
      if (largura >= MIN_AREA && altura >= MIN_AREA) {
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
    : tool.kind === 'posicionar' ? `Clique na planta onde fica: ${alvoPosicionar ?? 'o elemento'} (Esc cancela).`
      : 'Clique numa área para selecioná-la; arraste-a ou puxe as bordas. Passe o mouse nos pontos para ver os detalhes. Delete remove, Esc cancela.'
  const selecionada = selection?.kind === 'zona' ? config.zonas.find((z) => z.chave === selection.chave) : undefined
  const antigas = config.leitores.some((l) => l.antenas.some((a) => a.orientacao === null || a.orientacao === undefined))

  return <div className="sim-editor" onKeyDown={(event) => {
    if ((event.target as HTMLElement).closest('input, select, textarea')) return
    if (event.key === 'Escape') {
      if (drag && drag.kind !== 'desenho') onChange(drag.original, drag.grupo)  // cancela o arraste
      setDrag(null); setTool({ kind: 'selecionar' }); if (!drag) setSelection(null)
    }
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
      <span className="sim-view-toggles" role="group" aria-label="Mostrar na planta">
        <label className="checkbox-label"><input type="checkbox" checked={ver.cobertura} onChange={(e) => setVer({ ...ver, cobertura: e.target.checked })}/> Cobertura</label>
        <label className="checkbox-label"><input type="checkbox" checked={ver.cabos} onChange={(e) => setVer({ ...ver, cabos: e.target.checked })}/> Cabos</label>
        <label className="checkbox-label"><input type="checkbox" checked={ver.nomes} onChange={(e) => setVer({ ...ver, nomes: e.target.checked })}/> Nomes</label>
      </span>
    </div>
    <p className="sim-hint" role="status">{dica}</p>
    {aviso && <p className="admin-warning" role="alert" onClick={() => setAviso('')}>{aviso}</p>}
    <div className="sim-editor-body">
      <div>
        <SimPlan ref={planRef} layout={config} label="Planta editável da simulação" className={`sim-plan-editor tool-${tool.kind}`}
          options={{ selected: selection?.chave, showCoverage: ver.cobertura, showCables: ver.cabos }}
          onPointerDown={onPlanDown} onPointerMove={onPlanMove} onPointerUp={onPlanUp}>
          {selecionada?.area && <div className="sim-zone-edit" style={{ left: `${selecionada.area.x}%`, top: `${selecionada.area.y}%`, width: `${selecionada.area.largura}%`, height: `${selecionada.area.altura}%` }}>
            {!disabled && BORDAS.map((borda) => <span key={borda} className={`sim-handle sim-handle-${borda}`} aria-label={`Redimensionar ${selecionada.nome} (${borda})`}
              onPointerDown={(e) => startDrag(e, { kind: 'zona', chave: selecionada.chave, borda, inicio: pointFromEvent(planRef.current, e), area: selecionada.area!, grupo: novoGrupo(), original: config }, { kind: 'zona', chave: selecionada.chave })}/>)}
          </div>}
          {desenho && <div className="sim-drawing" style={{ left: `${desenho.x}%`, top: `${desenho.y}%`, width: `${desenho.w}%`, height: `${desenho.h}%` }}/>}
          {config.portais.map((portal) => portal.posicao && <Marcador key={portal.chave} tipo="portal" posicao={portal.posicao} titulo={`Portal ${portal.nome}`}
            linhas={[`Entre ${config.zonas.find((z) => z.chave === portal.zona_a)?.nome ?? '?'} (lado A) e ${config.zonas.find((z) => z.chave === portal.zona_b)?.nome ?? '?'} (lado B)`]}
            rotulo={ver.nomes ? portal.nome : null} selecionado={selection?.chave === portal.chave}
            onPointerDown={(e) => startDrag(e, { kind: 'portal', chave: portal.chave, grupo: novoGrupo(), original: config }, { kind: 'portal', chave: portal.chave })}/>)}
          {config.leitores.map((leitor) => <div key={leitor.chave}>
            {leitor.posicao && <Marcador tipo="leitor" posicao={leitor.posicao} titulo={leitor.nome} linhas={linhasLeitor(leitor)} rotulo={ver.nomes ? leitor.nome : null}
              restrito={!!leitor.alerta_area_restrita || !!zonaRestritaDoLeitor(config, leitor)} selecionado={selection?.chave === leitor.chave && !selection.antena}
              onPointerDown={(e) => startDrag(e, { kind: 'leitor', chave: leitor.chave, grupo: novoGrupo(), original: config }, { kind: 'leitor', chave: leitor.chave })}/>}
            {leitor.antenas.map((antena) => antena.posicao && <Marcador key={antena.chave} tipo="antena" posicao={antena.posicao} titulo={antena.nome}
              linhas={linhasAntena(leitor, antena, config.portais)} rotulo={ver.nomes ? `${antena.nome}${antena.lado ? ` · ${antena.lado.toUpperCase()}` : ''}` : null}
              orientacao={antena.orientacao} selecionado={selection?.antena === antena.chave}
              onPointerDown={(e) => startDrag(e, { kind: 'antena', chave: antena.chave, leitor: leitor.chave, grupo: novoGrupo(), original: config }, { kind: 'leitor', chave: leitor.chave, antena: antena.chave })}/>)}
          </div>)}
        </SimPlan>
        {config.cenario === 'hupaa' && <PlanLegend/>}
      </div>
      <aside className="sim-side panel" aria-label="Propriedades">
        {!selection && <Overview config={config} onSelect={setSelection} onPlace={disabled ? undefined : placeMissing}
          onDefaults={disabled || !antigas ? undefined : () => update((draft) => { Object.assign(draft, aplicarPadroesDeAntena(draft)) })}/>}
        {selection?.kind === 'zona' && (() => {
          const zona = config.zonas.find((z) => z.chave === selection.chave)
          if (!zona) return null
          const setArea = (campo: keyof Area, valor: number) => update((d) => {
            const alvo = d.zonas.find((z) => z.chave === zona.chave)!
            if (!alvo.area || Number.isNaN(valor)) return
            const area = { ...alvo.area, [campo]: valor }
            area.largura = clamp(area.largura, MIN_AREA, 100); area.altura = clamp(area.altura, MIN_AREA, 100)
            area.x = clamp(area.x, 0, 100 - area.largura); area.y = clamp(area.y, 0, 100 - area.altura)
            alvo.area = { x: round(area.x), y: round(area.y), largura: round(area.largura), altura: round(area.altura) }
          }, `numero-${zona.chave}-${campo}`)
          return <div className="sim-form"><h3>Zona</h3>
            <label>Nome<input value={zona.nome} maxLength={80} disabled={disabled} onChange={(e) => update((d) => { d.zonas.find((z) => z.chave === zona.chave)!.nome = e.target.value }, `nome-${zona.chave}`)}/></label>
            <label>Cor do contorno<input type="color" value={zona.cor} disabled={disabled} onChange={(e) => update((d) => { d.zonas.find((z) => z.chave === zona.chave)!.cor = e.target.value }, `cor-${zona.chave}`)}/></label>
            <label className="checkbox-label"><input type="checkbox" checked={zona.restrita} disabled={disabled} onChange={(e) => update((d) => { d.zonas.find((z) => z.chave === zona.chave)!.restrita = e.target.checked })}/> Área restrita (você decide qual circulação vertical é a escada)</label>
            {zona.restrita && <label>Portal de zona restrita (leitor)<select value={config.leitores.find((l) => l.alerta_area_restrita && l.antenas.some((a) => a.zona === zona.chave))?.chave ?? ''} disabled={disabled}
              onChange={(e) => update((d) => {
                // Um leitor só vigia a zona restrita: todas as antenas dele passam a ler presença nela
                // (sem portal); uma antena basta e as demais são opcionais. Os outros deixam de alertar.
                for (const leitor of d.leitores) {
                  const escolhido = leitor.chave === e.target.value
                  if (escolhido) { leitor.alerta_area_restrita = true; leitor.antenas.forEach((a) => { a.portal = null; a.lado = null; a.zona = zona.chave }) }
                  else if (leitor.alerta_area_restrita && leitor.antenas.some((a) => a.zona === zona.chave)) leitor.alerta_area_restrita = false
                }
              })}><option value="">Nenhum</option>{config.leitores.map((l) => <option key={l.chave} value={l.chave}>{l.nome} ({l.antenas.length} antena{l.antenas.length === 1 ? '' : 's'})</option>)}</select>
              <small>Qualquer leitor serve; uma antena basta (a segunda é opcional). Com uma antena ele não é portal de passagem: é o portal de zona restrita, e uma leitura gravada nele avisa a entrada.</small></label>}
            {zona.area ? <fieldset className="sim-area-fields" disabled={disabled}><legend>Posição e tamanho (0–100)</legend>
              {(['x', 'y', 'largura', 'altura'] as const).map((campo) => <label key={campo}>{campo === 'x' ? 'Esquerda' : campo === 'y' ? 'Topo' : campo === 'largura' ? 'Largura' : 'Altura'}
                <input type="number" step={0.5} min={0} max={100} value={zona.area![campo]} onChange={(e) => setArea(campo, Number(e.target.value))}/></label>)}
            </fieldset> : <p className="muted-text">Ainda não delimitada na planta.</p>}
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
            <p className="sim-portal-regra" role="note">{config.leitores.some((l) => new Set(l.antenas.filter((a) => a.portal === portal.chave).map((a) => a.lado)).size === 2)
              ? 'Portal completo: um leitor com pelo menos duas antenas, uma de cada lado.'
              : 'Ainda não conta como portal: um portal é um leitor com pelo menos duas antenas, uma de cada lado. (Leitor com uma antena só é portal de zona restrita.)'}</p>
            <div className="sim-form-actions"><button type="button" disabled={disabled} onClick={() => setTool({ kind: 'posicionar', alvo: 'portal', chave: portal.chave })}>{portal.posicao ? 'Reposicionar marcador' : 'Posicionar no mapa'}</button>
              <button type="button" className="danger" disabled={disabled} onClick={() => removePortal(portal.chave)}>Remover portal</button></div>
            <button type="button" className="link-button" onClick={() => setSelection(null)}>← Visão geral</button>
          </div>
        })()}
        {selection?.kind === 'leitor' && (() => {
          const leitor = config.leitores.find((l) => l.chave === selection.chave)
          if (!leitor) return null
          return <ReaderForm config={config} leitor={leitor} focus={selection.antena} disabled={disabled}
            onChange={(mutate, grupo) => update((d) => mutate(leitorDe(d, leitor.chave)), grupo)}
            onPosition={(alvo, chave) => setTool(alvo === 'leitor' ? { kind: 'posicionar', alvo, chave } : { kind: 'posicionar', alvo, chave, leitor: leitor.chave })}
            onRemove={() => { update((d) => { d.leitores = d.leitores.filter((l) => l.chave !== leitor.chave) }); setSelection(null) }}
            onBack={() => setSelection(null)} newKey={(prefixo) => novaChave(prefixo, todasAsChaves(config))}/>
        })()}
      </aside>
    </div>
  </div>
}

function Overview({ config, onSelect, onPlace, onDefaults }: { config: LayoutConfig; onSelect: (selection: Selection) => void; onPlace?: (leitor: LeitorLayout) => void; onDefaults?: () => void }) {
  return <div className="sim-overview">
    {!config.portais.length && <ol className="sim-steps">
      <li><strong>Desenhe as zonas</strong> (salas, corredores) com “Desenhar zona”.</li>
      <li><strong>Crie um portal</strong> entre duas zonas: ele já vem com um leitor e as antenas A e B, cada uma olhando para a própria zona.</li>
      <li><strong>Ajuste</strong> posições e a visada das antenas e clique em “Salvar layout”.</li>
      <li><strong>Inicie a simulação</strong> e arraste os equipamentos na aba de controle.</li>
    </ol>}
    {onDefaults && <div className="sim-defaults" role="note"><p>Este layout tem antenas sem visada (círculo do formato antigo).</p>
      <button type="button" onClick={onDefaults}>Aplicar novos padrões de antena</button>
      <small>Cada antena passa a olhar para o centro da própria zona, com traseira curta e alcance até {config.cenario === 'easy' ? 11 : ALCANCE_PADRAO}. Posições e portais não mudam; dá para desfazer.</small></div>}
    <h3>Zonas ({config.zonas.length})</h3>
    <ul>{config.zonas.map((zona) => <li key={zona.chave}><button type="button" className="link-button" onClick={() => onSelect({ kind: 'zona', chave: zona.chave })}><span className="sim-swatch" style={{ borderColor: zona.cor }}/>{zona.nome}</button>
      {zona.restrita && <span className="tag-chip tag-restricted">restrita</span>}{!zona.area && <span className="tag-chip tag-unknown">não delimitada</span>}</li>)}</ul>
    <h3>Portais ({config.portais.length})</h3>
    <ul>{config.portais.map((portal) => <li key={portal.chave}><button type="button" className="link-button" onClick={() => onSelect({ kind: 'portal', chave: portal.chave })}>{portal.nome}</button>{!portal.posicao && <span className="tag-chip tag-unknown">sem marcador</span>}</li>)}</ul>
    <h3>Leitores ({config.leitores.length})</h3>
    <ul>{config.leitores.map((leitor) => <li key={leitor.chave}><button type="button" className="link-button" onClick={() => onSelect({ kind: 'leitor', chave: leitor.chave })}>{leitor.nome} · {leitor.modelo === 'DR_MAX' ? 'DR Max' : 'EZ700'} · {leitor.antenas.length} antena(s)</button>
      {(leitor.alerta_area_restrita || zonaRestritaDoLeitor(config, leitor)) && <span className="tag-chip tag-restricted" title="Leitor de uma antena que detecta a presença na zona restrita">portal de zona restrita</span>}
      {(!leitor.posicao || leitor.antenas.some((a) => !a.posicao)) && (onPlace
        ? <button type="button" className="tag-chip tag-unknown sim-chip-action" title="Clique aqui e depois na planta" onClick={() => onPlace(leitor)}>posicionar</button>
        : <span className="tag-chip tag-unknown">posicionar</span>)}</li>)}</ul>
    <p className="muted-text">Alcances ilustrativos. A visada direta lê mais longe; atrás, bem menos. Uma leitura isolada não muda a zona: a passagem é confirmada quando a tag é lida dos dois lados de um portal.</p>
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
    <span>e</span>
    <select aria-label="Zona do lado B" value={b} onChange={(e) => setB(e.target.value)}>{config.zonas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}</option>)}</select>
    <label className="checkbox-label"><input type="checkbox" checked={comLeitor} onChange={(e) => setComLeitor(e.target.checked)}/> com leitor e antenas</label>
    <button type="button" className="admin-primary" disabled={!a || a === b} onClick={() => { onCreate(`${nome(a)} ↔ ${nome(b)}`, a, b, comLeitor); setOpen(false) }}>Criar portal</button>
    <button type="button" onClick={() => setOpen(false)}>Cancelar</button>
  </span>
}

/** Rosa dos ventos: 8 direções + ângulo livre + "todas" (omnidirecional, formato antigo). */
function Visada({ antena, onChange }: { antena: AntenaLayout; onChange: (mutate: (antena: AntenaLayout) => void, grupo?: string) => void }) {
  const atual = antena.orientacao
  const apontar = (valor: number) => (a: AntenaLayout) => { a.orientacao = valor; a.fator_traseiro = a.fator_traseiro ?? FATOR_TRASEIRO_PADRAO }
  return <fieldset className="sim-visada"><legend>Visada direta: {nomeDirecao(atual)}</legend>
    <div className="sim-compass" role="group" aria-label="Direção da visada">
      {GRADE_VISADA.map((valor) => {
        if (valor === null) return <button key="omni" type="button" className="sim-compass-center" aria-pressed={atual === null || atual === undefined}
          aria-label="Todas as direções (sem visada)" title="Todas as direções (sem visada)" onClick={() => onChange((a) => { a.orientacao = null })}>•</button>
        const direcao = DIRECOES.find((d) => d.graus === valor)!
        return <button key={valor} type="button" aria-pressed={atual === valor} aria-label={`Visada ${direcao.nome.toLowerCase()} (${valor}°)`}
          title={`${direcao.nome} (${valor}°)`} onClick={() => onChange(apontar(valor))}>{direcao.seta}</button>
      })}
    </div>
    <label>Ângulo livre (0° direita · 90° baixo · 180° esquerda · 270° cima)
      <span className="sim-range-row"><input type="range" min={0} max={359} step={1} value={atual ?? 0} onChange={(e) => onChange(apontar(Number(e.target.value)), `angulo-${antena.chave}`)}/>
        <input type="number" min={0} max={360} step={1} aria-label="Ângulo em graus" value={atual ?? ''} placeholder="todas"
          onChange={(e) => onChange(e.target.value === '' ? (a) => { a.orientacao = null } : apontar(Number(e.target.value) % 360), `angulo-${antena.chave}`)}/></span></label>
    {atual !== null && atual !== undefined && <label>Alcance atrás: {Math.round((antena.fator_traseiro ?? FATOR_TRASEIRO_PADRAO) * 100)}% da frente
      <input type="range" min={0.1} max={1} step={0.05} value={antena.fator_traseiro ?? FATOR_TRASEIRO_PADRAO} onChange={(e) => onChange((a) => { a.fator_traseiro = Number(e.target.value) }, `fator-${antena.chave}`)}/></label>}
  </fieldset>
}

function ReaderForm({ config, leitor, focus, disabled, onChange, onPosition, onRemove, onBack, newKey }: {
  config: LayoutConfig; leitor: LeitorLayout; focus?: string; disabled: boolean
  onChange: (mutate: (leitor: LeitorLayout) => void, grupo?: string) => void
  onPosition: (alvo: 'leitor' | 'antena', chave: string) => void
  onRemove: () => void; onBack: () => void; newKey: (prefixo: string) => string
}) {
  const portasLivres = (atual: number) => [1, 2, 3, 4].filter((porta) => porta === atual || !leitor.antenas.some((a) => a.porta === porta))
  const setAntena = (chave: string, mutate: (antena: AntenaLayout) => void, grupo?: string) => onChange((l) => mutate(l.antenas.find((a) => a.chave === chave)!), grupo)
  const restrita = zonaRestritaDoLeitor(config, leitor)
  const zonasOrdenadas = [...config.zonas].sort((a, b) => Number(b.restrita) - Number(a.restrita))
  return <div className="sim-form"><h3>Leitor virtual</h3>
    <label>Nome<input value={leitor.nome} maxLength={60} disabled={disabled} onChange={(e) => onChange((l) => { l.nome = e.target.value }, `nome-${leitor.chave}`)}/></label>
    <label>Identificador lógico (MQTT)<input value={leitor.reader_id} maxLength={45} disabled={disabled} spellCheck={false} onChange={(e) => onChange((l) => { l.reader_id = e.target.value.toLowerCase() }, `id-${leitor.chave}`)}/>
      <small>Sempre com prefixo <code>sim-</code>: separa a fonte simulada dos leitores físicos.</small></label>
    <label>Modelo<select value={leitor.modelo} disabled={disabled} onChange={(e) => onChange((l) => { l.modelo = e.target.value as Modelo })}>{MODELOS.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}</select></label>
    {leitor.modelo === 'DR_MAX' && <small className="muted-text">DR Max existe apenas no ambiente simulado: a integração física ao MQTT ainda não foi validada.</small>}
    <label className="checkbox-label"><input type="checkbox" checked={!!leitor.alerta_area_restrita} disabled={disabled} onChange={(e) => onChange((l) => {
      l.alerta_area_restrita = e.target.checked
      const zona = config.zonas.find((z) => z.restrita)?.chave
      if (e.target.checked && zona) l.antenas.forEach((a) => { if (!a.portal) a.zona = zona })
    })}/> Portal de zona restrita (uma antena basta)</label>
    {(leitor.alerta_area_restrita || restrita) && <p className="sim-restricted-note" role="note"><strong>Portal de zona restrita.</strong> {leitor.alerta_area_restrita
      ? 'Cada leitura gravada pelo sistema numa antena dele vira alerta, sem precisar de lado A nem de passagem. A antena fica dentro da zona monitorada, sem portal.'
      : `Ele detecta a entrada em “${restrita!.nome}” pelos portais (lado B). Marque “Portal de zona restrita” para avisar já na primeira leitura.`}</p>}
    <div className="sim-form-actions"><button type="button" disabled={disabled} onClick={() => onPosition('leitor', leitor.chave)}>{leitor.posicao ? 'Reposicionar leitor' : 'Posicionar leitor'}</button></div>
    <h4>Antenas ({leitor.antenas.length}/{MAX_ANTENAS})</h4>
    {leitor.antenas.map((antena) => <fieldset key={antena.chave} className={`sim-antenna-form ${focus === antena.chave ? 'focused' : ''}`} disabled={disabled}>
      <legend>{antena.nome}</legend>
      <div className="sim-grid-2">
        <label>Nome<input value={antena.nome} maxLength={60} onChange={(e) => setAntena(antena.chave, (a) => { a.nome = e.target.value }, `nome-${antena.chave}`)}/></label>
        <label>Porta física<select value={antena.porta} onChange={(e) => setAntena(antena.chave, (a) => { a.porta = Number(e.target.value) })}>{portasLivres(antena.porta).map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
        <label>Portal<select value={antena.portal ?? ''} onChange={(e) => setAntena(antena.chave, (a) => {
          a.portal = e.target.value || null
          if (a.portal) { a.lado = a.lado ?? 'a'; const portal = config.portais.find((p) => p.chave === a.portal)!; a.zona = a.lado === 'a' ? portal.zona_a : portal.zona_b }
          else { a.lado = null; a.zona = a.zona ?? config.zonas[0]?.chave ?? null }
        })}><option value="">{leitor.alerta_area_restrita ? 'Sem portal (presença)' : 'Sem portal'}</option>{config.portais.map((p) => <option key={p.chave} value={p.chave}>{p.nome}</option>)}</select></label>
        {antena.portal ? <label>Lado lógico<select value={antena.lado ?? 'a'} onChange={(e) => setAntena(antena.chave, (a) => {
          a.lado = e.target.value as 'a' | 'b'; const portal = config.portais.find((p) => p.chave === a.portal)!; a.zona = a.lado === 'a' ? portal.zona_a : portal.zona_b
        })}><option value="a">A — {config.zonas.find((z) => z.chave === config.portais.find((p) => p.chave === antena.portal)?.zona_a)?.nome}</option><option value="b">B — {config.zonas.find((z) => z.chave === config.portais.find((p) => p.chave === antena.portal)?.zona_b)?.nome}</option></select></label>
          : <label>{leitor.alerta_area_restrita ? 'Zona monitorada' : 'Zona'}<select value={antena.zona ?? ''} onChange={(e) => setAntena(antena.chave, (a) => { a.zona = e.target.value })}>{zonasOrdenadas.map((z) => <option key={z.chave} value={z.chave}>{z.nome}{z.restrita ? ' (restrita)' : ''}</option>)}</select></label>}
      </div>
      <label>Alcance na frente: {antena.alcance}<input type="range" min={1} max={config.cenario === 'easy' ? 20 : 12} step={0.5} value={antena.alcance} onChange={(e) => setAntena(antena.chave, (a) => { a.alcance = Number(e.target.value) }, `alcance-${antena.chave}`)}/></label>
      <Visada antena={antena} onChange={(mutate, grupo) => setAntena(antena.chave, mutate, grupo)}/>
      <div className="sim-form-actions"><button type="button" onClick={() => onPosition('antena', antena.chave)}>{antena.posicao ? 'Reposicionar' : 'Posicionar antena'}</button>
        <button type="button" className="danger" disabled={leitor.antenas.length <= 1} onClick={() => onChange((l) => { l.antenas = l.antenas.filter((a) => a.chave !== antena.chave) })}>Remover antena</button></div>
    </fieldset>)}
    <div className="sim-form-actions">
      <button type="button" disabled={disabled || leitor.antenas.length >= MAX_ANTENAS} onClick={() => onChange((l) => {
        const porta = [1, 2, 3, 4].find((p) => !l.antenas.some((a) => a.porta === p))!
        const zona = (l.alerta_area_restrita ? config.zonas.find((z) => z.restrita)?.chave : undefined) ?? config.zonas[0]?.chave ?? null
        l.antenas.push({ chave: newKey(`${l.chave}-antena`), nome: `Antena ${porta}`, porta, posicao: null, alcance: ALCANCE_PADRAO, orientacao: 0, fator_traseiro: FATOR_TRASEIRO_PADRAO, portal: null, lado: null, zona })
      })}>Adicionar antena</button>
      <button type="button" className="danger" disabled={disabled} onClick={onRemove}>Remover leitor</button>
    </div>
    <button type="button" className="link-button" onClick={onBack}>← Visão geral</button>
  </div>
}
