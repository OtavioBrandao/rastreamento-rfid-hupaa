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
from sqlalchemy.orm import Session, aliased

from api.timestamps import em_utc
from db.models import AssociacaoTagEquipamento, HistoricoMovimentacao, LeituraBruta, Tag, Zona

# Na área de alcance o leitor lê sem parar (a cada ~0,2 s): 10 s sem leitura já é
# outra visita. Assim a aproximação sem entrada não se funde com a entrada logo depois.
SILENCIO_S = 10
MARGEM_TRANSICAO = timedelta(seconds=5)


# Leituras do equipamento (pelas etiquetas, só dentro de cada vínculo) com a zona de
# referência da antena: no portal de entrada, a zona do portal (lado B), também para a
# Antena 1, que fica do lado de fora — "visto perto da Zona 1", não "da Circulação".
_LEITURAS_SQL = """
    SELECT lb.lido_em, a.porta_numero AS porta, le.reader_id,
           COALESCE((SELECT p.zona_b_id FROM mapeamentos_antena_portal m
                       JOIN portais p ON p.id = m.portal_id
                      WHERE m.antena_id = a.id AND p.modo = 'entrada' AND m.inicio <= lb.lido_em
                        AND (m.fim IS NULL OR m.fim > lb.lido_em)
                      ORDER BY m.inicio DESC LIMIT 1), a.zona_associada_id) AS zona
      FROM leituras_brutas lb
      JOIN antenas a ON a.id = lb.antena_id
      JOIN leitores le ON le.id = a.leitor_id
      JOIN unnest(CAST(:epcs AS varchar[]), CAST(:inicios AS timestamptz[]),
                  CAST(:fins AS timestamptz[])) AS v(epc, inicio, fim)
        ON lb.epc = v.epc AND lb.lido_em >= v.inicio AND (v.fim IS NULL OR lb.lido_em < v.fim)
"""


def _vinculos(db: Session, equipamento_id: int) -> list:
    """Etiquetas que já foram do equipamento, com o período de cada vínculo."""
    return db.execute(select(Tag.epc, AssociacaoTagEquipamento.inicio, AssociacaoTagEquipamento.fim)
                      .join(Tag, Tag.id == AssociacaoTagEquipamento.tag_id)
                      .where(AssociacaoTagEquipamento.equipamento_id == equipamento_id)).all()


def _parametros(vinculos: list) -> dict:
    """Parâmetros de ``_LEITURAS_SQL``."""
    return {"epcs": [v.epc for v in vinculos], "inicios": [v.inicio for v in vinculos],
            "fins": [v.fim for v in vinculos]}


def ultima_observacao(db: Session, equipamento_id: int) -> dict | None:
    """Última leitura do equipamento em qualquer antena, com a zona de referência.

    É a última *observação*, separada da última localização confirmada: uma leitura
    isolada atualiza esta, nunca a zona do equipamento.
    """
    vinculos = _vinculos(db, equipamento_id)
    if not vinculos:
        return None
    linha = db.execute(text(f"SELECT * FROM ({_LEITURAS_SQL}) x ORDER BY lido_em DESC LIMIT 1"),
                       _parametros(vinculos)).one_or_none()
    if linha is None:
        return None
    from api.service_percursos import nomes_dos_leitores

    zona = db.get(Zona, linha.zona) if linha.zona is not None else None
    return {"em": em_utc(linha.lido_em), "zona": zona.nome if zona else None,
            "leitor": nomes_dos_leitores(db).get(linha.reader_id, linha.reader_id), "porta": linha.porta}


def visitas(db: Session, equipamento_id: int, *, limite: int = 30) -> list[dict]:
    """Visitas sem confirmação de zona, da mais recente para a mais antiga."""
    vinculos = _vinculos(db, equipamento_id)
    if not vinculos:
        return []
    linhas = db.execute(text(f"""
        WITH base AS ({_LEITURAS_SQL}),
        l AS (SELECT *, lag(zona) OVER w AS zona_ant, lag(lido_em) OVER w AS em_ant
                FROM base WINDOW w AS (ORDER BY lido_em)),
        marcadas AS (
            SELECT *, CASE WHEN zona_ant IS DISTINCT FROM zona
                             OR lido_em - em_ant > make_interval(secs => :silencio) THEN 1 ELSE 0 END AS novo
              FROM l),
        grupos AS (SELECT *, sum(novo) OVER (ORDER BY lido_em) AS g FROM marcadas)
        SELECT min(lido_em) AS inicio, max(lido_em) AS fim, count(*) AS leituras, min(zona) AS zona,
               (array_agg(reader_id ORDER BY lido_em))[1] AS leitor,
               (array_agg(porta ORDER BY lido_em))[1] AS porta
          FROM grupos GROUP BY g ORDER BY min(lido_em) DESC LIMIT :limite
    """), {**_parametros(vinculos), "silencio": SILENCIO_S, "limite": limite * 4}).all()
    if not linhas:
        return []
    origem, destino = aliased(LeituraBruta), aliased(LeituraBruta)
    movimentos = db.execute(select(HistoricoMovimentacao.movimentada_em, HistoricoMovimentacao.zona_destino_id,
                                   origem.lido_em.label("lido_origem"), destino.lido_em.label("lido_destino"))
                            .outerjoin(origem, origem.id == HistoricoMovimentacao.leitura_origem_id)
                            .outerjoin(destino, destino.id == HistoricoMovimentacao.leitura_destino_id)
                            .where(HistoricoMovimentacao.equipamento_id == equipamento_id,
                                   HistoricoMovimentacao.movimentada_em.is_not(None))
                            .order_by(HistoricoMovimentacao.movimentada_em)).all()
    from api.service_percursos import nomes_dos_leitores

    leitores = nomes_dos_leitores(db)
    nomes = dict(db.execute(select(Zona.id, Zona.nome).where(
        Zona.id.in_({linha.zona for linha in linhas} | {m.zona_destino_id for m in movimentos}))).all())
    saida = []
    for visita in linhas:
        anteriores = [m for m in movimentos if m.movimentada_em <= visita.inicio]
        confirmada = anteriores[-1].zona_destino_id if anteriores else None
        if visita.zona == confirmada:
            continue  # perto da zona onde já está confirmado: nada de novo
        if any((m.zona_destino_id == visita.zona
                and visita.inicio - MARGEM_TRANSICAO <= m.movimentada_em <= visita.fim + MARGEM_TRANSICAO)
               or any(lido is not None and visita.inicio <= lido <= visita.fim
                      for lido in (m.lido_origem, m.lido_destino))
               for m in movimentos):
            continue  # é a evidência de uma transição confirmada (entrada ou saída)
        saida.append({
            "inicio": em_utc(visita.inicio), "fim": em_utc(visita.fim), "leituras": visita.leituras,
            "zona": nomes.get(visita.zona), "leitor": leitores.get(visita.leitor, visita.leitor), "porta": visita.porta,
            "zona_confirmada_no_momento": nomes.get(confirmada) if confirmada else None,
        })
        if len(saida) >= limite:
            break
    return saida
