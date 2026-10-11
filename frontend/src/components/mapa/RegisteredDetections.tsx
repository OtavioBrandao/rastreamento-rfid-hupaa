import { getReadSummary } from '../../services/dashboard'
import { useLiveQuery } from '../../services/live'
import type { EquipmentItem } from '../../types/dashboard'
import { ageLabel, antennaLabel, isFresh } from '../DashboardParts'

const WINDOW_SECONDS = 300

/** Visão direta dos equipamentos cadastrados e de onde suas tags estão sendo lidas. */
export function RegisteredDetections({ items, onSelect }: { items: EquipmentItem[]; onSelect: (item: EquipmentItem) => void }) {
  const query = useLiveQuery('registered-detections', (signal) => getReadSummary(WINDOW_SECONDS, true, signal))
  const byId = new Map(items.map((item) => [item.id, item]))
  const rows = [...(query.data?.items ?? [])].filter((row) => row.equipamento && byId.has(row.equipamento.id))
    .sort((a, b) => Number(isFresh(b.ultima_leitura)) - Number(isFresh(a.ultima_leitura)) || b.leituras - a.leituras)
  return <section className="panel inventory-panel registered-detections" aria-labelledby="registered-detections-title">
    <div className="panel-heading"><div><p className="eyebrow">EQUIPAMENTOS CADASTRADOS</p><h2 id="registered-detections-title">Detectados recentemente</h2></div><span>Leituras dos últimos 5 minutos</span></div>
    {query.loading && <p role="status">Carregando leituras...</p>}
    {query.error && <p role="alert">Não foi possível atualizar as leituras. Tentando novamente...</p>}
    {query.data && (rows.length ? <div className="table-wrap"><table className="equipment-table">
      <thead><tr><th>Equipamento</th><th>Lido agora em</th><th>Leituras (5 min)</th><th>Última zona confirmada</th></tr></thead>
      <tbody>{rows.map((row) => {
        const equipment = row.equipamento!
        const asset = byId.get(equipment.id)
        const fresh = isFresh(row.ultima_leitura)
        return <tr key={row.epc} className={fresh ? 'registered-row' : undefined}>
          <td data-label="Equipamento">{asset ? <button className="table-item-button" type="button" onClick={() => onSelect(asset)}>{equipment.nome}<small>{row.epc}</small></button> : <>{equipment.nome}<small>{row.epc}</small></>}</td>
          <td data-label="Lido agora em"><div><span className={fresh ? 'presence-dot fresh' : 'presence-dot'} aria-hidden="true"/>{fresh ? antennaLabel(row.ultima_leitura) : 'Sem leitura recente'}<small>{row.ultima_leitura ? `${fresh ? '' : `${antennaLabel(row.ultima_leitura)} · `}${ageLabel(row.ultima_leitura.em)}` : 'Nunca lida'}</small></div></td>
          <td data-label="Leituras (5 min)"><strong>{row.leituras.toLocaleString('pt-BR')}</strong></td>
          <td data-label="Última zona"><div>{equipment.ultima_zona ?? 'Nenhuma passagem confirmada'}{equipment.ultima_zona_em && <small>{ageLabel(equipment.ultima_zona_em)}</small>}</div></td>
        </tr>
      })}</tbody>
    </table></div> : <p>Nenhum equipamento cadastrado com tag ativa.</p>)}
  </section>
}
