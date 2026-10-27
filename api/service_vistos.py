"""Onde o equipamento foi visto sem confirmação de zona ("visto perto da Zona X").

Uma leitura numa antena diz que a tag esteve perto daquela antena, não que entrou
na zona: a zona só é confirmada por transição (passagem pelos dois lados de um
portal). Para o histórico não ficar mudo até a primeira transição, as leituras são
agrupadas em *visitas* — leituras seguidas perto da mesma zona, sem silêncio maior
que ``SILENCIO_S`` — calculadas das leituras gravadas, sem tabela nova.

Entram no histórico só as visitas que acrescentam informação: perto de uma zona
diferente da confirmada naquele momento (ou sem zona confirmada ainda). A visita
que é a própria evidência de uma transição confirmada não é repetida.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.timestamps import em_utc
from db.models import AssociacaoTagEquipamento, HistoricoMovimentacao, Tag, Zona

SILENCIO_S = 60
MARGEM_TRANSICAO = timedelta(seconds=5)


def visitas(db: Session, equipamento_id: int, *, limite: int = 30) -> list[dict]:
    """Visitas sem confirmação de zona, da mais recente para a mais antiga."""
    vinculos = db.execute(select(Tag.epc, AssociacaoTagEquipamento.inicio, AssociacaoTagEquipamento.fim)
                          .join(Tag, Tag.id == AssociacaoTagEquipamento.tag_id)
                          .where(AssociacaoTagEquipamento.equipamento_id == equipamento_id)).all()
    if not vinculos:
        return []
    linhas = db.execute(text("""
        WITH l AS (
            SELECT lb.lido_em, a.zona_associada_id AS zona, a.porta_numero AS porta, le.reader_id,
                   lag(a.zona_associada_id) OVER w AS zona_ant, lag(lb.lido_em) OVER w AS em_ant
              FROM leituras_brutas lb
              JOIN antenas a ON a.id = lb.antena_id
              JOIN leitores le ON le.id = a.leitor_id
              JOIN unnest(CAST(:epcs AS varchar[]), CAST(:inicios AS timestamptz[]),
                          CAST(:fins AS timestamptz[])) AS v(epc, inicio, fim)
                ON lb.epc = v.epc AND lb.lido_em >= v.inicio AND (v.fim IS NULL OR lb.lido_em < v.fim)
            WINDOW w AS (ORDER BY lb.lido_em)),
        marcadas AS (
            SELECT *, CASE WHEN zona_ant IS DISTINCT FROM zona
                             OR lido_em - em_ant > make_interval(secs => :silencio) THEN 1 ELSE 0 END AS novo
              FROM l),
        grupos AS (SELECT *, sum(novo) OVER (ORDER BY lido_em) AS g FROM marcadas)
        SELECT min(lido_em) AS inicio, max(lido_em) AS fim, count(*) AS leituras, min(zona) AS zona,
               (array_agg(reader_id ORDER BY lido_em))[1] AS leitor,
               (array_agg(porta ORDER BY lido_em))[1] AS porta
          FROM grupos GROUP BY g ORDER BY min(lido_em) DESC LIMIT :limite
    """), {"epcs": [v.epc for v in vinculos], "inicios": [v.inicio for v in vinculos],
           "fins": [v.fim for v in vinculos], "silencio": SILENCIO_S, "limite": limite * 4}).all()
    if not linhas:
        return []
    movimentos = db.execute(select(HistoricoMovimentacao.movimentada_em, HistoricoMovimentacao.zona_destino_id)
                            .where(HistoricoMovimentacao.equipamento_id == equipamento_id,
                                   HistoricoMovimentacao.movimentada_em.is_not(None))
                            .order_by(HistoricoMovimentacao.movimentada_em)).all()
    nomes = dict(db.execute(select(Zona.id, Zona.nome).where(
        Zona.id.in_({linha.zona for linha in linhas} | {m.zona_destino_id for m in movimentos}))).all())
    saida = []
    for visita in linhas:
        anteriores = [m for m in movimentos if m.movimentada_em <= visita.inicio]
        confirmada = anteriores[-1].zona_destino_id if anteriores else None
        if visita.zona == confirmada:
            continue  # perto da zona onde já está confirmado: nada de novo
        if any(m.zona_destino_id == visita.zona
               and visita.inicio - MARGEM_TRANSICAO <= m.movimentada_em <= visita.fim + MARGEM_TRANSICAO
               for m in movimentos):
            continue  # é a evidência da própria transição confirmada
        saida.append({
            "inicio": em_utc(visita.inicio), "fim": em_utc(visita.fim), "leituras": visita.leituras,
            "zona": nomes.get(visita.zona), "leitor": visita.leitor, "porta": visita.porta,
            "zona_confirmada_no_momento": nomes.get(confirmada) if confirmada else None,
        })
        if len(saida) >= limite:
            break
    return saida
