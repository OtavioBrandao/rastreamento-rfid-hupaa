import type { DashboardData } from '../types/dashboard'

// Dados fictícios de desenvolvimento. Não representam equipamentos do hospital.
export const dashboardFixture: DashboardData = {
  summary: { registered: 12, recent: 8, outdated: 3, never: 1 },
  equipment: [
    { id: '1', name: 'Cadeira de Rodas 12', type: 'Cadeira de rodas', assetNumber: 'PAT-1042', epc: 'E2000017221101441890A001', zone: '4º andar › Centro Cirúrgico', detectedAgo: 'há 2 minutos', status: 'recent' },
    { id: '2', name: 'Bomba de Infusão 08', type: 'Bomba de infusão', assetNumber: 'PAT-2087', epc: 'E2000017221101441890A002', zone: '3º andar › UTI Adulto', detectedAgo: 'há 8 minutos', status: 'recent' },
    { id: '3', name: 'Maca 07', type: 'Maca', assetNumber: 'PAT-3170', epc: 'E2000017221101441890A003', zone: '4º andar › Corredor Principal', detectedAgo: 'há 38 minutos', status: 'outdated' },
    { id: '4', name: 'Monitor Multiparamétrico 05', type: 'Monitor', assetNumber: 'PAT-2205', epc: 'E2000017221101441890A004', zone: '2º andar › Enfermaria', detectedAgo: 'há 1 hora', status: 'outdated' },
    { id: '5', name: 'Carrinho de Emergência 03', type: 'Carrinho de emergência', assetNumber: 'PAT-4013', epc: 'E2000017221101441890A005', zone: null, detectedAgo: null, status: 'never' },
  ],
}
