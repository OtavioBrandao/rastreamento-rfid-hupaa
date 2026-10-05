import { useState } from 'react'
import { ageLabel, antennaLabel, isFresh } from '../components/DashboardParts'
import { Icon } from '../components/layout/Icon'
import { getReadSummary } from '../services/dashboard'
import { useLiveQuery } from '../services/live'
import type { ReadAntenna, ReadSummaryItem } from '../types/dashboard'

const WINDOWS = [
  { seconds: 30, label: '30 segundos' },
  { seconds: 60, label: '1 minuto' },
  { seconds: 300, label: '5 minutos' },
  { seconds: 900, label: '15 minutos' },
  { seconds: 3600, label: '1 hora' },
]

function antennaName(antenna: ReadAntenna) {
  return `Antena ${antenna.porta}${antenna.zona ? ` · ${antenna.zona}` : ''}`
}

function rate(item: ReadSummaryItem, seconds: number) {
  return (item.leituras / seconds).toFixed(1).replace('.', ',')
}

export function ReadingsPage() {
  const [windowSeconds, setWindowSeconds] = useState(60)
  const [registeredOnly, setRegisteredOnly] = useState(false)
  const query = useLiveQuery(`reads:${windowSeconds}:${registeredOnly}`,
    (signal) => getReadSummary(windowSeconds, registeredOnly, signal))
  const data = query.data
  const antennas = data?.antenas ?? []
  const multiReader = new Set(antennas.map((antenna) => antenna.leitor)).size > 1
  return <>
    <div className="page-heading"><div><p className="eyebrow">LEITURAS RFID AO VIVO</p><h1>Leituras</h1><p className="lead">Quantas vezes cada tag foi lida pelas antenas, separando equipamentos cadastrados de tags avulsas. A leitura indica presença no alcance da antena; a zona do equipamento só muda após passagem confirmada.</p></div></div>
    <form className="panel asset-filters" onSubmit={(event) => event.preventDefault()}>
      <label>Janela de contagem<select value={windowSeconds} onChange={(e) => setWindowSeconds(Number(e.target.value))}>{WINDOWS.map((option) => <option key={option.seconds} value={option.seconds}>{option.label}</option>)}</select></label>
      <label className="checkbox-label"><input type="checkbox" checked={registeredOnly} onChange={(e) => setRegisteredOnly(e.target.checked)}/> Somente tags cadastradas</label>
    </form>
    {query.loading && <div className="panel table-skeleton" role="status" aria-label="Carregando leituras"><span/><span/><span/></div>}
    {query.error && !data && <div className="state-panel error-panel" role="alert"><h2>Não foi possível carregar as leituras.</h2>Tentando novamente automaticamente.</div>}
    {query.error && data && <p role="alert">Não foi possível atualizar as leituras. Exibindo a última consulta; tentando novamente...</p>}
    {data && <>
      <section className="summary-section" aria-labelledby="reads-summary-title"><div className="section-heading"><h2 id="reads-summary-title">Na janela selecionada</h2></div><div className="kpi-grid">
        <article className="kpi-card kpi-total"><div className="kpi-card-heading"><span className="kpi-card-label">Leituras recebidas</span><span className="kpi-icon"><Icon name="antenna" size={18}/></span></div><strong>{data.total_leituras.toLocaleString('pt-BR')}</strong></article>
        <article className="kpi-card kpi-available"><div className="kpi-card-heading"><span className="kpi-card-label">Cadastradas detectadas</span><span className="kpi-icon"><Icon name="check" size={18}/></span></div><strong>{data.cadastradas_detectadas}</strong></article>
        <article className="kpi-card kpi-attention"><div className="kpi-card-heading"><span className="kpi-card-label">Cadastradas sem leitura</span><span className="kpi-icon"><Icon name="alert" size={18}/></span></div><strong>{data.cadastradas_sem_leitura}</strong></article>
        <article className="kpi-card kpi-offline"><div className="kpi-card-heading"><span className="kpi-card-label">Tags não cadastradas</span><span className="kpi-icon"><Icon name="question" size={18}/></span></div><strong>{data.nao_cadastradas}</strong></article>
      </div></section>
      <section className="panel inventory-panel" aria-labelledby="reads-title">
        <div className="panel-heading"><div><p className="eyebrow">CONTAGEM POR TAG</p><h2 id="reads-title">Tags lidas</h2></div><span>{data.items.length} tag(s)</span></div>
        {data.items.length ? <div className="table-wrap"><table className="equipment-table readings-table">
          <thead><tr><th>Equipamento</th><th>EPC</th><th>Leituras</th><th>Por segundo</th>{antennas.map((antenna) => <th key={antenna.antena_id}>{multiReader ? `${antenna.leitor} · ` : ''}{antennaName(antenna)}</th>)}<th>Última leitura</th><th>Última zona confirmada</th></tr></thead>
          <tbody>{data.items.map((item) => {
            const counts = new Map(item.leituras_por_antena.map((entry) => [entry.antena_id, entry.leituras]))
            const fresh = isFresh(item.ultima_leitura)
            return <tr key={item.epc} className={item.cadastrada ? 'registered-row' : 'unregistered-row'}>
              <td>{item.equipamento ? <strong>{item.equipamento.nome}</strong> : <span className="muted-text">Não cadastrada</span>}{item.equipamento && <small>{item.equipamento.identificador_interno}</small>}</td>
              <td><code>{item.epc}</code></td>
              <td><strong>{item.leituras.toLocaleString('pt-BR')}</strong></td>
              <td>{rate(item, data.janela_segundos)}</td>
              {antennas.map((antenna) => <td key={antenna.antena_id}>{counts.get(antenna.antena_id)?.toLocaleString('pt-BR') ?? '—'}</td>)}
              <td><span className={fresh ? 'presence-dot fresh' : 'presence-dot'} aria-hidden="true"/>{antennaLabel(item.ultima_leitura)}<small>{ageLabel(item.ultima_leitura?.em)}</small></td>
              <td>{item.cadastrada ? (item.equipamento?.ultima_zona ?? 'Nenhuma') : '—'}{item.equipamento?.ultima_zona_em && <small>{ageLabel(item.equipamento.ultima_zona_em)}</small>}</td>
            </tr>
          })}</tbody>
        </table></div> : <div className="empty-panel"><h3>Nenhuma leitura nesta janela</h3><p>Confira se o leitor está publicando no broker e se o ingestor está ativo.</p></div>}
      </section>
    </>}
  </>
}
