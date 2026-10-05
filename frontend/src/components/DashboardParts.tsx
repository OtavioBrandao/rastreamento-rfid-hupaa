import type { AssetStatus, EquipmentItem } from '../types/dashboard'

const labels: Record<AssetStatus, string> = {
  disponivel: 'Em trânsito', atencao: 'Atenção necessária', offline: 'Offline',
  fora_de_servico: 'Fora de serviço', nunca_detectado: 'Nunca detectado',
}

export function StatusBadge({ status }: { status: AssetStatus }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>
}

export function LocationBadge({ item }: { item: EquipmentItem }) {
  return item.localizacao_desatualizada
    ? <span className="status-badge status-outdated">Localização pode estar desatualizada</span>
    : null
}

export function detectionLabel(value: string | null) {
  return value ? new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Maceio',
  }).format(new Date(value)) : 'Sem detecção'
}
