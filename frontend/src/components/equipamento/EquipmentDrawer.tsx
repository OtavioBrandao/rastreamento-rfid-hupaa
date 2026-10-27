import { useEffect, useRef, useState } from 'react'
import { getAsset, getMovements, getSightings } from '../../services/dashboard'
import type { EquipmentItem } from '../../types/dashboard'
import { useLiveQuery, useLiveRefresh } from '../../services/live'
import { AssetStatusBadge, LocationBadge, PresenceBadge, ageLabel, antennaLabel, detectionLabel, zonaNaoConfirmada } from '../DashboardParts'
import { Icon } from '../layout/Icon'
import { CorrectionPanel, type CorrectionMode } from './CorrectionPanel'
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
  const [historyPage, setHistoryPage] = useState(1)
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
  const historyQuery = useLiveQuery(item && historyOpen ? `history:${item.id}:${historyPage}` : null,
    (signal) => getMovements(item!.id, historyPage, signal))
  const history = historyQuery.data
  // Onde foi visto sem confirmar zona: entra no histórico, separado das movimentações confirmadas.
  const sightings = useLiveQuery(item && historyOpen ? `sightings:${item.id}` : null, (signal) => getSightings(item!.id, signal)).data ?? []
  const historyState = historyQuery.loading ? 'loading' : historyQuery.error ? 'error' : 'ready'
  useEffect(() => {
    setHistoryOpen(false)
    setHistoryPage(1)
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
        <div className="drawer-detail"><dt>Última leitura da tag</dt><dd>{item.ultima_leitura ? `${antennaLabel(item.ultima_leitura)} · ${ageLabel(item.ultima_leitura.em)}` : 'Nenhuma leitura registrada'}</dd></div>
      </dl></section>
      <section aria-labelledby="history-title"><h3 id="history-title">Histórico de movimentações</h3>
        <button className="text-button" type="button" onClick={() => setHistoryOpen((open) => !open)}>{historyOpen ? 'Ocultar histórico' : 'Ver histórico completo'}</button>
        {historyOpen && <div className="movement-history">
          {historyState === 'loading' && <p role="status">Carregando histórico...</p>}
          {historyState === 'error' && <p role="alert">Não foi possível carregar o histórico. Tentando novamente automaticamente.</p>}
          {history && <>
            {history.items.length || (historyPage === 1 && sightings.length) ? <ol>{[
              ...history.items.map((movement) => ({ chave: `m${movement.id}`, em: movement.movimentada_em ?? movement.registrado_em, conteudo: <>
                <strong>{movement.zona_origem ?? 'Origem não registrada'} → {movement.zona_destino}</strong>
                <span>{movement.movimentada_em ? detectionLabel(movement.movimentada_em) : 'Horário da movimentação indisponível'}</span>
                {movement.origem_registro === 'correcao_manual' && <small>Correção manual{movement.justificativa ? `: ${movement.justificativa}` : ''}{movement.referencia ? ` (ref. ${movement.referencia})` : ''}</small>}
              </>, visto: false })),
              ...(historyPage === 1 ? sightings : []).map((visto) => ({ chave: `v${visto.inicio}`, em: visto.inicio, visto: true, conteudo: <>
                <strong>Visto perto da {visto.zona ?? 'antena'}</strong>
                <span>{detectionLabel(visto.inicio)} · {visto.leitor}, porta {visto.porta} · {visto.leituras} leitura(s)</span>
                <small>Não confirma a zona: {visto.zona_confirmada_no_momento ? `a zona confirmada continuava ${visto.zona_confirmada_no_momento}` : 'ainda sem zona confirmada'}; só uma transição confirma.</small>
              </> })),
            ].sort((a, b) => Date.parse(b.em) - Date.parse(a.em)).map((entrada) => <li key={entrada.chave} className={entrada.visto ? 'history-visto' : undefined}>{entrada.conteudo}</li>)}</ol> : <p>Nenhuma movimentação registrada.</p>}
            {history.pages > 1 && <nav aria-label="Páginas do histórico"><button type="button" disabled={historyPage <= 1} onClick={() => setHistoryPage((page) => page - 1)}>Anterior</button><span>Página {history.page} de {history.pages}</span><button type="button" disabled={historyPage >= history.pages} onClick={() => setHistoryPage((page) => page + 1)}>Próxima</button></nav>}
          </>}
        </div>}
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
