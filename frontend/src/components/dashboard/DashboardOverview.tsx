import type { AssetPage, EquipmentItem, OverviewSummary } from '../../types/dashboard'
import { AssetStatusBadge, LocationBadge, PresenceBadge, ageLabel, antennaLabel, detectionLabel } from '../DashboardParts'
import { Icon } from '../layout/Icon'

export function DashboardOverview({ data, summary, onSelect, onPage }: {
  data: AssetPage; summary: OverviewSummary | null; onSelect: (item: EquipmentItem) => void; onPage: (page: number) => void
}) {
  const pages = Math.ceil(data.total / data.page_size)
  return <><section className="summary-section" aria-labelledby="summary-title"><div className="section-heading"><h2 id="summary-title">Situação dos equipamentos</h2></div><div className="kpi-grid">
    <article className="kpi-card kpi-total"><div className="kpi-card-heading"><span className="kpi-card-label">Total de equipamentos</span><span className="kpi-icon"><Icon name="reader" size={18}/></span></div><strong>{summary?.registered ?? '—'}</strong></article>
    <article className="kpi-card kpi-available"><div className="kpi-card-heading"><span className="kpi-card-label">Em trânsito</span><span className="kpi-icon"><Icon name="check" size={18}/></span></div><strong>{summary?.disponivel ?? '—'}</strong></article>
    <article className="kpi-card kpi-attention"><div className="kpi-card-heading"><span className="kpi-card-label">Atenção necessária</span><span className="kpi-icon"><Icon name="alert" size={18}/></span></div><strong>{summary?.atencao ?? '—'}</strong></article>
    <article className="kpi-card kpi-critical"><div className="kpi-card-heading"><span className="kpi-card-label">Fora de serviço</span><span className="kpi-icon"><Icon name="close" size={18}/></span></div><strong>{summary?.fora_de_servico ?? '—'}</strong></article>
    <article className="kpi-card kpi-offline"><div className="kpi-card-heading"><span className="kpi-card-label">Zona não confirmada</span><span className="kpi-icon"><Icon name="question" size={18}/></span></div><strong>{summary?.nunca_detectado ?? '—'}</strong></article>
  </div></section><section className="panel inventory-panel" aria-labelledby="inventory-title">
    <div className="panel-heading"><div><p className="eyebrow">INVENTÁRIO</p><h2 id="inventory-title">Equipamentos</h2></div><span>{data.total} encontrados</span></div>
    {data.items.length ? <div className="table-wrap"><table className="equipment-table">
      <thead><tr><th>Equipamento</th><th>Tipo / EPC</th><th>Última zona</th><th>Status</th><th>Última leitura da tag</th><th>Última zona confirmada em (horário de Maceió)</th></tr></thead>
      <tbody>{data.items.map((item) => <tr key={item.id}>
        <td><button className="table-item-button" type="button" onClick={() => onSelect(item)}>{item.nome}<small>{item.identificador_interno}</small></button></td>
        <td>{item.tipo}<small>{item.epc ?? 'Sem EPC associado'}</small></td>
        <td>{item.ultima_zona?.caminho ?? 'Nenhuma localização registrada'}</td>
        <td><AssetStatusBadge item={item}/><LocationBadge item={item}/><PresenceBadge reading={item.ultima_leitura}/></td>
        <td>{item.ultima_leitura ? <>{antennaLabel(item.ultima_leitura)}<small>{ageLabel(item.ultima_leitura.em)}</small></> : 'Sem leitura'}</td>
        <td>{detectionLabel(item.ultima_deteccao_em)}</td>
      </tr>)}</tbody>
    </table></div> : <div className="empty-panel"><h3>Nenhum equipamento encontrado</h3><p>Confira os filtros e tente novamente.</p></div>}
    <nav className="pagination" aria-label="Páginas da busca">
      <button type="button" disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}>Anterior</button>
      <span>Página {data.page} de {pages || 1}</span>
      <button type="button" disabled={data.page >= pages} onClick={() => onPage(data.page + 1)}>Próxima</button>
    </nav>
  </section></>
}
