import { useEffect, useState, type FormEvent } from 'react'
import { ageLabel } from '../components/DashboardParts'
import { Icon } from '../components/layout/Icon'
import { errorMessage } from '../services/api'
import {
  associateTag, createEquipmentType, epcAvailability, epcProblem, getDiscovery, getEquipmentTypes, getRegistrations, register, setInService,
  type EpcDetectado, type EquipamentoCadastro, type EstadoServico, type FiltrosDescoberta, type TipoEquipamento,
} from '../services/cadastro'
import { useLiveQuery, useLiveRefresh } from '../services/live'

type Tab = 'leitura' | 'manual' | 'equipamentos'

const WINDOWS = [
  { seconds: 120, label: '2 minutos' },
  { seconds: 900, label: '15 minutos' },
  { seconds: 3600, label: '1 hora' },
  { seconds: 86400, label: '24 horas' },
]

const STATUS_LABEL: Record<string, string> = { online: 'Online', degradado: 'Degradado', offline: 'Offline', nunca_conectado: 'Nunca conectado' }

function initialTab(): Tab {
  const query = window.location.hash.split('?')[1] ?? ''
  const tab = new URLSearchParams(query).get('aba')
  return tab === 'manual' || tab === 'equipamentos' ? tab : 'leitura'
}

export function RegistrationPage({ canEdit }: { canEdit: boolean }) {
  const [tab, setTab] = useState<Tab>(initialTab)
  const [notice, setNotice] = useState('')
  return <>
    <div className="page-heading"><div><p className="eyebrow">CADASTRO DE EQUIPAMENTOS E TAGS</p><h1>Cadastro</h1>
      <p className="lead">Cadastre equipamentos escolhendo uma tag detectada pelos leitores ou digitando o EPC. Nomes podem se repetir: cada equipamento é um registro próprio. Cadastrar não define localização — a zona muda apenas após passagem confirmada.</p></div></div>
    {!canEdit && <p className="admin-warning" role="note">Seu perfil pode consultar as tags detectadas, mas apenas administradores cadastram equipamentos e associam tags.</p>}
    {notice && <p className="admin-success" role="status">{notice}</p>}
    <div className="map-tabs" role="tablist" aria-label="Modalidades de cadastro">
      {([['leitura', 'Cadastrar por leitura RFID'], ['manual', 'Cadastro manual'], ['equipamentos', 'Equipamentos e tags']] as const).map(([id, label]) =>
        <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => { setTab(id); setNotice('') }}>{label}</button>)}
    </div>
    {tab === 'leitura' && <ByReading canEdit={canEdit} onDone={setNotice}/>}
    {tab === 'manual' && <section className="panel registration-panel" aria-labelledby="manual-title"><h2 id="manual-title">Cadastro manual</h2>
      <p className="muted-text">Informe o EPC impresso ou gravado na etiqueta. Deixe em branco para cadastrar o equipamento sem tag e associar depois.</p>
      {canEdit ? <RegistrationForm origin="manual" onDone={setNotice}/> : <p>Somente administradores podem cadastrar.</p>}</section>}
    {tab === 'equipamentos' && <EquipmentList canEdit={canEdit} onDone={setNotice}/>}
  </>
}

