export type DetectionStatus = 'recent' | 'outdated' | 'never'
export type OperationalStatus = 'available' | 'attention' | 'offline' | 'critical'

export interface RfidReading {
  antenna: string
  portal: string
  timestamp: string
}

export interface EquipmentItem {
  id: string
  name: string
  type: string
  assetNumber: string
  epc: string
  zone: string | null
  detectedAgo: string | null
  status: DetectionStatus
  operationalStatus: OperationalStatus
  department: string
  facility: string
  room: string | null
  manufacturer: string
  serialNumber: string
  lastInspection: string | null
  nextMaintenance: string | null
  readings: RfidReading[]
  mapZoneId: string | null
  mapX: number | null
  mapY: number | null
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
