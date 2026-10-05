import { useEffect, useRef, useState } from 'react'
import { getAsset, getMovements } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { useLiveQuery, useLiveRefresh } from '../../services/live'
import { AssetStatusBadge, LocationBadge, PresenceBadge, ageLabel, antennaLabel, detectionLabel } from '../DashboardParts'
import { Icon } from '../layout/Icon'
import { CorrectionPanel, type CorrectionMode } from './CorrectionPanel'

interface Props {
  item: EquipmentItem | null
  onClose: () => void
  /** Só o administrador (`equipamentos:corrigir`) vê a seção de correção (ISS-025). */
  canCorrect?: boolean
}

export function EquipmentDrawer({ item: selected, onClose, canCorrect = false }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyPage, setHistoryPage] = useState(1)
  const { refresh } = useLiveRefresh()
  const [correction, setCorrection] = useState<CorrectionMode | null>(null)
  const [correctionDone, setCorrectionDone] = useState<string | null>(null)
  // Recarrega pelo ID, identidade estável: o nome e o patrimônio podem ter sido
  // corrigidos (ISS-025), e uma busca textual pode não trazer o item na 1ª página.
  const detail = useLiveQuery(selected ? `detail:${selected.id}` : null,
    (signal) => getAsset(selected!.id, signal))
  const item = detail.data ?? selected
  const historyQuery = useLiveQuery(item && historyOpen ? `history:${item.id}:${historyPage}` : null,
    (signal) => getMovements(item!.id, historyPage, signal))
  const history = historyQuery.data
  const historyState = historyQuery.loading ? 'loading' : historyQuery.error ? 'error' : 'ready'
  useEffect(() => {
    setHistoryOpen(false)
    setHistoryPage(1)
    setCorrection(null)
    setCorrectionDone(null)
  }, [selected?.id])
  useEffect(() => {
    if (!item) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'Tab') {
        const controls = closeRef.current?.closest('[role="dialog"]')?.querySelectorAll<HTMLElement>('button, a, input, select, textarea')
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
      <div className="drawer-badges"><AssetStatusBadge item={item}/><LocationBadge item={item}/><PresenceBadge reading={item.ultima_leitura}/></div>
      <p className="drawer-caveat">A última zona detectada é aproximada e não indica a posição atual exata.</p>
      <section><h3>Identificação e localização</h3><dl className="drawer-details">
        <div className="drawer-detail"><dt>EPC associado</dt><dd>{item.epc ?? 'Sem EPC associado'}</dd></div>
        <div className="drawer-detail"><dt>Última zona detectada</dt><dd>{item.ultima_zona?.caminho ?? 'Nenhuma localização registrada'}</dd></div>
        <div className="drawer-detail"><dt>Última zona confirmada em (horário de Maceió)</dt><dd>{detectionLabel(item.ultima_deteccao_em)}</dd></div>
        <div className="drawer-detail"><dt>Última leitura da tag</dt><dd>{item.ultima_leitura ? `${antennaLabel(item.ultima_leitura)} · ${ageLabel(item.ultima_leitura.em)}` : 'Nenhuma leitura registrada'}</dd></div>
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
              {movement.origem_registro === 'correcao_manual' && <small>Correção manual{movement.justificativa ? `: ${movement.justificativa}` : ''}{movement.referencia ? ` (ref. ${movement.referencia})` : ''}</small>}
            </li>)}</ol> : <p>Nenhuma movimentação registrada.</p>}
            {history.pages > 1 && <nav aria-label="Páginas do histórico"><button type="button" disabled={historyPage <= 1} onClick={() => setHistoryPage((page) => page - 1)}>Anterior</button><span>Página {history.page} de {history.pages}</span><button type="button" disabled={historyPage >= history.pages} onClick={() => setHistoryPage((page) => page + 1)}>Próxima</button></nav>}
          </>}
        </div>}
      </section>
      {canCorrect && <section className="correction-section" aria-labelledby="correction-title"><h3 id="correction-title">Correção manual</h3>
        {correctionDone && <p className="correction-success" role="status">{correctionDone}</p>}
        {correction ? <CorrectionPanel key={correction} mode={correction} equipmentId={item.id}
          onCancel={() => setCorrection(null)}
          onDone={(message) => {
            setCorrection(null)
            setCorrectionDone(message)
            setHistoryPage(1)
            setHistoryOpen(true)
            // Atualização global (ISS-033): detalhe, histórico, lista e mapa sem esperar o ciclo.
            refresh()
          }}/> : <div className="correction-actions">
          <button type="button" className="correction-secondary" onClick={() => { setCorrectionDone(null); setCorrection('localizacao') }}>Corrigir localização</button>
          <button type="button" className="correction-secondary" onClick={() => { setCorrectionDone(null); setCorrection('cadastro') }}>Corrigir cadastro</button>
        </div>}
      </section>}
    </aside>
  </div>
}
