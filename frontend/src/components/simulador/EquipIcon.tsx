/** Símbolo do tipo de equipamento, para marcadores circulares compactos (20×20). */
export type TipoSimbolo = 'maca' | 'cadeira' | 'bomba' | 'monitor' | 'outro'

export function simboloDoTipo(tipo: string | null | undefined, nome = ''): TipoSimbolo {
  const texto = `${tipo ?? ''} ${nome}`.toLowerCase()
  if (/maca|leito|cama/.test(texto)) return 'maca'
  if (/cadeira/.test(texto)) return 'cadeira'
  if (/bomba|infus/.test(texto)) return 'bomba'
  if (/monitor|desfibr|ecg|ventil/.test(texto)) return 'monitor'
  return 'outro'
}

export function EquipIcon({ tipo, size = 14 }: { tipo: TipoSimbolo; size?: number }) {
  const comum = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  return <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
    {tipo === 'maca' && <g {...comum}><path d="M2 12h16M3 12V7M17 12v-2a2 2 0 0 0-2-2H8v4"/><circle cx="5" cy="15.5" r="1.5"/><circle cx="15" cy="15.5" r="1.5"/></g>}
    {tipo === 'cadeira' && <g {...comum}><circle cx="8" cy="13" r="4.5"/><path d="M7 3v6h6l2 6M13 9v-3"/></g>}
    {tipo === 'bomba' && <g {...comum}><path d="M10 2.5c3 4 5 6.5 5 9a5 5 0 0 1-10 0c0-2.5 2-5 5-9z"/><path d="M8 12.5h4M10 10.5v4"/></g>}
    {tipo === 'monitor' && <g {...comum}><rect x="2.5" y="3.5" width="15" height="10" rx="1.5"/><path d="M5 9h2.5l1.5-3 2 5 1.5-2H15M7 17h6"/></g>}
    {tipo === 'outro' && <g {...comum}><rect x="4" y="5" width="12" height="11" rx="1.5"/><path d="M7.5 5V3.5h5V5"/></g>}
  </svg>
}
