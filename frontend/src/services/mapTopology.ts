import type { MainZone, PortalPosition } from '../config/mapaConfig'
import type { EquipmentItem } from '../types/dashboard'

export interface RegisteredZone { id: number; nome: string; referencia_planta: string | null; ativo: boolean }
export interface RegisteredPortal { id: number; nome: string; zona_a_id: number; zona_b_id: number; ativo: boolean }
export interface MapTopology { zones: RegisteredZone[]; portals: RegisteredPortal[] }
export interface BoundZone extends MainZone { zoneId: number }
export interface BoundPortal extends PortalPosition { portalId: number; name: string; detail: string }
export const emptyTopology: MapTopology = { zones: [], portals: [] }

// Uma referência ambígua nunca escolhe silenciosamente uma zona de outro setor.
export function bindZones(config: MainZone[], registered: RegisteredZone[]): BoundZone[] {
  return config.flatMap((region) => {
    const matches = registered.filter((zone) => zone.ativo && zone.referencia_planta === region.id)
    return matches.length === 1 ? [{ ...region, name: matches[0].nome, zoneId: matches[0].id }] : []
  })
}

export function belongsToZone(item: EquipmentItem, zone: BoundZone): boolean {
  return item.status !== 'nunca_detectado' && item.ultima_zona?.id === zone.zoneId
    && item.ultima_zona.referencia_planta === zone.id
}

export function bindPortals(config: PortalPosition[], topology: MapTopology, zones: BoundZone[]): BoundPortal[] {
  return config.flatMap((position) => {
    const a = zones.find((zone) => zone.id === position.zoneA)
    const b = zones.find((zone) => zone.id === position.zoneB)
    if (!a || !b || a.zoneId === b.zoneId) return []
    const matches = topology.portals.filter((portal) => portal.ativo
      && (position.portalId !== undefined ? portal.id === position.portalId : portal.nome === position.portalName)
      && portal.zona_a_id === a.zoneId && portal.zona_b_id === b.zoneId)
    return matches.length === 1 ? [{ ...position, portalId: matches[0].id, name: matches[0].nome,
      detail: `Lado A: ${a.name} ↔ Lado B: ${b.name}` }] : []
  })
}
