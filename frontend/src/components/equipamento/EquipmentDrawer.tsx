import { useEffect, useRef } from 'react'
import type { EquipmentItem } from '../../types/dashboard'
import { LocationBadge, StatusBadge, detectionLabel } from '../DashboardParts'
import { Icon } from '../layout/Icon'

export function EquipmentDrawer({ item, onClose }: { item: EquipmentItem | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!item) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'Tab') {
        const controls = closeRef.current?.closest('[role="dialog"]')?.querySelectorAll<HTMLElement>('button, a, input, select')
        if (!controls?.length) return
        if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1].focus() }
        else if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0].focus() }
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
      <div className="drawer-title-row"><span className="drawer-equipment-icon"><Icon name="equipment" size={26}/></span><div><h2 id="drawer-title">{item.nome}</h2><p>{item.tipo} · {item.identificador_interno}</p></div></div>
      <div className="drawer-badges"><StatusBadge status={item.status}/><LocationBadge item={item}/></div>
      <p className="drawer-caveat">A última zona detectada é aproximada e não indica a posição atual exata.</p>
      <section><h3>Identificação e localização</h3><dl className="drawer-details">
        <div className="drawer-detail"><dt>EPC associado</dt><dd>{item.epc ?? 'Sem EPC associado'}</dd></div>
        <div className="drawer-detail"><dt>Última zona detectada</dt><dd>{item.ultima_zona?.nome ?? 'Nenhuma localização registrada'}</dd></div>
        <div className="drawer-detail"><dt>Última detecção</dt><dd>{detectionLabel(item.ultima_deteccao_em)}</dd></div>
      </dl></section>
    </aside>
  </div>
}