function ByReading({ canEdit, onDone }: { canEdit: boolean; onDone: (message: string) => void }) {
  const [filters, setFilters] = useState<FiltrosDescoberta>({ janela_segundos: 900, situacao: 'desconhecidos' })
  const [selected, setSelected] = useState<EpcDetectado | null>(null)
  const query = useLiveQuery(`discovery:${JSON.stringify(filters)}`, (signal) => getDiscovery(filters, signal))
  const data = query.data
  const reader = data?.leitores.find((item) => item.reader_id === filters.leitor)
  const offline = data?.leitores.filter((item) => item.status === 'offline' || item.status === 'nunca_conectado') ?? []
  return <>
    <ol className="registration-steps" aria-label="Como cadastrar por leitura">
      <li>Aproxime ou movimente o equipamento etiquetado perto de uma antena.</li>
      <li>O EPC aparece abaixo como <strong>Não cadastrada</strong>, com leitor, antena e horário.</li>
      <li>Selecione o EPC, informe nome e tipo e confirme a associação.</li>
    </ol>
    <form className="panel asset-filters" onSubmit={(event) => event.preventDefault()}>
      <label>Período<select value={filters.janela_segundos} onChange={(e) => setFilters({ ...filters, janela_segundos: Number(e.target.value) })}>{WINDOWS.map((item) => <option key={item.seconds} value={item.seconds}>Últimos {item.label}</option>)}</select></label>
      <label>Leitor<select value={filters.leitor ?? ''} onChange={(e) => setFilters({ ...filters, leitor: e.target.value || undefined, antena_id: undefined })}><option value="">Todos</option>{data?.leitores.map((item) => <option key={item.reader_id} value={item.reader_id}>{item.reader_id}{item.origem === 'simulado' ? ' (simulado)' : ''}</option>)}</select></label>
      <label>Antena<select value={filters.antena_id ?? ''} disabled={!reader} onChange={(e) => setFilters({ ...filters, antena_id: e.target.value ? Number(e.target.value) : undefined })}><option value="">Todas</option>{reader?.antenas.map((item) => <option key={item.antena_id} value={item.antena_id}>Porta {item.porta}</option>)}</select></label>
      <label>Situação<select value={filters.situacao} onChange={(e) => setFilters({ ...filters, situacao: e.target.value as FiltrosDescoberta['situacao'] })}><option value="desconhecidos">Somente não cadastradas</option><option value="todos">Todas</option><option value="cadastrados">Somente cadastradas</option></select></label>
    </form>
    {offline.length > 0 && <p className="admin-warning" role="note"><Icon name="alert" size={16}/> Leitor(es) sem contato recente: {offline.map((item) => `${item.reader_id} (${STATUS_LABEL[item.status]})`).join(', ')}. Tags perto deles não aparecerão até a comunicação voltar.</p>}
    {selected && canEdit && <section className="panel registration-panel" aria-labelledby="selected-title">
      <div className="panel-heading"><div><p className="eyebrow">TAG SELECIONADA</p><h2 id="selected-title"><code>{selected.epc}</code></h2></div><button type="button" className="admin-secondary" onClick={() => setSelected(null)}>Escolher outra</button></div>
      <p className="muted-text">Última leitura {ageLabel(selected.ultima_leitura_em)} em {selected.ultima_antena ? `${selected.ultima_antena.leitor} · antena ${selected.ultima_antena.porta}` : 'antena desconhecida'}{selected.recente ? '' : ' — leitura antiga: confirme que esta é a tag do equipamento à sua frente.'}</p>
      <RegistrationForm key={selected.epc} origin="leitura" epc={selected.epc} onDone={(message) => { setSelected(null); onDone(message) }}/>
    </section>}
    {query.loading && <div className="panel table-skeleton" role="status" aria-label="Carregando tags detectadas"><span/><span/><span/></div>}
    {query.error && !data && <div className="state-panel error-panel" role="alert"><h2>Não foi possível carregar as tags detectadas.</h2>Tentando novamente automaticamente.</div>}
    {data && <section className="panel inventory-panel" aria-labelledby="detected-title">
      <div className="panel-heading"><div><p className="eyebrow">ATUALIZAÇÃO AUTOMÁTICA</p><h2 id="detected-title">Tags detectadas</h2></div><span>{data.desconhecidos} não cadastrada(s) · {data.total} no período</span></div>
      {data.items.length ? <div className="table-wrap"><table className="equipment-table discovery-table">
        <thead><tr><th>Situação</th><th>EPC</th><th>Leitor / antena</th><th>Leituras</th><th>Última leitura</th><th><span className="visually-hidden">Ação</span></th></tr></thead>
        <tbody>{data.items.map((item) => <tr key={item.epc} className={item.situacao === 'cadastrado' ? 'registered-row' : 'unregistered-row'} aria-selected={selected?.epc === item.epc}>
          <td>{item.situacao === 'cadastrado'
            ? <><span className="tag-chip tag-known">Cadastrada</span><small>{item.equipamento?.nome} · {item.equipamento?.identificador_interno}</small></>
            : <span className="tag-chip tag-unknown">Não cadastrada</span>}</td>
          <td><code>{item.epc}</code></td>
          <td>{item.ultima_antena ? <>{item.ultima_antena.leitor} · antena {item.ultima_antena.porta}{item.ultima_antena.origem === 'simulado' && <span className="tag-chip tag-sim">Simulado</span>}<small>{item.antenas.length > 1 ? `${item.antenas.length} antenas leram esta tag` : item.ultima_antena.zona ?? ''}</small></> : '—'}</td>
          <td>{item.leituras.toLocaleString('pt-BR')}</td>
          <td><span className={item.recente ? 'presence-dot fresh' : 'presence-dot'} aria-hidden="true"/>{ageLabel(item.ultima_leitura_em)}{!item.recente && <small>Leitura antiga</small>}</td>
          <td>{item.situacao === 'desconhecido' && canEdit && <button type="button" className="admin-primary" onClick={() => setSelected(item)} aria-label={`Cadastrar equipamento com a tag ${item.epc}`}>Cadastrar</button>}</td>
        </tr>)}</tbody>
      </table></div> : <div className="empty-panel"><h3>Nenhuma tag {filters.situacao === 'desconhecidos' ? 'não cadastrada ' : ''}neste período</h3><p>Aproxime a etiqueta de uma antena e aguarde alguns segundos. No simulador web, arraste o item etiquetado até a área de leitura.</p></div>}
    </section>}
  </>
}

