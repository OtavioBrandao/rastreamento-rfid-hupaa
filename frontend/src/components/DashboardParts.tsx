import type { AssetStatus, EquipmentItem, LastReading } from '../types/dashboard'

const labels: Record<AssetStatus, string> = {
  disponivel: 'Em trânsito', atencao: 'Atenção necessária', offline: 'Offline',
  fora_de_servico: 'Fora de serviço', nunca_detectado: 'Nunca detectado',
}

export function StatusBadge({ status }: { status: AssetStatus }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>
}

export function LocationBadge({ item }: { item: EquipmentItem }) {
  return item.localizacao_desatualizada
    ? <span className="status-badge status-outdated">Localização pode estar desatualizada</span>
    : null
}

export function detectionLabel(value: string | null) {
  return value ? new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Maceio',
  }).format(new Date(value)) : 'Sem detecção'
}

/** Verde de "leitura recente": 90 s desde a última leitura em qualquer antena; cada
 * leitura nova recomeça a contagem. Só visual: não muda a janela de 5 min das listas
 * de leituras, a inferência de passagem nem os alertas. */
export const PRESENCE_FRESH_MS = 90_000

export function isFresh(reading: LastReading | null | undefined, now = Date.now()) {
  return !!reading && now - new Date(reading.em).getTime() <= PRESENCE_FRESH_MS
}

export function ageLabel(value: string | null | undefined, now = Date.now()) {
  if (!value) return 'Sem leitura'
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000))
  if (seconds < 60) return `há ${seconds} s`
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`
  return detectionLabel(value)
}

export function antennaLabel(reading: LastReading | null | undefined) {
  if (!reading) return 'Sem leitura'
  const antenna = reading.porta != null ? `Antena ${reading.porta}` : 'Antena desconhecida'
  return reading.zona ? `${antenna} · ${reading.zona}` : antenna
}

export function PresenceBadge({ reading }: { reading: LastReading | null | undefined }) {
  return isFresh(reading)
    ? <span className="status-badge status-presente">Leitura recente · {antennaLabel(reading)}</span>
    : <span className="status-badge status-ausente" title={reading ? `Última leitura ${ageLabel(reading.em)}` : 'Nunca lida'}>Sem leitura recente</span>
}

/** Ponto verde (até 90 s da última leitura) ou cinza, com o texto correspondente. */
export function PresenceDot({ reading }: { reading: LastReading | null | undefined }) {
  const fresh = isFresh(reading)
  return <><span className={fresh ? 'presence-dot fresh' : 'presence-dot'} aria-hidden="true"/>{fresh ? antennaLabel(reading) : 'Sem leitura recente'}</>
}

/** "Nunca detectado" só vale sem zona confirmada E sem nenhuma leitura bruta. */
/** Sem transição confirmada, mas lido: onde foi visto (perto da antena), não onde está. */
export function zonaNaoConfirmada(item: EquipmentItem) {
  if (item.ultima_zona || !item.ultima_leitura) return null
  const perto = item.ultima_leitura.zona ? `perto da ${item.ultima_leitura.zona}` : 'perto de uma antena'
  return `Zona não confirmada · visto ${perto} (${detectionLabel(item.ultima_leitura.em)})`
}

export function AssetStatusBadge({ item }: { item: EquipmentItem }) {
  if (item.status === 'nunca_detectado' && item.ultima_leitura) {
    return <span className="status-badge status-sem_zona" title="Lido por uma antena, mas a zona só é confirmada por transição">Zona não confirmada</span>
  }
  return <StatusBadge status={item.status}/>
}
