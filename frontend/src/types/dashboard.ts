export type DetectionStatus = 'recent' | 'outdated' | 'never'

export interface EquipmentItem {
  id: string
  name: string
  type: string
  assetNumber: string
  epc: string
  zone: string | null
  detectedAgo: string | null
  status: DetectionStatus
}

export interface DashboardData {
  summary: {
    registered: number
    recent: number
    outdated: number
    never: number
  }
  equipment: EquipmentItem[]
}
