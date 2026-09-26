import type { AssetPage, EquipmentItem, OverviewSummary } from '../../types/dashboard'
import { LocationBadge, StatusBadge, detectionLabel } from '../DashboardParts'

export function DashboardOverview({ data, summary, onSelect, onPage }: {
  data: AssetPage; summary: OverviewSummary | null; onSelect: (item: EquipmentItem) => void; onPage: (page: number) => void
}) {
  const pages = Math.ceil(data.total / data.page_size)
  return <><section className="summary-section" aria-labelledby="summary-title"><div className="section-heading"><h2 id="summary-title">Situação dos equipamentos</h2></div><div className="kpi-grid">
    <article className="kpi-card kpi-total"><span>Total de equipamentos</span><strong>{summary?.registered ?? '—'}</strong></article>
    <article className="kpi-card kpi-available"><span>Disponíveis</span><strong>{summary?.disponivel ?? '—'}</strong></article>
    <article className="kpi-card kpi-attention"><span>Atenção necessária</span><strong>{summary?.atencao ?? '—'}</strong></article>
    <article className="kpi-card kpi-critical"><span>Fora de serviço</span><strong>{summary?.fora_de_servico ?? '—'}</strong></article>
    <article className="kpi-card kpi-offline"><span>Nunca detectados</span><strong>{summary?.nunca_detectado ?? '—'}</strong></article>
  </div></section><section className="panel inventory-panel" aria-labelledby="inventory-title">
    <div className="panel-heading"><div><p className="eyebrow">INVENTÁRIO</p><h2 id="inventory-title">Equipamentos</h2></div><span>{data.total} encontrados</span></div>
    {data.items.length ? <div className="table-wrap"><table className="equipment-table">
      <thead><tr><th>Equipamento</th><th>Tipo / EPC</th><th>Última zona</th><th>Status</th><th>Última detecção</th></tr></thead>
      <tbody>{data.items.map((item) => <tr key={item.id}>
        <td><button className="table-item-button" type="button" onClick={() => onSelect(item)}>{item.nome}<small>{item.identificador_interno}</small></button></td>
        <td>{item.tipo}<small>{item.epc ?? 'Sem EPC associado'}</small></td>
        <td>{item.ultima_zona?.nome ?? 'Nenhuma localização registrada'}</td>
        <td><StatusBadge status={item.status}/><LocationBadge item={item}/></td>
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
