import { useCallback, useEffect, useState } from 'react'
import { ageLabel } from '../components/DashboardParts'
import { Icon } from '../components/layout/Icon'
import { LayoutEditor } from '../components/simulador/LayoutEditor'
import { SimPlan } from '../components/simulador/SimPlan'
import { errorMessage } from '../services/api'
import { useLiveQuery, useLiveRefresh } from '../services/live'
import {
  archiveLayout, controlUrl, createLayout, getLayouts, getMonitor, getSessions, getSimConfig, pendencias, quickTest, restorePreset, saveLayout, sessionAction, startSession, wipeScenario,
  type Cenario, type LayoutConfig, type LayoutResumo, type Monitor, type SessaoResumo,
} from '../services/simulacao'

const CENARIOS: { id: Cenario; nome: string; descricao: string }[] = [
  { id: 'easy', nome: 'Laboratório EASY', descricao: 'Duas salas, duas zonas, um portal e duas antenas — testes simples e validação do pipeline.' },
  { id: 'hupaa', nome: 'Hospital HUPAA', descricao: 'Planta de referência do 2º pavimento com leitores EZ700 e DR Max virtuais — demonstrações completas.' },
]

const ESTADO: Record<string, string> = { em_execucao: 'Em execução', pausada: 'Pausada', encerrada: 'Encerrada' }

function initialScenario(): Cenario {
  return new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('cenario') === 'hupaa' ? 'hupaa' : 'easy'
}

