import { useEffect, useRef, useState } from 'react'
import { getAsset, getJourneys } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { useLiveQuery, useLiveRefresh } from '../../services/live'
import { AssetStatusBadge, LocationBadge, PresenceBadge, PresenceDot, ageLabel, antennaLabel, detectionLabel, zonaNaoConfirmada } from '../DashboardParts'
import { Icon } from '../layout/Icon'
import { CorrectionPanel, type CorrectionMode } from './CorrectionPanel'
import { JourneyBlocks, JourneySummary } from './MovementJourneys'
import { errorMessage } from '../../services/api'
import { setInService } from '../../services/cadastro'

interface Props {
  item: EquipmentItem | null
  onClose: () => void
  /** Só o administrador (`equipamentos:corrigir`) vê a seção de correção (ISS-025). */
  canCorrect?: boolean
  /** Administrador (`equipamentos:alterar`): colocar fora de serviço ou reativar. */
  canChangeService?: boolean
}

export function EquipmentDrawer({ item: selected, onClose, canCorrect = false, canChangeService = false }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const { refresh } = useLiveRefresh()
  const [correction, setCorrection] = useState<CorrectionMode | null>(null)
  const [correctionDone, setCorrectionDone] = useState<string | null>(null)
  const [serviceMessage, setServiceMessage] = useState<string | null>(null)
  const [serviceBusy, setServiceBusy] = useState(false)
  // Recarrega pelo ID, identidade estável: o nome e o patrimônio podem ter sido
  // corrigidos (ISS-025), e uma busca textual pode não trazer o item na 1ª página.
  const detail = useLiveQuery(selected ? `detail:${selected.id}` : null,
    (signal) => getAsset(selected!.id, signal))
  const item = detail.data ?? selected
  // Resumo e histórico completo vêm da mesma consulta: percursos com as evidências.
  const journeys = useLiveQuery(item ? `journeys:${item.id}` : null, (signal) => getJourneys(item!.id, signal))
  const historyState = journeys.loading && !journeys.data ? 'loading' : journeys.error ? 'error' : 'ready'
  useEffect(() => {
    setHistoryOpen(false)
    setCorrection(null)
    setServiceMessage(null)
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
        <div className="drawer-detail"><dt>Última zona detectada</dt><dd>{item.ultima_zona?.caminho ?? zonaNaoConfirmada(item) ?? 'Nenhuma localização registrada'}</dd></div>
        <div className="drawer-detail"><dt>Última zona confirmada em (horário de Maceió)</dt><dd>{detectionLabel(item.ultima_deteccao_em)}</dd></div>
        <div className="drawer-detail"><dt>Última observação perto de uma antena</dt><dd>{journeys.data?.ultima_observacao
          ? `Perto da ${journeys.data.ultima_observacao.zona ?? 'antena'} · ${journeys.data.ultima_observacao.leitor ?? 'leitor'}, Antena ${journeys.data.ultima_observacao.porta ?? '?'} · ${detectionLabel(journeys.data.ultima_observacao.em)}`
          : 'Nenhuma leitura registrada'}<small>Não altera a localização confirmada.</small></dd></div>
        <div className="drawer-detail"><dt>Última leitura da tag</dt><dd><PresenceDot reading={item.ultima_leitura}/>{item.ultima_leitura ? <small>{antennaLabel(item.ultima_leitura)} · {ageLabel(item.ultima_leitura.em)}</small> : <small>Nenhuma leitura registrada</small>}</dd></div>
      </dl></section>
      <section aria-labelledby="history-title"><h3 id="history-title">Histórico de movimentações</h3>
        {historyState === 'loading' && <p role="status">Carregando histórico...</p>}
        {historyState === 'error' && <p role="alert">Não foi possível carregar o histórico. Tentando novamente automaticamente.</p>}
        {journeys.data && !journeys.error && <JourneySummary data={journeys.data}/>}
        <button className="text-button" type="button" onClick={() => setHistoryOpen((open) => !open)}>{historyOpen ? 'Ocultar histórico completo' : 'Ver histórico completo'}</button>
        {historyOpen && journeys.data && !journeys.error && <div className="movement-history"><JourneyBlocks data={journeys.data}/></div>}
      </section>
      {canChangeService && <section className="correction-section" aria-labelledby="service-title"><h3 id="service-title">Situação de serviço</h3>
        <p className="muted-text">{item.status === 'fora_de_servico'
          ? 'Fora de serviço: aparece em vermelho no mapa até ser reativado. A tag continua vinculada.'
          : 'Ex.: a maca quebrou ou a tag está danificada. O equipamento fica em vermelho no mapa e no dashboard; a tag continua vinculada e o histórico é mantido.'}</p>
        {serviceMessage && <p className="correction-success" role="status">{serviceMessage}</p>}
        <button type="button" className={item.status === 'fora_de_servico' ? 'correction-secondary' : 'danger'} disabled={serviceBusy}
          onClick={async () => {
            const voltar = item.status === 'fora_de_servico'
            if (!voltar && !window.confirm(`Colocar “${item.nome}” fora de serviço?`)) return
            setServiceBusy(true)
            try { await setInService(item.id, voltar); setServiceMessage(voltar ? `“${item.nome}” voltou ao serviço.` : `“${item.nome}” está fora de serviço.`); refresh() }
            catch (failure) { setServiceMessage(errorMessage(failure)) } finally { setServiceBusy(false) }
          }}>{item.status === 'fora_de_servico' ? 'Reativar (voltar ao serviço)' : 'Colocar fora de serviço'}</button>
      </section>}
      {canCorrect && <section className="correction-section" aria-labelledby="correction-title"><h3 id="correction-title">Correção manual</h3>
        {correctionDone && <p className="correction-success" role="status">{correctionDone}</p>}
        {correction ? <CorrectionPanel key={correction} mode={correction} equipmentId={item.id}
          onCancel={() => setCorrection(null)}
          onDone={(message) => {
            setCorrection(null)
            setCorrectionDone(message)
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
