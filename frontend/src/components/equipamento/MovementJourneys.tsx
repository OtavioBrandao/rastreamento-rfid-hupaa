import type { JourneyEvent, JourneyStep, Journeys } from '../../services/dashboard'
import { detectionLabel } from '../DashboardParts'

const ZONA = 'America/Maceio'

/** Data e hora com segundos, no fuso da aplicação: horário das leituras de evidência. */
export function secondsLabel(value: string | null | undefined) {
  return value ? new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: ZONA,
  }).format(new Date(value)) : 'horário não registrado'
}

export function durationLabel(seconds: number | null | undefined) {
  if (seconds == null) return null
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total} s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} min ${total % 60} s`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

/** Linha do resumo: percurso direto, saída parada na circulação ou observação sem entrada. */
function summaryLine(event: JourneyEvent, stopped: boolean) {
  if (event.tipo === 'observacao') {
    return { text: `${event.titulo} — entrada não confirmada`, tag: 'Observação', kind: 'observacao' }
  }
  if (event.tipo === 'correcao') return { text: event.titulo, tag: 'Correção manual', kind: 'correcao' }
  if (!event.completo) {
    return { text: event.titulo, tag: stopped ? 'Saída confirmada · parado na circulação' : 'Percurso incompleto', kind: 'incompleto' }
  }
  return { text: event.titulo, tag: event.mesma_zona ? 'Saiu e voltou' : 'Percurso concluído', kind: 'percurso' }
}

/** Até três acontecimentos mais recentes, mostrados assim que o painel abre. */
export function JourneySummary({ data }: { data: Journeys }) {
  const recent = data.items.slice(0, 3)
  if (!recent.length) return <p className="muted-text">Nenhuma movimentação ou observação registrada.</p>
  const firstJourney = data.items.find((event) => event.tipo !== 'observacao')
  return <ol className="journey-summary">{recent.map((event, index) => {
    const line = summaryLine(event, data.em_circulacao && event === firstJourney && !event.completo)
    return <li key={`${event.tipo}-${event.em}-${index}`} className={`journey-${line.kind}`}>
      <strong>{line.text}</strong>
      <span>{detectionLabel(event.tipo === 'observacao' ? event.inicio ?? event.em : event.em)} · {line.tag}</span>
      {event.tipo === 'observacao' && <small>Última localização confirmada: {event.zona_confirmada_no_momento ?? 'nenhuma'}. Só a passagem 1 → 2 confirma a entrada.</small>}
      {event.tipo === 'correcao' && event.justificativa && <small>{event.justificativa}</small>}
    </li>
  })}</ol>
}

function StepDetail({ step, index }: { step: JourneyStep; index: number }) {
  const manual = step.origem_registro !== 'passagem_automatica'
  return <li>
    <strong>Etapa {index + 1}: {step.de} → {step.para}</strong>
    <span>{secondsLabel(step.em)}{manual ? ' · correção manual' : ''}</span>
    {!manual && <small>{step.portal ?? 'Portal não registrado'} · {step.leitor ?? 'leitor não registrado'}{step.ordem ? ` · antenas ${step.ordem}` : ''}</small>}
    {step.antenas.length > 0 && <small>Leituras usadas: {step.antenas.map((antenna) => `Antena ${antenna.porta} às ${secondsLabel(antenna.lido_em)}`).join('; ')}{step.travessia_s != null ? ` (travessia em ${durationLabel(step.travessia_s)})` : ''}</small>}
  </li>
}

/** Histórico completo: cada deslocamento em um bloco, com as etapas e as evidências. */
export function JourneyBlocks({ data }: { data: Journeys }) {
  if (!data.items.length) return <p>Nenhuma movimentação registrada.</p>
  const firstJourney = data.items.find((event) => event.tipo !== 'observacao')
  return <div className="journey-blocks">{data.items.map((event, index) => {
    const key = `${event.tipo}-${event.em}-${index}`
    if (event.tipo === 'observacao') {
      return <article key={key} className="journey-block journey-observacao">
        <h4>{event.titulo} <em>observação, sem deslocamento</em></h4>
        <p>{secondsLabel(event.inicio)} até {secondsLabel(event.fim)} · {event.leitor}, Antena {event.porta} · {event.leituras} leitura(s)</p>
        <p className="muted-text">Entrada não confirmada: a localização confirmada continuava {event.zona_confirmada_no_momento ?? 'desconhecida'}.</p>
      </article>
    }
    const stopped = data.em_circulacao && event === firstJourney && !event.completo
    return <article key={key} className={`journey-block ${event.tipo === 'correcao' ? 'journey-correcao' : event.completo ? 'journey-percurso' : 'journey-incompleto'}`}>
      <h4>{event.titulo} <em>{event.tipo === 'correcao' ? 'correção manual' : event.completo ? 'percurso concluído' : 'percurso incompleto'}</em></h4>
      {event.tipo === 'correcao' && <p>{event.justificativa ?? 'Sem justificativa registrada'}{event.referencia ? ` (ref. ${event.referencia})` : ''}</p>}
      {event.tipo === 'percurso' && event.origem == null && <p className="muted-text">Origem desconhecida: nenhuma localização confirmada antes desta entrada.</p>}
      {event.tipo === 'percurso' && event.origem != null && event.saida_registrada === false && event.etapas && event.etapas.length === 1 && event.etapas[0].de !== event.origem &&
        <p className="muted-text">Saída de {event.origem} não registrada por portal; a origem é a última localização confirmada.</p>}
      <ol>{(event.etapas ?? []).map((step, stepIndex) => <StepDetail key={step.movimentacao_id} step={step} index={stepIndex}/>)}</ol>
      {event.tempo_na_circulacao_s != null && <p>Tempo na circulação entre as etapas: {durationLabel(event.tempo_na_circulacao_s)}</p>}
      {event.tipo === 'percurso' && !event.completo && <p className="journey-pending">{stopped ? 'Percurso incompleto: parado na circulação; a entrada em outra zona ainda não foi confirmada.' : 'Percurso incompleto: a entrada em outra zona não foi confirmada.'}</p>}
    </article>
  })}</div>
}