function TypeSelect({ value, onChange }: { value: number | ''; onChange: (id: number) => void }) {
  const [types, setTypes] = useState<TipoEquipamento[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    getEquipmentTypes(controller.signal).then(setTypes).catch(() => setTypes([]))
    return () => controller.abort()
  }, [])
  async function create() {
    if (!name.trim()) return
    setError('')
    try {
      const tipo = await createEquipmentType(name.trim())
      setTypes([...(types ?? []), tipo].sort((a, b) => a.nome.localeCompare(b.nome)))
      onChange(tipo.id); setCreating(false); setName('')
    } catch (failure) { setError(errorMessage(failure)) }
  }
  return <div className="type-select">
    <label>Tipo / categoria<select required value={value} onChange={(e) => onChange(Number(e.target.value))}><option value="" disabled>{types === null ? 'Carregando…' : 'Selecione'}</option>{types?.map((tipo) => <option key={tipo.id} value={tipo.id}>{tipo.nome}</option>)}</select></label>
    {creating ? <div className="inline-create"><input aria-label="Nome do novo tipo" placeholder="Ex.: Cadeira de rodas" maxLength={255} value={name} onChange={(e) => setName(e.target.value)}/><button type="button" onClick={create}>Criar tipo</button><button type="button" onClick={() => setCreating(false)}>Cancelar</button></div>
      : <button type="button" className="link-button" onClick={() => setCreating(true)}>+ Novo tipo</button>}
    {error && <small className="field-error" role="alert">{error}</small>}
  </div>
}

