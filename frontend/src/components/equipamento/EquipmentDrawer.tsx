import { useEffect, useRef } from 'react'
import type { EquipmentItem, OperationalStatus } from '../../types/dashboard'
import { Icon } from '../layout/Icon'
import { StatusBadge } from '../DashboardParts'

const statusText: Record<OperationalStatus, string> = {
  available: 'Disponível', attention: 'Atenção necessária', offline: 'Offline', critical: 'Fora de serviço',
}
const statusIcon: Record<OperationalStatus, 'check' | 'alert' | 'clock'> = {
  available: 'check', attention: 'alert', offline: 'clock', critical: 'alert',
}

export function OperationalBadge({ status }: { status: OperationalStatus }) {
  return <span className={`operational-badge operational-${status}`}><Icon name={statusIcon[status]} size={14}/>{statusText[status]}</span>
}

function Detail({ label, value }: { label: string; value: string | null }) {
  return <div className="drawer-detail"><dt>{label}</dt><dd>{value ?? 'Não informado'}</dd></div>
}

export function EquipmentDrawer({ item, onClose }: { item: EquipmentItem | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!item) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'Tab') {
        const drawer = closeRef.current?.closest('[role="dialog"]')
        const controls = drawer?.querySelectorAll<HTMLElement>('button, a, input, select, [tabindex]:not([tabindex="-1"])')
        if (!controls?.length) return
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus() }
  }, [item, onClose])
  if (!item) return null
  return <div className="drawer-root">
    <button className="drawer-backdrop" type="button" aria-label="Fechar detalhes" onClick={onClose}/>
    <aside className="equipment-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <div className="drawer-top"><span className="eyebrow">DETALHE DO EQUIPAMENTO</span><button ref={closeRef} className="icon-button" type="button" aria-label="Fechar painel" onClick={onClose}><Icon name="close"/></button></div>
      <div className="drawer-title-row"><span className="drawer-equipment-icon"><Icon name="equipment" size={26}/></span><div><h2 id="drawer-title">{item.name}</h2><p>{item.type} · {item.assetNumber}</p></div></div>
      <div className="drawer-badges"><OperationalBadge status={item.operationalStatus}/><StatusBadge status={item.status}/></div>
      <p className="drawer-caveat">Localização aproximada pela última detecção. O equipamento pode estar em outro local.</p>
      <section><h3>Identificação e localização</h3><dl className="drawer-details"><Detail label="Unidade" value={item.facility}/><Detail label="Departamento" value={item.department}/><Detail label="Última zona detectada" value={item.zone ?? 'Nenhuma localização registrada'}/><Detail label="Sala" value={item.room}/><Detail label="Última detecção" value={item.detectedAgo}/><Detail label="Conectividade" value={item.operationalStatus === 'offline' ? 'Offline' : 'Condição não integrada à API'}/></dl></section>
      <section><h3>Manutenção</h3><dl className="drawer-details"><Detail label="Fabricante" value={item.manufacturer}/><Detail label="Número de série" value={item.serialNumber}/><Detail label="Última inspeção" value={item.lastInspection}/><Detail label="Próxima manutenção" value={item.nextMaintenance}/></dl></section>
      <section><h3>Últimas leituras RFID <span className="demo-tag">demonstração</span></h3>{item.readings.length ? <ol className="reading-list">{item.readings.map((reading, index) => <li key={`${reading.timestamp}-${index}`}><span className="reading-dot"/><div><strong>{reading.portal}</strong><p>{reading.antenna} · {reading.timestamp}</p></div></li>)}</ol> : <p className="muted">Nenhuma leitura registrada.</p>}</section>
    </aside>
  </div>
}
