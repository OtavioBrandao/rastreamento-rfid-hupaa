import { useEffect, useState, type ReactNode } from 'react'
import type { MapZone } from '../../config/mapaConfig'
import { belongsToZone, type BoundPortal, type BoundZone } from '../../services/mapTopology'
import type { AssetStatus, EquipmentItem } from '../../types/dashboard'
import { detectionLabel } from '../DashboardParts'
import { simboloDoTipo } from '../simulador/EquipIcon'
import { FloorMap, type MapMarker } from './FloorMap'
import { MapDataTabs, type ExtraTab } from './MapDataTabs'

/** Prioridade de alerta das categorias existentes: desempata a cor do ícone recolhido. */
export const PRIORIDADE_ALERTA: AssetStatus[] = ['fora_de_servico', 'atencao', 'offline', 'nunca_detectado', 'disponivel']
export const ROTULO_STATUS: Record<AssetStatus, string> = {
  disponivel: 'Disponível', atencao: 'Atenção', offline: 'Offline', fora_de_servico: 'Fora de serviço', nunca_detectado: 'Nunca detectado',
}

/** Cor do ícone recolhido: a categoria com mais equipamentos; empate vai para a de maior alerta. */
export function statusDominante(items: EquipmentItem[]): AssetStatus {
  const contagem = new Map<AssetStatus, number>()
  for (const item of items) contagem.set(item.status, (contagem.get(item.status) ?? 0) + 1)
  return [...PRIORIDADE_ALERTA].sort((a, b) => (contagem.get(b) ?? 0) - (contagem.get(a) ?? 0)
    || PRIORIDADE_ALERTA.indexOf(a) - PRIORIDADE_ALERTA.indexOf(b))[0]
}

/** Centro do ícone recolhido: o meio da área da zona, quando delimitada. */
export function centroDaZona(zone: BoundZone) {
  return zone.area ? { x: zone.area.x + zone.area.width / 2, y: zone.area.y + zone.area.height / 2 } : { x: zone.x, y: zone.y + 6 }
}

/** Posições legíveis dentro dos limites da zona (grade); são ilustrativas, não físicas. */
export function posicoesNaZona(zone: BoundZone, total: number) {
  const area = zone.area ?? { x: zone.x - 8, y: zone.y - 2, width: 16, height: 16 }
  const margemX = Math.min(area.width * 0.12, 4), margemY = Math.min(area.height * 0.15, 5)
  const largura = area.width - 2 * margemX, altura = area.height - 2 * margemY
  const colunas = Math.max(1, Math.round(Math.sqrt(total * (largura / Math.max(altura, 1)) * 0.5)))
  const linhas = Math.ceil(total / colunas)
  return Array.from({ length: total }, (_, i) => {
    const coluna = i % colunas, linha = Math.floor(i / colunas)
    const naLinha = linha === linhas - 1 ? total - linha * colunas : colunas
    return { x: area.x + margemX + (largura * (coluna + 0.5 + (colunas - naLinha) / 2)) / colunas, y: area.y + margemY + (altura * (linha + 0.5)) / linhas }
  })
}

