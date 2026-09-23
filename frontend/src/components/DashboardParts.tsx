import type { EquipmentItem, DetectionStatus, DashboardData } from '../types/dashboard'

const statusLabels: Record<DetectionStatus, string> = {
  recent: 'Recente', outdated: 'Desatualizada', never: 'Nunca detectado',
}
const statusSymbols: Record<DetectionStatus, string> = {
  recent: '✓', outdated: '!', never: '—',
}

export function StatusBadge({ status }: { status: DetectionStatus }) {
  return <span className={`status-badge status-${status}`}><span aria-hidden="true">{statusSymbols[status]}</span> {statusLabels[status]}</span>
}

export function SummaryGrid({ summary }: { summary: DashboardData['summary'] }) {
  const cards = [
    { label: 'Equipamentos cadastrados', value: summary.registered, tone: 'total' },
    { label: 'Detectados recentemente', value: summary.recent, tone: 'recent' },
    { label: 'Localizações desatualizadas', value: summary.outdated, tone: 'outdated' },
    { label: 'Nunca detectados', value: summary.never, tone: 'never' },
  ]
  return <div className="summary-grid">{cards.map(({ label, value, tone }) =>
    <article className={`summary-card summary-${tone}`} key={label}>
      <p>{label}</p><strong>{value}</strong>
    </article>,
  )}</div>
}

export function RecentActivityItem({ item }: { item: EquipmentItem }) {
  return <li className="activity-item">
    <div className="activity-icon" aria-hidden="true">{item.name.charAt(0)}</div>
    <div className="activity-main">
      <div className="activity-title-row"><h3>{item.name}</h3><StatusBadge status={item.status} /></div>
      <p className="activity-type">{item.type} <span aria-hidden="true">·</span> Patrimônio {item.assetNumber}</p>
      <p className="zone-label">Última localização detectada</p>
      <p className="zone-value">{item.zone ?? 'Nenhuma localização registrada'}</p>
      {item.detectedAgo && <p className="activity-time">Última detecção {item.detectedAgo}{item.status === 'outdated' && <span className="outdated-note"> · Pode estar em outro local</span>}</p>}
    </div>
  </li>
}

export function RecentActivityList({ items }: { items: EquipmentItem[] }) {
  return <ul className="activity-list">{items.map((item) => <RecentActivityItem key={item.id} item={item} />)}</ul>
}
