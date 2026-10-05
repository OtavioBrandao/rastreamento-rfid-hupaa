import type { BoundPortal, BoundZone } from '../../services/mapTopology'
import { belongsToZone } from '../../services/mapTopology'
import type { EquipmentItem } from '../../types/dashboard'

export function MapReferences({ zones, portals, items, selectedZone, onZone }: {
  zones: BoundZone[]; portals: BoundPortal[]; items: EquipmentItem[]
  selectedZone: string; onZone: (id: string) => void
}) {
  return <section className="panel" aria-label="Zonas e portais da planta">
    <h2>Zonas e portais</h2>
    <p>Esquema de referência, sem escala validada. A posição dos ativos é aproximada por zona.</p>
    {zones.length ? <ul className="asset-list">{zones.map((zone) => <li key={zone.zoneId}>
      <button type="button" aria-pressed={selectedZone === zone.id} onClick={() => onZone(selectedZone === zone.id ? '' : zone.id)}>
        {zone.name} · {items.filter((item) => belongsToZone(item, zone)).length} ativo(s)
      </button>
    </li>)}</ul> : <p>Sem zonas vinculadas à planta. Consulte a lista textual de ativos.</p>}
    {portals.length ? <ul className="asset-list">{portals.map((portal) => <li key={portal.portalId}>
      <strong>{portal.name} · Portal #{portal.portalId}</strong><small>{portal.detail}</small>
      <small>A ordem das leituras nos lados A/B permite inferir a mudança de zona.</small>
    </li>)}</ul> : <p>Sem portal cadastrado com posição validada nesta planta.</p>}
  </section>
}