function RegistrationForm({ origin, epc: fixedEpc, onDone }: { origin: 'manual' | 'leitura'; epc?: string; onDone: (message: string) => void }) {
  const [name, setName] = useState('')
  const [typeId, setTypeId] = useState<number | ''>('')
  const [patrimony, setPatrimony] = useState('')
  const [description, setDescription] = useState('')
  const [epc, setEpc] = useState(fixedEpc ?? '')
  const [confirmed, setConfirmed] = useState(false)
  const [availability, setAvailability] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { refresh } = useLiveRefresh()
  const problem = epcProblem(epc)

  async function checkEpc() {
    setAvailability('')
    if (!epc.trim() || problem || fixedEpc) return
    try {
      const result = await epcAvailability(epc)
      setAvailability(result.disponivel ? 'EPC disponível para associação.' : `EPC já associado a ${result.equipamento?.nome} (${result.equipamento?.identificador_interno}).`)
    } catch { /* a verificação definitiva acontece ao salvar */ }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (!name.trim()) { setError('Informe o nome do equipamento.'); return }
    if (typeId === '') { setError('Selecione o tipo do equipamento.'); return }
    if (problem) { setError(problem); return }
    if (epc.trim() && !confirmed) { setError('Confirme que a tag pertence a este equipamento.'); return }
    setBusy(true)
    try {
      const created = await register({
        nome: name.trim(), tipo_id: typeId, identificador_interno: patrimony.trim() || undefined,
        descricao: description.trim() || undefined, epc: epc.trim() || undefined,
        origem_epc: origin, confirmar_associacao: !!epc.trim() && confirmed,
      })
      refresh()
      setName(''); setPatrimony(''); setDescription(''); setConfirmed(false); setAvailability('')
      if (!fixedEpc) setEpc('')
      onDone(created.epc
        ? `“${created.nome}” cadastrado (${created.identificador_interno}) e associado à tag ${created.epc}. Você já pode cadastrar o próximo.`
        : `“${created.nome}” cadastrado (${created.identificador_interno}) sem tag. Associe um EPC em “Equipamentos e tags”.`)
    } catch (failure) { setError(errorMessage(failure)) } finally { setBusy(false) }
  }

  return <form className="admin-editor registration-form" onSubmit={submit} noValidate><fieldset disabled={busy}>
    <div className="admin-form-grid">
      <label>Nome do equipamento<input required maxLength={255} placeholder="Ex.: Maca hospitalar" value={name} onChange={(e) => setName(e.target.value)}/><small>Pode repetir: duas macas podem ter o mesmo nome.</small></label>
      <TypeSelect value={typeId} onChange={setTypeId}/>
      <label>Patrimônio / identificador interno<input maxLength={255} placeholder="Opcional — gerado se vazio" value={patrimony} onChange={(e) => setPatrimony(e.target.value)}/><small>Único por equipamento físico.</small></label>
      <label>EPC da tag<input value={epc} readOnly={!!fixedEpc} maxLength={32} spellCheck={false} placeholder={origin === 'manual' ? 'Opcional — ex.: E2000017221101441890A001' : ''} aria-invalid={!!problem}
        onChange={(e) => { setEpc(e.target.value.toUpperCase()); setConfirmed(false); setAvailability('') }} onBlur={checkEpc}/>
        <small className={problem ? 'field-error' : undefined}>{problem ?? (availability || (fixedEpc ? 'Selecionado entre as tags detectadas.' : 'Hexadecimal, 8 a 32 caracteres.'))}</small></label>
    </div>
    <label>Descrição<input maxLength={2000} placeholder="Opcional — setor de origem, observações" value={description} onChange={(e) => setDescription(e.target.value)}/></label>
    {epc.trim() && !problem && <label className="checkbox-label confirm-tag"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}/> Confirmo que a tag <code>{epc.trim()}</code> está fixada neste equipamento.</label>}
    {error && <p className="admin-error" role="alert">{error}</p>}
    <div className="admin-form-actions"><button className="admin-primary" type="submit">{busy ? 'Salvando…' : epc.trim() ? 'Cadastrar e associar tag' : 'Cadastrar sem tag'}</button></div>
  </fieldset></form>
}

