// Coordenadas percentuais no viewBox 0–100. Layout esquemático, sujeito a
// calibração após validação física das zonas e da posição do hardware.
export interface MapZone {
  id: string
  name: string
  type: string
  color: string
  path: string
}

export interface InfrastructurePosition {
  id: string
  type: 'antenna' | 'reader'
  x: number
  y: number
  room: string
  label: string
}

export const hospitalZones: MapZone[] = [
  { id: 'atendimento', name: 'Permanência / atendimento', type: 'atendimento', color: '#f3df99', path: 'M8 8 H92 V52 H59 V48 H44 V52 H8 Z M8 56 H46 V64 H35 V73 H8 Z' },
  { id: 'servico', name: 'Serviço', type: 'servico', color: '#f7b6ad', path: 'M64 8 H75 V28 H64 Z M34 8 H38 V39 H34 Z M82 32 H86 V44 H82 Z' },
  { id: 'administrativo', name: 'Administrativo', type: 'administrativo', color: '#b89891', path: 'M14 76 H42 V94 H14 Z' },
  { id: 'vertical', name: 'Circulação vertical', type: 'vertical', color: '#a9d9ae', path: 'M3 38 H13 V56 H3 Z M47 60 H53 V76 H47 Z M53 42 H61 V55 H53 Z M8 74 H14 V88 H8 Z' },
  { id: 'institucional', name: 'Institucional / sala de aula', type: 'institucional', color: '#a8d9ec', path: 'M53 74 H63 V94 H53 Z' },
  { id: 'horizontal', name: 'Circulação horizontal', type: 'horizontal', color: '#c1a1c8', path: 'M11 34 H88 V40 H56 V84 H50 V40 H11 Z M8 40 H11 V46 H4 V42 Z M8 88 H50 V94 H8 Z' },
]

export const labInfrastructure: InfrastructurePosition[] = [
  { id: 'ANT-A', type: 'antenna', x: 28, y: 66, room: 'Sala A', label: 'Antena A' },
  { id: 'LEITOR-01', type: 'reader', x: 50, y: 66, room: 'Divisória', label: 'Leitor 01' },
  { id: 'ANT-B', type: 'antenna', x: 72, y: 66, room: 'Sala B', label: 'Antena B' },
]

// Posições ilustrativas de portais hospitalares. A topologia real depende da
// calibração física e dos cadastros da API; não são coordenadas de equipamento.
export const hospitalAntennas: InfrastructurePosition[] = [
  { id: 'HUPAA-AT-01', type: 'antenna', x: 47, y: 36, room: 'Atendimento', label: 'Antena Atendimento' },
  { id: 'HUPAA-CV-01', type: 'antenna', x: 13, y: 53, room: 'Circulação vertical', label: 'Antena Elevadores' },
]
