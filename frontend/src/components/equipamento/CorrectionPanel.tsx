import { useEffect, useState, type FormEvent } from 'react'
import {
  correctLocation, correctRecord, getEquipment, getTypeOptions, getZoneOptions,
  type EquipmentRecord, type Option, type RecordCorrection,
} from '../../services/correcoes'
import { detectionLabel } from '../DashboardParts'

export type CorrectionMode = 'localizacao' | 'cadastro'
type Field = 'zona' | 'nome' | 'identificador' | 'tipo' | 'descricao'
type Form = Record<Field, string>

const FIELDS: Record<CorrectionMode, Field[]> = {
  localizacao: ['zona'],
  cadastro: ['nome', 'identificador', 'tipo', 'descricao'],
}
const LABELS: Record<Field, string> = {
  zona: 'Zona', nome: 'Nome', identificador: 'Patrimônio (identificador interno)', tipo: 'Tipo',
  descricao: 'Descrição',
}

function formFrom(record: EquipmentRecord): Form {
  return {
    zona: record.ultima_zona_id === null ? '' : String(record.ultima_zona_id),
    nome: record.nome, identificador: record.identificador_interno,
    tipo: String(record.tipo_id), descricao: record.descricao ?? '',
  }
}

const clean = (value: string) => value.trim()

interface Props {
  mode: CorrectionMode
  equipmentId: number
  onDone: (message: string, identificador: string) => void
  onCancel: () => void
}