function EquipmentList({ canEdit, onDone }: { canEdit: boolean; onDone: (message: string) => void }) {
  const [situation, setSituation] = useState('sem_tag')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [associating, setAssociating] = useState<number | null>(null)
  const [service, setService] = useState<EstadoServico>('ativo')
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  const { refresh } = useLiveRefresh()
  const query = useLiveQuery(`registrations:${situation}:${search}:${page}:${service}`, (signal) => getRegistrations(situation, search, page, signal, service))
  const data = query.data
  async function toggleService(item: EquipamentoCadastro) {
    const emServico = item.status !== 'ativo'
    if (!emServico && !window.confirm(`Colocar “${item.nome}” (${item.identificador_interno}) fora de serviço? Ele sai do dashboard e da busca até ser reativado; a tag e o histórico ficam.`)) return
    setBusy(item.id); setError('')
    try { await setInService(item.id, emServico); refresh(); onDone(emServico ? `“${item.nome}” voltou ao serviço.` : `“${item.nome}” está fora de serviço.`) }
    catch (failure) { setError(errorMessage(failure)) } finally { setBusy(null) }
  }
  return <>
    <form className="panel asset-filters" onSubmit={(event) => event.preventDefault()}>
      <label>Situação da tag<select value={situation} onChange={(e) => { setSituation(e.target.value); setPage(1) }}><option value="sem_tag">Sem tag (aguardando etiqueta)</option><option value="com_tag">Com tag associada</option><option value="todos">Todos</option></select></label>
      <label>Serviço<select value={service} onChange={(e) => { setService(e.target.value as EstadoServico); setPage(1) }}><option value="ativo">Em serviço</option><option value="inativo">Fora de serviço</option><option value="todos">Todos</option></select></label>
      <label>Buscar<input type="search" placeholder="Nome, patrimônio ou EPC" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }}/></label>
    </form>
    {query.error && !data && <div className="state-panel error-panel" role="alert"><h2>Não foi possível carregar os equipamentos.</h2></div>}
    {error && <p className="admin-error" role="alert">{error}</p>}
    {data && <section className="panel inventory-panel" aria-labelledby="registered-title">
      <div className="panel-heading"><h2 id="registered-title">Equipamentos</h2><span>{data.total} equipamento(s)</span></div>
      {data.items.length ? <div className="table-wrap"><table className="equipment-table">
        <thead><tr><th>Equipamento</th><th>Tipo</th><th>Tag</th><th>Última zona confirmada</th><th><span className="visually-hidden">Ação</span></th></tr></thead>
        <tbody>{data.items.map((item) => <tr key={item.id} className={item.status !== 'ativo' ? 'row-out-of-service' : undefined}>
          <td><strong>{item.nome}</strong><small>{item.identificador_interno}</small>{item.status !== 'ativo' && <span className="tag-chip tag-out-of-service">Fora de serviço</span>}</td>
          <td>{item.tipo_nome}</td>
          <td>{item.epc ? <code>{item.epc}</code> : <span className="tag-chip tag-unknown">Sem tag</span>}</td>
          <td>{item.ultima_zona ?? 'Nenhuma'}</td>
          <td>{canEdit && <div className="admin-row-actions">
            {!item.epc && item.status === 'ativo' && (associating === item.id
              ? <AssociateTag equipmentId={item.id} name={item.nome} onCancel={() => setAssociating(null)} onDone={(message) => { setAssociating(null); onDone(message) }}/>
              : <button type="button" className="admin-primary" onClick={() => setAssociating(item.id)}>Associar tag</button>)}
            {associating !== item.id && <button type="button" className={item.status === 'ativo' ? 'danger' : undefined} disabled={busy === item.id}
              aria-label={`${item.status === 'ativo' ? 'Colocar fora de serviço' : 'Reativar'}: ${item.nome}`} onClick={() => { void toggleService(item) }}>
              {item.status === 'ativo' ? 'Fora de serviço' : 'Reativar'}</button>}
          </div>}</td>
        </tr>)}</tbody>
      </table></div> : <p className="empty-panel">Nenhum equipamento nesta situação.</p>}
      {data.pages > 1 && <div className="admin-pagination"><span>Página {data.page} de {data.pages}</span><button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button><button type="button" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Próxima</button></div>}
    </section>}
  </>
}

function AssociateTag({ equipmentId, name, onCancel, onDone }: { equipmentId: number; name: string; onCancel: () => void; onDone: (message: string) => void }) {
  const [epc, setEpc] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const recent = useLiveQuery('associate:recent', (signal) => getDiscovery({ janela_segundos: 900, situacao: 'desconhecidos' }, signal))
  const { refresh } = useLiveRefresh()
  const problem = epcProblem(epc)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (!epc.trim() || problem) { setError(problem ?? 'Informe o EPC.'); return }
    if (!confirmed) { setError('Confirme a associação.'); return }
    setBusy(true)
    try { await associateTag(equipmentId, epc.trim()); refresh(); onDone(`Tag ${epc.trim()} associada a “${name}”.`) }
    catch (failure) { setError(errorMessage(failure)) } finally { setBusy(false) }
  }
  return <form className="associate-form" onSubmit={submit}><fieldset disabled={busy}>
    <label>EPC<input value={epc} maxLength={32} spellCheck={false} placeholder="Digite ou escolha abaixo" onChange={(e) => { setEpc(e.target.value.toUpperCase()); setConfirmed(false) }}/></label>
    {!!recent.data?.items.length && <label>Detectadas agora<select value="" onChange={(e) => { setEpc(e.target.value); setConfirmed(false) }}><option value="">Escolher tag não cadastrada…</option>{recent.data.items.map((item) => <option key={item.epc} value={item.epc}>{item.epc} · {ageLabel(item.ultima_leitura_em)}</option>)}</select></label>}
    {problem && <small className="field-error">{problem}</small>}
    {epc.trim() && !problem && <label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}/> Confirmo a associação</label>}
    {error && <small className="field-error" role="alert">{error}</small>}
    <div className="admin-row-actions"><button type="submit" className="admin-primary">Associar</button><button type="button" onClick={onCancel}>Cancelar</button></div>
  </fieldset></form>
}
