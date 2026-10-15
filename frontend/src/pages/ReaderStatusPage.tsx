import { readJson } from '../services/dashboard'
import { useLiveQuery } from '../services/live'

type Status = 'online' | 'degradado' | 'offline' | 'nunca_conectado'
interface Reader { id: number; reader_id: string; modelo: string; ativo: boolean; status: Status; motivo: string; ultimo_contato_em: string | null; ultimo_heartbeat_em: string | null; origem_ultimo_contato: string | null }
interface Portal { id: number; nome: string; ativo: boolean; status: Status; motivo: string; leitores_ids: number[]; ultimo_contato_em: string | null; lados_configurados: string[] }
interface Snapshot { consultado_em: string; degradado_apos_segundos: number; offline_apos_segundos: number; leitores: Reader[]; portais: Portal[] }

const labels: Record<Status, string> = { online: 'Online', degradado: 'Degradado', offline: 'Offline', nunca_conectado: 'Nunca conectado' }
const reasons: Record<string, string> = {
  sem_contato_observado: 'Nenhuma mensagem válida observada', timeout_sem_mensagens: 'Prazo sem mensagens excedido',
  degradacao_reportada: 'Degradação informada pelo heartbeat', contato_atrasado: 'Contato atrasado', contato_recente: 'Contato recente',
  sem_leitores_ativos: 'Nenhum leitor ativo associado', leitores_sem_contato: 'Leitores sem contato recente',
  topologia_incompleta: 'Mapeamento dos lados A/B incompleto', todos_leitores_online: 'Todos os leitores online',
  falha_parcial_ou_degradacao: 'Parte dos leitores indisponível ou degradada',
}
function date(value: string | null) { return value ? new Date(value).toLocaleString('pt-BR') : 'Sem contato' }
function Badge({ status }: { status: Status }) { return <span className={`hardware-status hardware-${status}`}>{labels[status]}</span> }

export function ReaderStatusPage() {
  const query = useLiveQuery('reader-status', (signal) => readJson<Snapshot>('/leitores/status', signal))
  const data = query.data
  const readers = data?.leitores.filter((reader) => reader.ativo) ?? []
  return <>
    <div className="page-heading"><div><p className="eyebrow">MONITORAMENTO DA INFRAESTRUTURA</p><h1>Status dos leitores</h1><p className="lead">Contato observado dos leitores e disponibilidade dos portais. A ausência de tags não significa falha do leitor; o heartbeat permite acompanhar a comunicação mesmo sem equipamentos no alcance.</p></div></div>
    {query.loading && <div className="state-panel" role="status">Carregando status dos leitores…</div>}
    {query.error && <div className="state-panel" role="alert">{data ? 'Não foi possível atualizar. Os dados abaixo são da última consulta; tentando novamente.' : 'Não foi possível carregar o status. Tentando novamente automaticamente.'}</div>}
    {data && <>
      <section className="summary-section" aria-label="Resumo dos leitores ativos"><div className="kpi-grid">{(Object.keys(labels) as Status[]).map((status) => <article className={`kpi-card hardware-card-${status}`} key={status}><span className="kpi-card-label">{labels[status]}</span><strong>{readers.filter((reader) => reader.status === status).length}</strong><small>leitor(es) ativo(s)</small></article>)}</div></section>
      <p className="hardware-policy">Degradação após {data.degradado_apos_segundos} s sem contato; offline após {data.offline_apos_segundos} s. Consulta: {date(data.consultado_em)}. Atualização automática a cada 2 s.</p>
      <section className="panel inventory-panel"><div className="panel-heading"><div><p className="eyebrow">COMUNICAÇÃO MQTT OBSERVADA</p><h2>Leitores cadastrados</h2></div></div>
        {data.leitores.length ? <div className="table-wrap"><table className="equipment-table"><thead><tr><th>Leitor</th><th>Estado</th><th>Último contato</th><th>Origem</th><th>Último heartbeat</th><th>Motivo</th></tr></thead><tbody>{data.leitores.map((reader) => <tr key={reader.id}><td data-label="Leitor"><strong>{reader.reader_id}</strong><small>{reader.modelo}{!reader.ativo && ' · Cadastro inativo'}</small></td><td data-label="Estado"><Badge status={reader.status}/></td><td data-label="Último contato">{date(reader.ultimo_contato_em)}</td><td data-label="Origem">{reader.origem_ultimo_contato === 'heartbeat' ? 'Heartbeat' : reader.origem_ultimo_contato === 'leitura' ? 'Leitura RFID' : '—'}</td><td data-label="Último heartbeat">{date(reader.ultimo_heartbeat_em)}</td><td data-label="Motivo">{reasons[reader.motivo] ?? 'Estado indisponível'}</td></tr>)}</tbody></table></div> : <div className="empty-panel">Nenhum leitor cadastrado.</div>}
      </section>
      <section className="panel inventory-panel hardware-portals"><div className="panel-heading"><div><p className="eyebrow">AGREGAÇÃO POR COMPONENTES ATIVOS</p><h2>Portais</h2></div></div>
        {data.portais.length ? <div className="table-wrap"><table className="equipment-table"><thead><tr><th>Portal</th><th>Estado</th><th>Leitores</th><th>Lados mapeados</th><th>Último contato de componente</th><th>Motivo</th></tr></thead><tbody>{data.portais.map((portal) => <tr key={portal.id}><td data-label="Portal"><strong>{portal.nome}</strong>{!portal.ativo && <small>Cadastro inativo</small>}</td><td data-label="Estado"><Badge status={portal.status}/></td><td data-label="Leitores">{portal.leitores_ids.map((id) => data.leitores.find((reader) => reader.id === id)?.reader_id ?? id).join(', ') || '—'}</td><td data-label="Lados mapeados">{portal.lados_configurados.map((side) => side.toUpperCase()).join(' / ') || '—'}</td><td data-label="Último contato de componente">{date(portal.ultimo_contato_em)}</td><td data-label="Motivo">{reasons[portal.motivo] ?? 'Estado indisponível'}</td></tr>)}</tbody></table></div> : <div className="empty-panel">Nenhum portal cadastrado.</div>}
      </section><p className="hardware-policy">Online confirma contato recente com o software. Não comprova alcance RF, antena saudável ou validação física. Cadastros inativos ficam fora dos totais e da agregação dos portais.</p>
    </>}
  </>
}
