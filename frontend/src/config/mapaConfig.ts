// Planta esquemática reproduzida a partir do contorno fornecido pela equipe.
// Todas as coordenadas usam o viewBox 0–100. As três zonas principais são
// provisórias; as cores abaixo são somente o contexto arquitetônico da figura.
export interface MapZone {
  id: string
  name: string
  color: string
  path: string
}

export interface MainZone {
  id: string
  name: string
  x: number
  y: number
  description: string
}

export interface InfrastructurePosition {
  id: string
  type: 'antenna' | 'reader'
  x: number
  y: number
  room: string
  label: string
}

// Contorno preto: ala superior contínua, volume verde à esquerda, ligação
// central e bloco inferior. O fundo e as faixas são recortados por este path.
export const hospitalOutlinePath = 'M13 1 H100 V49 H52 V70 H61 V100 H12 V70 H42 V49 H13 V29 H10 V50 H0 V29 H5 L8 22 H13 Z'

export const hospitalContextAreas: MapZone[] = [
  { id: 'atendimento', name: 'Permanência / atendimento', color: '#FFCA08', path: 'M13 1 H100 V49 H13 Z' },
  { id: 'servico', name: 'Serviço', color: '#F31217', path: 'M21 1 H24 V49 H21 Z M40 1 H43 V37 H40 Z M72 1 H84 V29 H72 Z M82 29 H85 V37 H82 Z M42 50 H49 V60 H42 Z' },
  { id: 'administrativo', name: 'Administrativo', color: '#633937', path: 'M42 49 H49 V58 H42 Z M20 70 H49 V90 H20 Z' },
  { id: 'vertical', name: 'Circulação vertical', color: '#00E820', path: 'M0 29 H10 V50 H0 Z M52 29 H58 V49 H52 Z M42 60 H49 V70 H42 Z M12 70 H20 V90 H12 Z' },
  { id: 'institucional', name: 'Institucional / sala de aula', color: '#12BCE8', path: 'M52 70 H61 V100 H52 Z' },
  { id: 'horizontal', name: 'Circulação horizontal', color: '#67008F', path: 'M5 29 L8 22 H13 V22 H95 V29 H52 V100 H49 V29 H10 V35 H5 Z M12 90 H49 V100 H12 Z M93 19 H95 V30 H93 Z' },
]

// Apenas três áreas principais estão definidas no protótipo. Os nomes finais,
// limites funcionais e eventuais zonas extras serão decididos com a equipe.
export const hospitalMainZones: MainZone[] = [
  { id: 'zona-1', name: 'Zona 1', x: 31, y: 15, description: 'Ala superior esquerda e acesso lateral' },
  { id: 'zona-2', name: 'Zona 2', x: 73, y: 42, description: 'Ala superior direita' },
  { id: 'zona-3', name: 'Zona 3', x: 35, y: 83, description: 'Bloco inferior e ligação central' },
]

// Hardware do laboratório: posição ajustável sem alterar FloorMap.
export const labInfrastructure: InfrastructurePosition[] = [
  { id: 'ANT-A', type: 'antenna', x: 28, y: 66, room: 'Sala A', label: 'Antena A' },
  { id: 'LEITOR-01', type: 'reader', x: 50, y: 66, room: 'Divisória', label: 'Leitor 01' },
  { id: 'ANT-B', type: 'antenna', x: 72, y: 66, room: 'Sala B', label: 'Antena B' },
]