export function SimulatorPage({ canEdit }: { canEdit: boolean }) {
  const [cenario, setCenario] = useState<Cenario>(initialScenario)
  const [layouts, setLayouts] = useState<LayoutResumo[] | null>(null)
  const [layoutId, setLayoutId] = useState<number | null>(null)
  const [draft, setDraft] = useState<LayoutConfig | null>(null)
  const [name, setName] = useState('')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [view, setView] = useState<'config' | 'monitor'>('config')
  const [history, setHistory] = useState<LayoutConfig[]>([])
  const config = useLiveQuery('sim:config', getSimConfig)
  const { refresh } = useLiveRefresh()
  const sessions = useLiveQuery('sim:sessions', getSessions)
  const current = layouts?.find((layout) => layout.id === layoutId) ?? null
  const session: SessaoResumo | undefined = sessions.data?.find((item) => item.layout_id === layoutId)

  const load = useCallback(async (keep?: number) => {
    setError('')
    try {
      const items = await getLayouts(cenario)
      setLayouts(items)
      const chosen = items.find((item) => item.id === keep) ?? items[0] ?? null
      setLayoutId(chosen?.id ?? null); setDraft(chosen ? chosen.configuracao : null); setName(chosen?.nome ?? ''); setDirty(false); setHistory([])
    } catch (failure) { setError(errorMessage(failure)); setLayouts([]) }
  }, [cenario])
  useEffect(() => { setLayouts(null); void load() }, [load])

  function choose(id: number) {
    const chosen = layouts?.find((item) => item.id === id)
    if (!chosen) return
    if (dirty && !window.confirm('Descartar as alterações não salvas?')) return
    setLayoutId(id); setDraft(chosen.configuracao); setName(chosen.nome); setDirty(false); setNotice(''); setHistory([])
  }

  function edit(next: LayoutConfig) {
    if (draft) setHistory((old) => [...old.slice(-49), draft])
    setDraft(next); setDirty(true)
  }
  function undo() {
    const previous = history.at(-1)
    if (!previous) return
    setHistory((old) => old.slice(0, -1)); setDraft(previous); setDirty(true)
  }
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !(event.target as HTMLElement).closest('input, textarea')) { event.preventDefault(); undo() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (failure) { setError(errorMessage(failure)) } finally { setBusy(false) }
  }

  const create = () => run(async () => { const created = await createLayout(cenario); await load(created.id); setNotice('Layout criado a partir da configuração predefinida.') })
  const save = () => run(async () => {
    if (!current || !draft) return
    const saved = await saveLayout(current.id, name, draft, current.versao)
    setLayouts((items) => items?.map((item) => item.id === saved.id ? saved : item) ?? null)
    setDraft(saved.configuracao); setDirty(false)
    setNotice(session ? 'Layout salvo. Use “Reiniciar” para a simulação em andamento passar a usá-lo.' : 'Layout salvo.')
  })
  const restore = () => run(async () => {
    if (!current || !window.confirm('Restaurar a configuração predefinida deste cenário? As posições ajustadas serão perdidas.')) return
    const saved = await restorePreset(current.id)
    setLayouts((items) => items?.map((item) => item.id === saved.id ? saved : item) ?? null)
    setDraft(saved.configuracao); setDirty(false); setNotice('Configuração predefinida restaurada.')
  })
  const archive = () => run(async () => {
    if (!current || !window.confirm(`Excluir o layout “${current.nome}”? Ele sai da lista (o histórico do pipeline fica).`)) return
    await archiveLayout(current.id); await load(); setNotice('Layout excluído.')
  })
  const quick = () => run(async () => {
    if (dirty && !window.confirm('Descartar as alterações não salvas?')) return
    const started = await quickTest(cenario)
    await load(started.layout_id); refresh(); setView('monitor')
    setNotice('Teste rápido pronto: layout, leitores e quatro equipamentos na planta. Na aba de controle, arraste a “Maca 01” pelo portal.')
    window.open(controlUrl(started.codigo), '_blank', 'noopener')
  })
  const wipe = () => run(async () => {
    const nome = CENARIOS.find((item) => item.id === cenario)!.nome
    if (!window.confirm(`Apagar tudo do ${nome}? Encerra as simulações abertas e exclui todos os layouts deste cenário. Leituras e histórico já gravados pelo pipeline não são apagados.`)) return
    const result = await wipeScenario(cenario)
    refresh(); setView('config'); await load()
    setNotice(`Tudo apagado: ${result.layouts_arquivados} layout(s) excluído(s), ${result.sessoes_encerradas} simulação(ões) encerrada(s).`)
  })
  const start = () => run(async () => {
    if (!current || !draft) return
    if (dirty) {
      const saved = await saveLayout(current.id, name, draft, current.versao)
      setLayouts((items) => items?.map((item) => item.id === saved.id ? saved : item) ?? null); setDirty(false)
    }
    const started = await startSession(current.id)
    refresh()
    setView('monitor')
    setNotice('Simulação iniciada. Abra o controle em outra aba para movimentar os equipamentos.')
    window.open(controlUrl(started.codigo), '_blank', 'noopener')
  })
  const act = (acao: 'pausar' | 'retomar' | 'reiniciar' | 'encerrar') => run(async () => {
    if (!session) return
    if (acao === 'encerrar' && !window.confirm('Encerrar esta simulação? O histórico gerado no pipeline é mantido.')) return
    await sessionAction(session.codigo, acao)
    refresh()
    setNotice(acao === 'reiniciar' ? 'Simulação reiniciada com o layout salvo; itens voltaram à posição inicial.' : `Simulação ${acao === 'encerrar' ? 'encerrada' : acao === 'pausar' ? 'pausada' : 'retomada'}.`)
    if (acao === 'encerrar') setView('config')
  })

  const sim = config.data
  return <>
    <div className="page-heading"><div><p className="eyebrow">SIMULADOR WEB · DADOS SINTÉTICOS</p><h1>Simulador</h1>
      <p className="lead">Configure a planta, os leitores virtuais e os portais; inicie a simulação e movimente os equipamentos em outra aba. As leituras virtuais passam pelo mesmo MQTT, ingestor e motor de inferência do sistema real.</p></div></div>
    {sim && !sim.habilitado && <p className="admin-warning" role="note"><Icon name="alert" size={16}/> Simulador desabilitado neste servidor ({sim.motivo}). É possível editar layouts, mas não iniciar simulações. Em ambiente de desenvolvimento, use <code>python scripts/dev.py --teste 1</code>.</p>}
    {sim?.motor?.erro && <p className="admin-error" role="alert">Publicação MQTT com falha: {sim.motor.erro}</p>}
    <div className="sim-scenarios" role="tablist" aria-label="Cenário de simulação">
      {CENARIOS.map((item) => <button key={item.id} type="button" role="tab" aria-selected={cenario === item.id}
        onClick={() => { if (dirty && !window.confirm('Descartar as alterações não salvas?')) return; setCenario(item.id); setView('config'); window.location.hash = `#/simulador?cenario=${item.id}` }}>
        <strong>{item.nome}</strong><small>{item.descricao}</small></button>)}
    </div>
    {canEdit && <section className="panel sim-quick" aria-labelledby="sim-quick-title">
      <div><h2 id="sim-quick-title">Teste rápido</h2>
        <p>Um clique: monta a planta {cenario === 'easy' ? 'do laboratório' : 'do HUPAA com posições ilustrativas'}, inicia a simulação e já coloca 4 equipamentos (2 cadastrados, 1 com tag não cadastrada e 1 sem etiqueta). Abre o controle em outra aba.</p></div>
      <div className="sim-quick-actions">
        <button type="button" className="admin-primary sim-start" disabled={busy || !sim?.habilitado} onClick={quick}><Icon name="arrow" size={16}/> Testar agora</button>
        <button type="button" className="danger" disabled={busy || !layouts?.length} onClick={wipe}>Apagar tudo</button>
      </div>
    </section>}
    {notice && <p className="admin-success" role="status">{notice}</p>}
    {error && <p className="admin-error" role="alert">{error}</p>}
    {layouts === null && <div className="panel table-skeleton" role="status" aria-label="Carregando layouts"><span/><span/></div>}
    {layouts?.length === 0 && <div className="empty-panel panel"><h3>Nenhum layout salvo para este cenário</h3><p>Use o teste rápido acima ou crie um layout a partir da configuração predefinida e ajuste no editor.</p>
      {canEdit && <button type="button" disabled={busy} onClick={create}>Criar layout para editar</button>}</div>}
    {current && draft && <>
      <section className="panel sim-session-bar" aria-label="Layout e sessão">
        <label>Layout<select value={current.id} onChange={(e) => choose(Number(e.target.value))}>{layouts!.map((item) => <option key={item.id} value={item.id}>{item.nome}</option>)}</select></label>
        <label>Nome<input value={name} maxLength={120} disabled={!canEdit} onChange={(e) => { setName(e.target.value); setDirty(true) }}/></label>
        <div className="sim-session-actions">
          {canEdit && <><button type="button" className="admin-primary" disabled={busy || !dirty} onClick={save}>{dirty ? 'Salvar layout' : 'Salvo'}</button>
            <button type="button" disabled={!history.length} title="Ctrl+Z" onClick={undo}>Desfazer</button>
            <button type="button" disabled={busy} onClick={restore}>Restaurar predefinido</button>
            <button type="button" disabled={busy} onClick={create}>Novo layout</button>
            <button type="button" className="danger" disabled={busy || !!session} title={session ? 'Encerre a simulação antes' : undefined} onClick={archive}>Excluir layout</button></>}
        </div>
        <div className="sim-session-state">
          {session ? <>
            <span className={`sim-state sim-state-${session.estado}`}>{ESTADO[session.estado]}</span>
            <a className="admin-primary as-button" href={`#/simulador/controle/${session.codigo}`} target="_blank" rel="noopener">Abrir controle em nova aba</a>
            <button type="button" onClick={() => { void navigator.clipboard?.writeText(controlUrl(session.codigo)); setNotice('Link do controle copiado.') }}>Copiar link</button>
            {canEdit && <>{session.estado === 'em_execucao' ? <button type="button" disabled={busy} onClick={() => act('pausar')}>Pausar</button> : <button type="button" disabled={busy} onClick={() => act('retomar')}>Retomar</button>}
              <button type="button" disabled={busy} onClick={() => act('reiniciar')}>Reiniciar</button>
              <button type="button" className="danger" disabled={busy} onClick={() => act('encerrar')}>Encerrar</button></>}
          </> : canEdit && <button type="button" className="admin-primary sim-start" disabled={busy || !sim?.habilitado} onClick={start}><Icon name="arrow" size={16}/> Iniciar simulação</button>}
        </div>
      </section>
      {session && <div className="map-tabs" role="tablist" aria-label="Visão do simulador">
        <button type="button" role="tab" aria-selected={view === 'config'} onClick={() => setView('config')}>Configuração da planta</button>
        <button type="button" role="tab" aria-selected={view === 'monitor'} onClick={() => setView('monitor')}>Monitoramento do pipeline</button>
      </div>}
      {view === 'config' || !session ? <>
        {(() => {
          const faltam = pendencias(draft)
          return faltam.length ? <details className="sim-warnings" open={faltam.length <= 4}><summary>Falta {faltam.length} passo(s) para a simulação detectar passagens</summary><ul>{faltam.map((item) => <li key={item}>{item}</li>)}</ul></details>
            : <p className="sim-ready" role="status"><Icon name="check" size={16}/> Planta pronta: {dirty ? 'salve e inicie a simulação.' : session ? 'em uso pela simulação.' : 'pode iniciar a simulação.'}</p>
        })()}
        {session && <p className="muted-text">A simulação em andamento usa a versão salva no início. Salve e use “Reiniciar” para aplicar mudanças.</p>}
        <LayoutEditor config={draft} disabled={!canEdit} onChange={edit}/>
      </> : <SessionMonitor codigo={session.codigo} layout={draft}/>}
    </>}
  </>
}

