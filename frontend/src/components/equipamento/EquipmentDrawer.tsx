import { useEffect, useRef, useState } from 'react'
import { getAllAssets, getMovements } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { useLiveQuery } from '../../services/live'
import { LocationBadge, StatusBadge, detectionLabel } from '../DashboardParts'
import { Icon } from '../layout/Icon'

export function EquipmentDrawer({ item: selected, onClose }: { item: EquipmentItem | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyPage, setHistoryPage] = useState(1)
  const detail = useLiveQuery(selected ? `detail:${selected.id}` : null, async (signal) => {
    const result = await getAllAssets({ q: selected!.identificador_interno }, signal)
    const found = result.find((asset) => asset.id === selected!.id)
    if (!found) throw new Error('Equipamento não encontrado')
    return found
  })
  const item = detail.data ?? selected
  const historyQuery = useLiveQuery(item && historyOpen ? `history:${item.id}:${historyPage}` : null,
    (signal) => getMovements(item!.id, historyPage, signal))
  const history = historyQuery.data
  const historyState = historyQuery.loading ? 'loading' : historyQuery.error ? 'error' : 'ready'
  useEffect(() => {
    setHistoryOpen(false)
    setHistoryPage(1)
  }, [selected?.id])
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
  }, [item?.id, onClose])
  if (!item) return null
  return <div className="drawer-root">
    <button className="drawer-backdrop" type="button" aria-label="Fechar detalhes" onClick={onClose}/>
    <aside className="equipment-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <div className="drawer-top"><span className="eyebrow">DETALHE DO EQUIPAMENTO</span><button ref={closeRef} className="icon-button" type="button" aria-label="Fechar painel" onClick={onClose}><Icon name="close"/></button></div>
      <div className="drawer-title-row"><span className="drawer-equipment-icon"><Icon name="equipment" size={26}/></span><div><h2 id="drawer-title">{item.nome}</h2><p>{item.tipo} · {item.identificador_interno}</p></div></div>
      {detail.error && <p role="alert">Não foi possível atualizar os detalhes. Exibindo a última consulta; tentando novamente...</p>}
      <div className="drawer-badges"><StatusBadge status={item.status}/><LocationBadge item={item}/></div>
      <p className="drawer-caveat">A última zona detectada é aproximada e não indica a posição atual exata.</p>
      <section><h3>Identificação e localização</h3><dl className="drawer-details">
        <div className="drawer-detail"><dt>EPC associado</dt><dd>{item.epc ?? 'Sem EPC associado'}</dd></div>
        <div className="drawer-detail"><dt>Última zona detectada</dt><dd>{item.ultima_zona?.caminho ?? 'Nenhuma localização registrada'}</dd></div>
        <div className="drawer-detail"><dt>Última detecção (horário de Maceió)</dt><dd>{detectionLabel(item.ultima_deteccao_em)}</dd></div>
      </dl></section>
      <section aria-labelledby="history-title"><h3 id="history-title">Histórico de movimentações</h3>
        <button className="text-button" type="button" onClick={() => setHistoryOpen((open) => !open)}>{historyOpen ? 'Ocultar histórico' : 'Ver histórico completo'}</button>
        {historyOpen && <div className="movement-history">
          {historyState === 'loading' && <p role="status">Carregando histórico...</p>}
          {historyState === 'error' && <p role="alert">Não foi possível carregar o histórico. Tentando novamente automaticamente.</p>}
          {history && <>
            {history.items.length ? <ol>{history.items.map((movement) => <li key={movement.id}>
              <strong>{movement.zona_origem ?? 'Origem não registrada'} → {movement.zona_destino}</strong>
              <span>{movement.movimentada_em ? detectionLabel(movement.movimentada_em) : 'Horário da movimentação indisponível'}</span>
              {movement.origem_registro === 'correcao_manual' && <small>Correção manual{movement.justificativa ? `: ${movement.justificativa}` : ''}</small>}
            </li>)}</ol> : <p>Nenhuma movimentação registrada.</p>}
            {history.pages > 1 && <nav aria-label="Páginas do histórico"><button type="button" disabled={historyPage <= 1} onClick={() => setHistoryPage((page) => page - 1)}>Anterior</button><span>Página {history.page} de {history.pages}</span><button type="button" disabled={historyPage >= history.pages} onClick={() => setHistoryPage((page) => page + 1)}>Próxima</button></nav>}
          </>}
        </div>}
      </section>
    </aside>
  </div>
}