export function CorrectionPanel({ mode, equipmentId, onDone, onCancel }: Props) {
  const [phase, setPhase] = useState<'loading' | 'load-error' | 'edit' | 'review' | 'saving'>('loading')
  const [current, setCurrent] = useState<EquipmentRecord | null>(null)
  const [zones, setZones] = useState<Option[]>([])
  const [types, setTypes] = useState<Option[]>([])
  const [form, setForm] = useState<Form | null>(null)
  // Campos que a PESSOA mexeu: no conflito, só eles mantêm o valor escolhido.
  const [edited, setEdited] = useState<Set<Field>>(new Set())
  const [justificativa, setJustificativa] = useState('')
  const [referencia, setReferencia] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    setPhase('loading')
    Promise.all([getEquipment(equipmentId), mode === 'localizacao' ? getZoneOptions() : getTypeOptions()])
      .then(([record, options]) => {
        if (!active) return
        setCurrent(record)
        setForm(formFrom(record))
        setEdited(new Set())
        if (mode === 'localizacao') setZones(options); else setTypes(options)
        setPhase('edit')
      })
      .catch(() => { if (active) setPhase('load-error') })
    return () => { active = false }
  }, [equipmentId, mode, reload])

  const baseline = current ? formFrom(current) : null
  const changes = form && baseline
    ? FIELDS[mode].filter((field) => clean(form[field]) !== clean(baseline[field]))
    : []

  function label(field: Field, value: string): string {
    if (field === 'zona') {
      if (!value) return 'Nenhuma localização registrada'
      return zones.find((zone) => String(zone.id) === value)?.label ?? `Zona #${value} (inativa ou fora da lista)`
    }
    if (field === 'tipo') {
      return types.find((type) => String(type.id) === value)?.label
        ?? (current && String(current.tipo_id) === value ? current.tipo_nome : `Tipo #${value}`)
    }
    if (field === 'descricao') return clean(value) || '(sem descrição)'
    return clean(value)
  }

  function change(field: Field, value: string) {
    setForm((previous) => previous && { ...previous, [field]: value })
    setEdited((previous) => new Set(previous).add(field))
  }

  function review(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!clean(justificativa)) { setError('Informe a justificativa da correção.'); return }
    if (!form) return
    if (mode === 'cadastro' && (!clean(form.nome) || !clean(form.identificador))) {
      setError('Nome e patrimônio não podem ficar vazios.')
      return
    }
    if (changes.length === 0) { setError('Nada a corrigir: os valores são iguais aos atuais.'); return }
    setPhase('review')
  }

  async function confirm() {
    if (!current || !form) return
    setPhase('saving')
    setError(null)
    const meta = {
      justificativa: clean(justificativa), versao_esperada: current.versao,
      ...(clean(referencia) ? { referencia: clean(referencia) } : {}),
    }
    let result
    if (mode === 'localizacao') {
      result = await correctLocation(current.id, { zona_id: Number(form.zona), ...meta })
    } else {
      const body: RecordCorrection = {}
      for (const field of changes) {
        if (field === 'nome') body.nome = clean(form.nome)
        if (field === 'identificador') body.identificador_interno = clean(form.identificador)
        if (field === 'tipo') body.tipo_id = Number(form.tipo)
        if (field === 'descricao') body.descricao = clean(form.descricao) || null
      }
      result = await correctRecord(current.id, { ...body, ...meta })
    }
    if (result.ok) {
      const identificador = mode === 'cadastro' && changes.includes('identificador')
        ? clean(form.identificador) : current.identificador_interno
      onDone(mode === 'localizacao' ? 'Localização corrigida.' : 'Cadastro corrigido.', identificador)
      return
    }
    if (result.kind === 'conflict') {
      try {
        const fresh = await getEquipment(current.id)
        setCurrent(fresh)
        // Só o que a pessoa editou mantém o valor escolhido; o resto volta ao
        // atual — senão a nova confirmação desfaria em silêncio a outra operação.
        setForm((previous) => {
          const next = formFrom(fresh)
          if (previous) for (const field of edited) next[field] = previous[field]
          return next
        })
        setNotice(result.message)
        setPhase('edit')
      } catch {
        setPhase('load-error')
      }
      return
    }
    setError(result.message)
    setPhase('edit')
  }

  const title = mode === 'localizacao' ? 'Corrigir localização' : 'Corrigir cadastro'
  if (phase === 'loading') return <section className="correction-panel" aria-label={title}><p role="status">Carregando dados atuais…</p></section>
  if (phase === 'load-error' || !current || !form) {
    return <section className="correction-panel" aria-label={title}>
      <p role="alert">Não foi possível carregar os dados atuais do equipamento.</p>
      <div className="correction-actions">
        <button type="button" className="correction-secondary" onClick={() => setReload((value) => value + 1)}>Tentar novamente</button>
        <button type="button" className="correction-secondary" onClick={onCancel}>Cancelar</button>
      </div>
    </section>
  }

  return <section className="correction-panel" aria-label={title}>
    <h4>{title}</h4>
    {notice && <p className="correction-notice" role="alert">{notice}</p>}
    {phase === 'review' || phase === 'saving' ? <div className="correction-review">
      <table>
        <caption>Revise antes de confirmar</caption>
        <thead><tr><th scope="col">Campo</th><th scope="col">Atual</th><th scope="col">Corrigido</th></tr></thead>
        <tbody>{changes.map((field) => <tr key={field}>
          <th scope="row">{LABELS[field]}</th><td>{label(field, formFrom(current)[field])}</td><td>{label(field, form[field])}</td>
        </tr>)}</tbody>
      </table>
      <p className="correction-meta"><strong>Justificativa:</strong> {clean(justificativa)}{clean(referencia) && <> · <strong>Referência:</strong> {clean(referencia)}</>}</p>
      {mode === 'localizacao' && <p className="correction-hint">A correção vale a partir de agora (horário do servidor) e entra no histórico como correção manual.</p>}
      {error && <p className="correction-error" role="alert">{error}</p>}
      <div className="correction-actions">
        <button type="button" className="correction-primary" disabled={phase === 'saving'} onClick={confirm}>{phase === 'saving' ? 'Gravando…' : 'Confirmar correção'}</button>
        <button type="button" className="correction-secondary" disabled={phase === 'saving'} onClick={() => setPhase('edit')}>Voltar e editar</button>
      </div>
    </div> : <form className="correction-form" onSubmit={review} noValidate>
      {mode === 'localizacao' ? <>
        <div className="correction-current" role="group" aria-label="Localização atual">
          <strong>Localização atual</strong>
          <span>{label('zona', formFrom(current).zona)}</span>
          <span>Última detecção: {detectionLabel(current.ultima_deteccao_em)}</span>
        </div>
        <label htmlFor="correcao-zona">Nova zona</label>
        <select id="correcao-zona" value={form.zona} onChange={(event) => change('zona', event.target.value)}>
          <option value="">Selecione a zona</option>
          {zones.map((zone) => <option key={zone.id} value={zone.id}>{zone.label}</option>)}
        </select>
      </> : <>
        <label htmlFor="correcao-nome">Nome <span className="correction-was">(atual: {current.nome})</span></label>
        <input id="correcao-nome" value={form.nome} onChange={(event) => change('nome', event.target.value)}/>
        <label htmlFor="correcao-identificador">Patrimônio <span className="correction-was">(atual: {current.identificador_interno})</span></label>
        <input id="correcao-identificador" value={form.identificador} onChange={(event) => change('identificador', event.target.value)}/>
        <label htmlFor="correcao-tipo">Tipo <span className="correction-was">(atual: {label('tipo', String(current.tipo_id))})</span></label>
        <select id="correcao-tipo" value={form.tipo} onChange={(event) => change('tipo', event.target.value)}>
          {!types.some((type) => type.id === current.tipo_id) && <option value={current.tipo_id}>{current.tipo_nome}</option>}
          {types.map((type) => <option key={type.id} value={type.id}>{type.label}</option>)}
        </select>
        <label htmlFor="correcao-descricao">Descrição <span className="correction-was">(atual: {label('descricao', current.descricao ?? '')})</span></label>
        <textarea id="correcao-descricao" rows={2} value={form.descricao} onChange={(event) => change('descricao', event.target.value)}/>
      </>}
      <label htmlFor={`correcao-justificativa-${mode}`}>Justificativa (obrigatória)</label>
      <textarea id={`correcao-justificativa-${mode}`} rows={3} maxLength={1000} required value={justificativa} onChange={(event) => setJustificativa(event.target.value)}/>
      <label htmlFor={`correcao-referencia-${mode}`}>Referência (opcional: chamado, ordem de serviço)</label>
      <input id={`correcao-referencia-${mode}`} maxLength={255} value={referencia} onChange={(event) => setReferencia(event.target.value)}/>
      {error && <p className="correction-error" role="alert">{error}</p>}
      <div className="correction-actions">
        <button type="submit" className="correction-primary">Revisar correção</button>
        <button type="button" className="correction-secondary" onClick={onCancel}>Cancelar</button>
      </div>
    </form>}
  </section>
}