const DIRECAO: Record<string, string> = { confirmed: 'Confirmada', ambiguous: 'Ambígua', unknown: 'Desconhecida' }

function SessionMonitor({ codigo, layout }: { codigo: string; layout: LayoutConfig }) {
  const query = useLiveQuery(`sim:monitor:${codigo}`, (signal) => getMonitor(codigo, signal))
  const data: Monitor | null = query.data
  if (!data) return query.error ? <div className="state-panel error-panel" role="alert">Não foi possível carregar o monitoramento.</div> : <div className="panel table-skeleton" role="status" aria-label="Carregando monitoramento"><span/><span/></div>
  const naoCadastradas = data.tags.filter((tag) => !tag.equipamento).length
  const confirmadas = data.passagens.filter((item) => item.direcao_status === 'confirmed').length
  return <div className="sim-monitor">
    <p className="muted-text">Tudo nesta visão vem do banco: leituras gravadas pelo ingestor, passagens e última zona confirmadas pela inferência. A posição virtual dos itens não aparece aqui — o RFID só sabe a zona.</p>
    <div className="kpi-grid sim-kpis">
      <article className="kpi-card kpi-total"><div className="kpi-card-heading"><span className="kpi-card-label">Leituras recebidas</span><span className="kpi-icon"><Icon name="antenna" size={18}/></span></div><strong>{data.leituras_total.toLocaleString('pt-BR')}</strong></article>
      <article className="kpi-card kpi-available"><div className="kpi-card-heading"><span className="kpi-card-label">Tags reconhecidas</span><span className="kpi-icon"><Icon name="check" size={18}/></span></div><strong>{data.tags.length - naoCadastradas}</strong></article>
      <article className="kpi-card kpi-offline"><div className="kpi-card-heading"><span className="kpi-card-label">EPCs não cadastrados</span><span className="kpi-icon"><Icon name="question" size={18}/></span></div><strong>{naoCadastradas}</strong></article>
      <article className="kpi-card kpi-attention"><div className="kpi-card-heading"><span className="kpi-card-label">Passagens confirmadas</span><span className="kpi-icon"><Icon name="portal" size={18}/></span></div><strong>{confirmadas}</strong></article>
    </div>
    <section className="panel" aria-labelledby="sim-zones-title"><div className="panel-heading"><div><p className="eyebrow">ÚLTIMA ZONA CONFIRMADA</p><h2 id="sim-zones-title">Distribuição por zona</h2></div></div>
      <SimPlan layout={layout} label="Planta com equipamentos agrupados pela última zona confirmada" options={{ showCoverage: false }}>
        {layout.zonas.map((zona) => zona.area && <div key={zona.chave} className="sim-zone-summary" style={{ left: `${zona.area.x + 1}%`, top: `${zona.area.y + 6}%`, maxWidth: `${Math.max(zona.area.largura - 2, 12)}%` }}>
          <strong>{data.zonas[zona.chave]?.length ?? 0}</strong> equipamento(s)
          <ul>{(data.zonas[zona.chave] ?? []).slice(0, 6).map((item) => <li key={item.id} className={`recency-${item.estado_recencia}`}>{item.nome}</li>)}</ul>
        </div>)}
      </SimPlan>
      {layout.zonas.some((zona) => !zona.area) && <ul className="sim-zone-list">{layout.zonas.filter((zona) => !zona.area).map((zona) => <li key={zona.chave}><strong>{zona.nome}</strong>: {(data.zonas[zona.chave] ?? []).map((item) => item.nome).join(', ') || 'nenhum equipamento'}</li>)}</ul>}
    </section>
    <div className="sim-monitor-grid">
      <section className="panel" aria-labelledby="sim-passages-title"><h2 id="sim-passages-title">Passagens</h2>
        {data.passagens.length ? <table className="equipment-table"><thead><tr><th>Equipamento / EPC</th><th>Portal</th><th>Direção</th><th>Quando</th></tr></thead><tbody>
          {data.passagens.map((item) => <tr key={item.id}><td><strong>{item.equipamento ?? 'Não cadastrado'}</strong><small><code>{item.epc}</code></small></td><td>{item.portal}</td>
            <td><span className={`tag-chip direction-${item.direcao_status ?? 'pendente'}`}>{item.direcao_status ? DIRECAO[item.direcao_status] : 'Em análise'}</span>{item.zona_origem && <small>{item.zona_origem} → {item.zona_destino}</small>}</td>
            <td>{ageLabel(item.detectada_em)}</td></tr>)}</tbody></table> : <p className="empty-panel">Nenhuma passagem ainda. Atravesse um portal: saia do alcance de um lado e entre no do outro.</p>}
      </section>
      <section className="panel" aria-labelledby="sim-readers-title"><h2 id="sim-readers-title">Leitores virtuais</h2>
        <ul className="sim-readers">{data.leitores.map((leitor) => <li key={leitor.chave}><span className={`hardware-status hardware-${leitor.status}`}>{leitor.status.replace('_', ' ')}</span> <strong>{leitor.reader_id}</strong> · {leitor.modelo}<small>{leitor.leituras_sessao.toLocaleString('pt-BR')} leitura(s) nesta sessão · último contato {ageLabel(leitor.ultimo_contato_em)}</small></li>)}</ul>
        <h3>Tags lidas</h3>
        {data.tags.length ? <ul className="sim-tags">{data.tags.map((tag) => <li key={tag.epc}><code>{tag.epc}</code> {tag.equipamento ? <span className="tag-chip tag-known">{tag.equipamento.nome}</span> : <><span className="tag-chip tag-unknown">Não cadastrada</span> <a href="#/cadastro">Cadastrar</a></>}<small>{tag.leituras} leitura(s) · {ageLabel(tag.ultima_leitura_em)}</small></li>)}</ul> : <p className="muted-text">Nenhuma tag lida nesta sessão.</p>}
      </section>
    </div>
    <section className="panel" aria-labelledby="sim-reads-title"><h2 id="sim-reads-title">Leituras recentes</h2>
      {data.leituras.length ? <div className="table-wrap"><table className="equipment-table"><thead><tr><th>EPC</th><th>Equipamento</th><th>Leitor · porta</th><th>RSSI</th><th>Quando</th></tr></thead><tbody>
        {data.leituras.map((item) => <tr key={item.id}><td><code>{item.epc}</code></td><td>{item.equipamento?.nome ?? <span className="muted-text">Não cadastrado</span>}</td><td>{item.reader_id} · {item.porta}</td><td>{item.rssi ?? '—'}</td><td>{ageLabel(item.lido_em)}</td></tr>)}
      </tbody></table></div> : <p className="empty-panel">Sem leituras. Arraste um item etiquetado até uma área de leitura na aba de controle.</p>}
    </section>
  </div>
}
