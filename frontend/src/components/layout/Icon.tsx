import type { ReactNode } from 'react'

export type IconName = 'dashboard' | 'map' | 'search' | 'equipment' | 'antenna' | 'reader' | 'portal' | 'refresh' | 'alert' | 'check' | 'clock' | 'close' | 'arrow' | 'layers' | 'question' | 'users' | 'audit'

const paths: Record<IconName, ReactNode> = {
  users: <><circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v3"/></>,
  audit: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
  portal: <><path d="M5 21V3h14v18M2 21h6M16 21h6M8 12h8m-3-3 3 3-3 3"/></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/></>,
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  map: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  equipment: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15h3l2-6 2 6h3M8 22h8"/></>,
  antenna: <><path d="M12 20v-9M8 20h8M12 7v.01"/><path d="M7.5 4.5a6.4 6.4 0 0 0 0 9M16.5 4.5a6.4 6.4 0 0 1 0 9M4 2a10 10 0 0 0 0 14M20 2a10 10 0 0 1 0 14"/></>,
  reader: <><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8M8 13h5M8 17h2"/></>,
  alert: <><path d="m12 3 10 18H2z"/><path d="M12 9v5M12 17v.01"/></>,
  check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  close: <><path d="M5 5 19 19M19 5 5 19"/></>,
  arrow: <><path d="M4 12h16m-7-7 7 7-7 7"/></>,
  layers: <><path d="m12 2 9 5-9 5-9-5zM3 12l9 5 9-5M3 17l9 5 9-5"/></>,
  question: <><path d="M9 9a3 3 0 1 1 5.4 1.8C12.9 12.1 12 12.6 12 14"/><path d="M12 18v.01"/></>,
}

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}
