import { describe, expect, it } from 'vitest'
import { labMainZones, labPortals } from '../config/mapaConfig'
import { bindPortals, bindZones, belongsToZone, type MapTopology } from '../services/mapTopology'
import type { EquipmentItem } from '../types/dashboard'

const topology: MapTopology = {
  zones: [{ id: 31, nome: 'Sala A', referencia_planta: 'sala-a', ativo: true },
    { id: 82, nome: 'Sala B', referencia_planta: 'sala-b', ativo: true }],
  portals: [{ id: 907, nome: 'Portal de teste RFID', zona_a_id: 31, zona_b_id: 82, ativo: true }],
}
describe('vínculos da planta com o cadastro', () => {
  it('resolve os IDs reais, sem depender de IDs do seed', () => {
    const zones = bindZones(labMainZones, topology.zones)
    expect(zones.map((zone) => zone.zoneId)).toEqual([31, 82])
    expect(bindPortals(labPortals, topology, zones)[0]).toMatchObject({ portalId: 907, x: 50, y: 54 })
  })
  it('não escolhe uma zona quando a referência é inexistente, inativa ou ambígua', () => {
    expect(bindZones(labMainZones, [])).toEqual([])
    expect(bindZones(labMainZones, topology.zones.map((zone) => ({ ...zone, ativo: false })))).toEqual([])
    const duplicate = { ...topology.zones[0], id: 999 }
    expect(bindZones(labMainZones, [...topology.zones, duplicate]).map((zone) => zone.zoneId)).toEqual([82])
  })
  it('exige ID e referência da mesma zona e não posiciona nunca detectados', () => {
    const zone = bindZones(labMainZones, topology.zones)[0]
    const item = { status: 'disponivel', ultima_zona: { id: 31, referencia_planta: 'sala-a' } } as EquipmentItem
    expect(belongsToZone(item, zone)).toBe(true)
    expect(belongsToZone({ ...item, ultima_zona: { ...item.ultima_zona!, id: 999 } }, zone)).toBe(false)
    expect(belongsToZone({ ...item, status: 'nunca_detectado' }, zone)).toBe(false)
  })
  it('rejeita portais ausentes, inativos, ambíguos ou com lados incompatíveis', () => {
    const zones = bindZones(labMainZones, topology.zones)
    for (const portals of [[], [{ ...topology.portals[0], ativo: false }],
      [{ ...topology.portals[0], zona_a_id: 82, zona_b_id: 31 }],
      [topology.portals[0], { ...topology.portals[0], id: 908 }]]) {
      expect(bindPortals(labPortals, { ...topology, portals }, zones)).toEqual([])
    }
    expect(bindPortals(labPortals, topology, zones.slice(0, 1))).toEqual([])
  })
  it('permite substituir a posição e usar portalId explícito sem alterar componentes', () => {
    const config = [{ ...labPortals[0], portalId: 907, portalName: undefined, x: 12, y: 34 }]
    expect(bindPortals(config, topology, bindZones(labMainZones, topology.zones))[0]).toMatchObject({ portalId: 907, x: 12, y: 34 })
  })
})
