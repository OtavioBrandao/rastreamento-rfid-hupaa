"""Histórico do equipamento em percursos: origem → destino, com as etapas e as evidências.

Nos portais de entrada das zonas (``portais.modo = 'entrada'``) o lado A é a
circulação e o lado B é a zona. Cada passagem confirmada vira uma etapa:

- ``Zona 1 → Circulação`` (antenas 2 → 1): saiu da zona;
- ``Circulação → Zona 2`` (antenas 1 → 2): entrou na zona.

O percurso junta as duas etapas: ``Zona 1 → Zona 2``. Enquanto só a saída está
confirmada, o percurso fica incompleto (``Zona 1 → Circulação``). Uma entrada sem
saída registrada usa a última localização confirmada como origem (por exemplo,
"Outro andar (elevador)"); sem nenhuma, a origem é desconhecida e nada é inventado.

Correções manuais são acontecimentos próprios, identificados como tais. As
observações ("visto perto da Zona X", em ``service_vistos``) entram na lista como
observação, sem deslocamento. Horários e durações vêm só do que foi gravado: o
horário da movimentação e o das leituras que a passagem usou como evidência.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from api import service_vistos
from api.timestamps import em_utc
from db.models import Antena, HistoricoMovimentacao, Leitor, LeituraBruta, Portal, Zona

ROTULO_CIRCULACAO = "Circulação"
ORIGEM_DESCONHECIDA = "Origem desconhecida"


def zonas_de_circulacao(db: Session) -> set[int]:
    """Lado de fora dos portais de entrada: a circulação entre as zonas."""
    return set(db.scalars(select(Portal.zona_a_id).where(Portal.modo == "entrada")))


def nomes_dos_leitores(db: Session) -> dict[str, str]:
    """Nome amigável do leitor ("Leitor 1") pelos layouts do simulador; senão o reader_id."""
    from db.models import SimulacaoLayout

    nomes: dict[str, str] = {}
    for configuracao in db.scalars(select(SimulacaoLayout.configuracao).order_by(SimulacaoLayout.id)):
        for leitor in (configuracao or {}).get("leitores", []):
            if leitor.get("reader_id") and leitor.get("nome"):
                nomes[leitor["reader_id"]] = leitor["nome"]
    return nomes


def _segundos(inicio: datetime | None, fim: datetime | None) -> float | None:
    """Duração entre dois instantes gravados; sem um deles, não há duração."""
    if inicio is None or fim is None:
        return None
    return round((fim - inicio).total_seconds(), 1)


def _movimentos(db: Session, equipamento_id: int) -> list:
    """Movimentações em ordem cronológica, com nomes, portal e as duas leituras de evidência."""
    origem, destino = aliased(Zona), aliased(Zona)
    leitura_o, leitura_d = aliased(LeituraBruta), aliased(LeituraBruta)
    antena_o, antena_d = aliased(Antena), aliased(Antena)
    leitor_o, leitor_d = aliased(Leitor), aliased(Leitor)
    return db.execute(
        select(HistoricoMovimentacao.id, HistoricoMovimentacao.zona_origem_id,
               HistoricoMovimentacao.zona_destino_id, HistoricoMovimentacao.movimentada_em,
               HistoricoMovimentacao.registrado_em, HistoricoMovimentacao.origem_registro,
               HistoricoMovimentacao.justificativa, HistoricoMovimentacao.referencia,
               HistoricoMovimentacao.passagem_id,
               origem.nome.label("origem"), destino.nome.label("destino"),
               Portal.nome.label("portal"), Portal.modo.label("portal_modo"),
               leitura_o.lido_em.label("lido_origem"), leitura_d.lido_em.label("lido_destino"),
               antena_o.porta_numero.label("porta_origem"), antena_d.porta_numero.label("porta_destino"),
               leitor_o.reader_id.label("leitor_origem"), leitor_d.reader_id.label("leitor_destino"))
        .outerjoin(origem, origem.id == HistoricoMovimentacao.zona_origem_id)
        .join(destino, destino.id == HistoricoMovimentacao.zona_destino_id)
        .outerjoin(Portal, Portal.id == HistoricoMovimentacao.portal_id)
        .outerjoin(leitura_o, leitura_o.id == HistoricoMovimentacao.leitura_origem_id)
        .outerjoin(leitura_d, leitura_d.id == HistoricoMovimentacao.leitura_destino_id)
        .outerjoin(antena_o, antena_o.id == leitura_o.antena_id)
        .outerjoin(antena_d, antena_d.id == leitura_d.antena_id)
        .outerjoin(leitor_o, leitor_o.id == antena_o.leitor_id)
        .outerjoin(leitor_d, leitor_d.id == antena_d.leitor_id)
        .where(HistoricoMovimentacao.equipamento_id == equipamento_id)
        .order_by(HistoricoMovimentacao.movimentada_em.asc().nulls_first(), HistoricoMovimentacao.id)
    ).all()


def percursos(db: Session, equipamento_id: int, *, limite: int = 200) -> dict:
    """Acontecimentos do equipamento, do mais recente ao mais antigo, e a última observação.

    Cada acontecimento tem ``tipo`` (``percurso``, ``correcao`` ou ``observacao``),
    ``titulo`` (origem → destino) e ``em`` (instante do acontecimento). O percurso
    traz ``etapas`` com portal, leitor, antenas na ordem lida e horários das leituras.
    """
    circulacao = zonas_de_circulacao(db)
    leitores = nomes_dos_leitores(db)

    def nome(zona_id: int | None, nome_zona: str | None) -> str | None:
        """Circulação aparece como tal; as demais zonas pelo nome cadastrado."""
        if zona_id is None:
            return None
        return ROTULO_CIRCULACAO if zona_id in circulacao else nome_zona

    def etapa(m) -> dict:
        """Uma passagem confirmada (ou correção) com as evidências gravadas."""
        antenas = []
        if m.porta_origem is not None:
            antenas.append({"porta": m.porta_origem, "lido_em": em_utc(m.lido_origem)})
        if m.porta_destino is not None:
            antenas.append({"porta": m.porta_destino, "lido_em": em_utc(m.lido_destino)})
        leitor = m.leitor_destino or m.leitor_origem
        return {
            "movimentacao_id": m.id, "de": nome(m.zona_origem_id, m.origem) or ORIGEM_DESCONHECIDA,
            "para": nome(m.zona_destino_id, m.destino), "em": em_utc(m.movimentada_em),
            "portal": m.portal, "leitor": leitores.get(leitor, leitor) if leitor else None,
            "antenas": antenas,
            "ordem": " → ".join(str(a["porta"]) for a in antenas) if len(antenas) == 2 else None,
            "travessia_s": _segundos(m.lido_origem, m.lido_destino),
            "origem_registro": m.origem_registro,
        }

    eventos: list[dict] = []
    atual: tuple[int, str] | None = None  # última localização confirmada (id, nome)
    aberto: dict | None = None
    for m in _movimentos(db, equipamento_id):
        if m.origem_registro != "passagem_automatica":
            aberto = None
            origem = nome(m.zona_origem_id, m.origem)
            eventos.append({
                "tipo": "correcao", "titulo": f"{origem or ORIGEM_DESCONHECIDA} → {nome(m.zona_destino_id, m.destino)}",
                "origem": origem, "destino": nome(m.zona_destino_id, m.destino),
                "em": em_utc(m.movimentada_em or m.registrado_em),
                "justificativa": m.justificativa, "referencia": m.referencia, "completo": True,
                "etapas": [etapa(m)],
            })
            atual = (m.zona_destino_id, m.destino)
            continue
        sai = m.zona_destino_id in circulacao and m.zona_origem_id not in circulacao
        entra = m.zona_origem_id in circulacao and m.zona_destino_id not in circulacao
        if sai:
            aberto = {"tipo": "percurso", "origem": nome(m.zona_origem_id, m.origem), "destino": ROTULO_CIRCULACAO,
                      "em": em_utc(m.movimentada_em), "completo": False, "saida_registrada": True,
                      "etapas": [etapa(m)], "tempo_na_circulacao_s": None}
            eventos.append(aberto)
        elif entra and aberto is not None:
            aberto["etapas"].append(etapa(m))
            aberto.update(destino=nome(m.zona_destino_id, m.destino), em=em_utc(m.movimentada_em), completo=True,
                          tempo_na_circulacao_s=_segundos(aberto["etapas"][0]["em"], em_utc(m.movimentada_em)))
            aberto = None
        elif entra:
            # Entrou sem saída registrada: a origem é a última localização confirmada
            # (ex.: "Outro andar (elevador)"); sem nenhuma, fica desconhecida.
            origem = atual[1] if atual is not None and atual[0] not in circulacao else None
            eventos.append({"tipo": "percurso", "origem": origem, "destino": nome(m.zona_destino_id, m.destino),
                            "em": em_utc(m.movimentada_em), "completo": True, "saida_registrada": False,
                            "etapas": [etapa(m)], "tempo_na_circulacao_s": None})
        else:  # portal entre duas zonas (direcional): uma etapa só
            aberto = None
            eventos.append({"tipo": "percurso", "origem": nome(m.zona_origem_id, m.origem),
                            "destino": nome(m.zona_destino_id, m.destino), "em": em_utc(m.movimentada_em),
                            "completo": True, "saida_registrada": True, "etapas": [etapa(m)],
                            "tempo_na_circulacao_s": None})
        atual = (m.zona_destino_id, m.destino)
    for evento in eventos:
        if evento["tipo"] == "percurso":
            evento["titulo"] = f"{evento['origem'] or ORIGEM_DESCONHECIDA} → {evento['destino']}"
            evento["mesma_zona"] = evento["completo"] and evento["origem"] == evento["destino"]

    for visto in service_vistos.visitas(db, equipamento_id, limite=limite):
        eventos.append({
            "tipo": "observacao", "titulo": f"Visto perto da {visto['zona'] or 'antena'}",
            "em": visto["fim"], "inicio": visto["inicio"], "fim": visto["fim"], "zona": visto["zona"],
            "leitor": visto["leitor"], "porta": visto["porta"], "leituras": visto["leituras"],
            "zona_confirmada_no_momento": visto["zona_confirmada_no_momento"], "completo": False,
        })
    eventos.sort(key=lambda evento: evento["em"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    em_circulacao = atual is not None and atual[0] in circulacao
    return {"items": eventos[:limite], "em_circulacao": em_circulacao,
            "ultima_observacao": service_vistos.ultima_observacao(db, equipamento_id)}
