export type AssetStatus = 'disponivel' | 'atencao' | 'offline' | 'fora_de_servico' | 'nunca_detectado'

export interface AssetZone {
  id: number
  nome: string
  referencia_planta: string | null
  andar: string
  setor: string
  caminho: string
}

export interface MovementItem {
  id: number
  origem_registro: string
  zona_origem: string | null
  zona_destino: string
  movimentada_em: string | null
  registrado_em: string
  justificativa: string | null
}

export interface MovementPage {
  items: MovementItem[]
  page: number
  size: number
  total: number
  pages: number
}

export interface EquipmentItem {
  id: number
  nome: string
  identificador_interno: string
  tipo: string
  tipo_id: number
  epc: string | null
  status: AssetStatus
  ultima_zona: AssetZone | null
  ultima_deteccao_em: string | null
  localizacao_desatualizada: boolean | null
}

export interface AssetPage {
  items: EquipmentItem[]
  total: number
  page: number
  page_size: number
}

export interface AssetFilters {
  q?: string
  tipo?: number
  epc?: string
  status?: AssetStatus
  zona?: number
  page?: number
  page_size?: number
  sort?: 'nome' | '-nome' | 'ultima_deteccao_em' | '-ultima_deteccao_em'
}

export interface FilterOption { id: number; nome: string }

export interface OverviewSummary {
  registered: number
  disponivel: number
  atencao: number
  fora_de_servico: number
  nunca_detectado: number
}

export interface ActivityItem {
  id: number
  equipamento_id: number
  equipamento_nome: string
  zona_origem: string | null
  zona_destino: string
  movimentada_em: string
  origem_registro: string
}