/** Planta + abas compartilhando a zona selecionada. Os pontos não são posições físicas. */
export function MapWorkspace({ mode, zones, portals, items, onSelect, markers = [], areas = [], showEquipment = true, svgExtras, extraTabs = [], below, simplified, onZoneLabelMove }: {
  mode: 'hospital' | 'lab'; zones: BoundZone[]; portals: BoundPortal[]; items: EquipmentItem[]
  onSelect: (item: EquipmentItem) => void; markers?: MapMarker[]; areas?: MapZone[]; showEquipment?: boolean
  svgExtras?: ReactNode; extraTabs?: ExtraTab[]; below?: ReactNode
  simplified?: boolean; onZoneLabelMove?: (id: string, x: number, y: number) => void
}) {
  const [selectedId, setSelectedId] = useState('')
  // Se a topologia deixar de validar a zona, a seleção some junto com ela.
  const selectedZone = zones.find((zone) => zone.id === selectedId)
  const toggle = (id: string) => setSelectedId((old) => old === id ? '' : id)
  const close = () => setSelectedId('')
  // Clicar fora da zona expandida (nem nos seus ícones nem na lista dela) recolhe.
  useEffect(() => {
    if (!selectedId) return
    const fora = (event: PointerEvent) => {
      const alvo = event.target as Element | null
      if (!alvo?.closest('[data-zone-member], .sector-pin, .room-hit, .map-data, .equipment-drawer, [role="dialog"]')) setSelectedId('')
    }
    const esc = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedId('') }
    document.addEventListener('pointerdown', fora)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', fora); document.removeEventListener('keydown', esc) }
  }, [selectedId])
  const equipmentMarkers: MapMarker[] = showEquipment ? zones.flatMap((zone) => {
    const members = items.filter((item) => belongsToZone(item, zone))
    if (!members.length) return []
    const expandida = selectedZone?.id === zone.id
    const centro = centroDaZona(zone)
    const status = statusDominante(members)
    const recolhido: MapMarker = { id: `zona-${zone.id}`, kind: 'equipment', ...centro, count: members.length, status, selected: expandida,
      label: `${members.length} equipamento${members.length === 1 ? '' : 's'} em ${zone.name}`, detail: expandida ? 'Clique para recolher' : 'Clique para ver cada um',
      ariaLabel: `${members.length} equipamento${members.length === 1 ? '' : 's'} em ${zone.name}, maioria ${ROTULO_STATUS[status].toLowerCase()}. ${expandida ? 'Clique para recolher' : 'Clique para ver cada um'}` }
    if (!expandida) return [recolhido]
    const ordenados = [...members].sort((a, b) => PRIORIDADE_ALERTA.indexOf(a.status) - PRIORIDADE_ALERTA.indexOf(b.status) || a.nome.localeCompare(b.nome, 'pt-BR', { numeric: true }))
    const posicoes = posicoesNaZona(zone, ordenados.length + 1)
    // O primeiro lugar da grade fica com o ícone da zona (para recolher); os demais, com os itens.
    return [{ ...recolhido, ...posicoes[0] }, ...ordenados.map((item, i) => ({
      id: `eq-${item.id}`, kind: 'equipment' as const, ...posicoes[i + 1], status: item.status, symbol: simboloDoTipo(item.tipo, item.nome),
      label: item.nome, detail: `${ROTULO_STATUS[item.status]} · ${item.ultima_deteccao_em ? `última detecção ${detectionLabel(item.ultima_deteccao_em)}` : 'sem detecção'}`,
      ariaLabel: `${item.nome}: ${ROTULO_STATUS[item.status]}. Abrir detalhes`,
    }))]
  }) : []
  const portalMarkers: MapMarker[] = portals.map((portal) => ({ id: portal.id, portalId: portal.portalId, kind: 'portal', x: portal.x, y: portal.y,
    label: `${portal.name} · Portal #${portal.portalId}`, detail: portal.detail }))
  return <>
    <FloorMap mode={mode} zones={areas} mainZones={zones} selectedZoneId={selectedZone?.id} svgExtras={svgExtras} simplified={simplified} onZoneLabelMove={onZoneLabelMove}
      markers={[...markers, ...portalMarkers, ...equipmentMarkers]}
      onMarkerClick={(marker) => {
        if (marker.count !== undefined) toggle(marker.id.slice('zona-'.length))
        else if (marker.symbol) { const item = items.find((entry) => `eq-${entry.id}` === marker.id); if (item) onSelect(item) }
      }} onZoneClick={toggle} onBackgroundClick={close}/>
    {below}
    <p className="map-footnote">Cada zona mostra um ícone com a quantidade; clique para ver os equipamentos. A posição dentro da zona é ilustrativa: o sistema conhece a zona, não a coordenada exata.</p>
    <MapDataTabs mode={mode} zones={zones} portals={portals} items={items} onSelect={onSelect} selectedZone={selectedZone} onZone={toggle} onCloseZone={close} extraTabs={extraTabs}/>
  </>
}
