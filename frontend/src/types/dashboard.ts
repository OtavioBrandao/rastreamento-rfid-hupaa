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
  referencia?: string | null  // ISS-025: chamado/OS da correção manual
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
  ultima_leitura?: LastReading | null
}

/** Última leitura bruta da tag: presença na antena, não zona confirmada. */
export interface LastReading {
  em: string
  leitor?: string | null
  porta?: number | null
  zona?: string | null
}

export interface ReadAntenna { antena_id: number; leitor: string; porta: number; zona: string | null }

export interface ReadSummaryItem {
  epc: string
  cadastrada: boolean
  equipamento: { id: number; nome: string; identificador_interno: string; ultima_zona: string | null; ultima_zona_em: string | null } | null
  leituras: number
  leituras_por_antena: { antena_id: number; leituras: number }[]
  ultima_leitura: LastReading | null
}

export interface ReadSummary {
  janela_segundos: number
  gerado_em: string
  total_leituras: number
  tags_detectadas: number
  cadastradas_detectadas: number
  cadastradas_sem_leitura: number
  nao_cadastradas: number
  antenas: ReadAntenna[]
  items: ReadSummaryItem[]
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
