import type { DashboardData, EquipmentItem } from '../types/dashboard'

// TODO(API): substituir por consulta operacional paginada com status, recência,
// última zona e histórico. Todos os registros abaixo são fictícios.
function item(base: Pick<EquipmentItem, 'id' | 'name' | 'type' | 'assetNumber' | 'epc' | 'zone' | 'detectedAgo' | 'status'>, extra: Partial<EquipmentItem> = {}): EquipmentItem {
  return {
    operationalStatus: 'available', department: 'Engenharia clínica', facility: 'HUPAA (demonstração)',
    room: null, manufacturer: 'Não informado', serialNumber: 'Não informado',
    lastInspection: null, nextMaintenance: null, readings: [],
    mapZoneId: null, mapX: null, mapY: null, ...base, ...extra,
  }
}

const reading = (antenna: string, portal: string, timestamp: string) => ({ antenna, portal, timestamp })

export const dashboardFixture: DashboardData = {
  summary: { registered: 12, recent: 8, outdated: 3, never: 1 },
  equipment: [
    item({ id: '1', name: 'Cadeira de Rodas 12', type: 'Cadeira de rodas', assetNumber: 'PAT-1042', epc: 'E2000017221101441890A001', zone: '4º andar › Centro Cirúrgico', detectedAgo: 'há 2 minutos', status: 'recent' }, { department: 'Centro Cirúrgico', manufacturer: 'Fabricante demonstrativo', serialNumber: 'CR-1042', lastInspection: '12/08/2026', nextMaintenance: '12/11/2026', readings: [reading('Antena CC-01', 'Portal Centro Cirúrgico', '26/09/2026 09:42')] }),
    item({ id: '2', name: 'Bomba de Infusão 08', type: 'Bomba de infusão', assetNumber: 'PAT-2087', epc: 'E2000017221101441890A002', zone: '3º andar › UTI Adulto', detectedAgo: 'há 8 minutos', status: 'recent' }, { department: 'UTI Adulto', operationalStatus: 'attention', manufacturer: 'Fabricante demonstrativo', serialNumber: 'BI-2087', nextMaintenance: '30/09/2026', readings: [reading('Antena UTI-02', 'Portal UTI', '26/09/2026 09:36')] }),
    item({ id: '3', name: 'Maca 07', type: 'Maca', assetNumber: 'PAT-3170', epc: 'E2000017221101441890A003', zone: '4º andar › Corredor Principal', detectedAgo: 'há 38 minutos', status: 'outdated' }, { department: 'Centro Cirúrgico', operationalStatus: 'offline', readings: [reading('Antena CC-02', 'Portal Corredor', '26/09/2026 09:06')] }),
    item({ id: '4', name: 'Monitor Multiparamétrico 05', type: 'Monitor', assetNumber: 'PAT-2205', epc: 'E2000017221101441890A004', zone: '2º andar › Enfermaria', detectedAgo: 'há 1 hora', status: 'outdated' }, { department: 'Enfermaria', operationalStatus: 'attention', mapZoneId: 'atendimento', mapX: 79, mapY: 52, readings: [reading('Antena ENF-01', 'Portal Enfermaria', '26/09/2026 08:44')] }),
    item({ id: '5', name: 'Carrinho de Emergência 03', type: 'Carrinho de emergência', assetNumber: 'PAT-4013', epc: 'E2000017221101441890A005', zone: null, detectedAgo: null, status: 'never' }, { operationalStatus: 'offline' }),
    item({ id: '6', name: 'Bomba de Infusão 14', type: 'Bomba de infusão', assetNumber: 'PAT-2104', epc: 'E2000017221101441890A006', zone: '2º andar › Atendimento', detectedAgo: 'há 4 minutos', status: 'recent' }, { department: 'Atendimento', mapZoneId: 'atendimento', mapX: 34, mapY: 38, manufacturer: 'Fabricante demonstrativo', serialNumber: 'BI-2104', lastInspection: '10/08/2026', nextMaintenance: '10/11/2026', readings: [reading('Antena AT-01', 'Portal Atendimento', '26/09/2026 09:40')] }),
    item({ id: '7', name: 'Oxímetro Portátil 02', type: 'Oxímetro', assetNumber: 'PAT-1612', epc: 'E2000017221101441890A007', zone: '2º andar › Atendimento', detectedAgo: 'há 6 minutos', status: 'recent' }, { department: 'Atendimento', mapZoneId: 'atendimento', mapX: 69, mapY: 35, readings: [reading('Antena AT-02', 'Portal Atendimento', '26/09/2026 09:38')] }),
    item({ id: '8', name: 'Cadeira de Rodas 19', type: 'Cadeira de rodas', assetNumber: 'PAT-1059', epc: 'E2000017221101441890A008', zone: '2º andar › Circulação horizontal', detectedAgo: 'há 12 minutos', status: 'recent' }, { department: 'Apoio', mapZoneId: 'horizontal', mapX: 49, mapY: 51, readings: [reading('Antena CH-01', 'Portal Corredor', '26/09/2026 09:32')] }),
    item({ id: '9', name: 'Desfibrilador 04', type: 'Desfibrilador', assetNumber: 'PAT-3304', epc: 'E2000017221101441890A009', zone: '2º andar › Serviço', detectedAgo: 'há 15 minutos', status: 'recent' }, { department: 'Serviço', operationalStatus: 'critical', mapZoneId: 'servico', mapX: 67, mapY: 18, nextMaintenance: '25/09/2026', readings: [reading('Antena SV-01', 'Portal Serviço', '26/09/2026 09:29')] }),
    item({ id: '10', name: 'Maca 11', type: 'Maca', assetNumber: 'PAT-3184', epc: 'E2000017221101441890A010', zone: '2º andar › Atendimento', detectedAgo: 'há 22 minutos', status: 'recent' }, { department: 'Atendimento', mapZoneId: 'atendimento', mapX: 82, mapY: 30, readings: [reading('Antena AT-02', 'Portal Atendimento', '26/09/2026 09:22')] }),
    item({ id: '11', name: 'Monitor Multiparamétrico 09', type: 'Monitor', assetNumber: 'PAT-2209', epc: 'E2000017221101441890A011', zone: '2º andar › Administrativo', detectedAgo: 'há 27 minutos', status: 'recent' }, { department: 'Administrativo', operationalStatus: 'attention', mapZoneId: 'administrativo', mapX: 34, mapY: 82, readings: [reading('Antena ADM-01', 'Portal Administrativo', '26/09/2026 09:17')] }),
    item({ id: '12', name: 'Bomba de Infusão 21', type: 'Bomba de infusão', assetNumber: 'PAT-2121', epc: 'E2000017221101441890A012', zone: '2º andar › Circulação vertical', detectedAgo: 'há 2 horas', status: 'outdated' }, { department: 'Apoio', mapZoneId: 'vertical', mapX: 15, mapY: 43, readings: [reading('Antena CV-01', 'Portal Elevadores', '26/09/2026 07:44')] }),
  ],
}
