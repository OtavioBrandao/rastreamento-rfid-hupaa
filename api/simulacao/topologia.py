"""Aplica um layout do simulador ao cadastro de topologia usado pelo pipeline.

O ingestor só aceita leituras de leitor/porta cadastrados, e a inferência
interpreta lado A/B pelos mapeamentos versionados (ISS-013). Por isso iniciar
uma simulação cadastra (ou atualiza) zonas, portais, leitores virtuais,
antenas e mapeamentos — exatamente como um técnico faria para um leitor real.

Isolamento:
- Leitores virtuais têm `reader_id` com prefixo `sim-` e serial
  `SIM-L<layout>-<reader_id>`: o vínculo com o layout fica no próprio
  cadastro. Um `reader_id` já usado por leitor físico ou por outro layout
  ativo é recusado, para duas simulações nunca publicarem pelo mesmo leitor.
  Excluir (arquivar) um layout desliga os leitores dele (`liberar`), e o
  primeiro layout ativo que usar o mesmo `reader_id` assume o leitor.
- HUPAA usa um andar próprio ("Simulação HUPAA") e um setor por layout; EASY
  reaproveita as zonas e o portal do laboratório (mesmo cadastro do launcher).

Mudanças de mapeamento encerram o anterior (`fim`) e abrem outro, preservando
o histórico temporal. Nada é apagado. Tudo roda na transação do chamador.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.normalizacao import normalizar_nome
from db.models import (
    Andar,
    Antena,
    Leitor,
    MapeamentoAntenaPortal,
    Portal,
    Setor,
    SimulacaoLayout,
    Zona,
)

from .esquema import MODELOS_LEITOR, Layout
from .presets import ANDAR_SIMULACAO_HUPAA

FABRICANTE_VIRTUAL = "Simulador web EASY/UFAL"


class TopologiaRecusada(ValueError):
    """O layout não pode ser aplicado sem afetar outro cadastro."""


def serial_virtual(layout_id: int, reader_id: str) -> str:
    """Serial do leitor virtual; o prefixo `SIM-` identifica a fonte simulada."""
    return f"SIM-L{layout_id}-{reader_id}"


def destino(layout_id: int, layout: Layout) -> tuple[str, str]:
    """Andar e setor onde as zonas do layout são cadastradas."""
    if layout.destino is not None:
        return layout.destino.andar, layout.destino.setor
    return ANDAR_SIMULACAO_HUPAA, f"Layout #{layout_id}"


def _por_nome(session: Session, modelo, nome: str, **filtros):
    """Busca pela chave normalizada, como os CRUDs de localização."""
    return session.scalar(select(modelo).filter_by(
        nome_normalizado=normalizar_nome(nome), **filtros))


def _setor(session: Session, andar_nome: str, setor_nome: str) -> Setor:
    """Encontra ou cria andar e setor de destino, reativando se preciso."""
    andar = _por_nome(session, Andar, andar_nome)
    if andar is None:
        andar = Andar(nome=andar_nome, nome_normalizado=normalizar_nome(andar_nome))
        session.add(andar)
        session.flush()
    andar.ativo = True
    setor = _por_nome(session, Setor, setor_nome, andar_id=andar.id)
    if setor is None:
        setor = Setor(andar_id=andar.id, nome=setor_nome,
                      nome_normalizado=normalizar_nome(setor_nome))
        session.add(setor)
        session.flush()
    setor.ativo = True
    return setor


def _encerrar_mapeamento(session: Session, antena_id: int, agora: datetime) -> None:
    """Fecha o mapeamento ativo da antena, se houver."""
    ativo = session.scalar(select(MapeamentoAntenaPortal).where(
        MapeamentoAntenaPortal.antena_id == antena_id, MapeamentoAntenaPortal.fim.is_(None)))
    if ativo is not None:
        ativo.fim = agora


def aplicar(session: Session, registro: SimulacaoLayout, layout: Layout) -> dict:
    """Cadastra/atualiza a topologia do layout e devolve os ids por chave."""
    agora = datetime.now(timezone.utc)
    anteriores = registro.vinculos or {}
    vinculos: dict[str, dict[str, int]] = {"zonas": {}, "portais": {}, "leitores": {},
                                           "antenas": {}}
    andar_nome, setor_nome = destino(registro.id, layout)
    setor = _setor(session, andar_nome, setor_nome)

    for zona_layout in layout.zonas:
        zona = None
        anterior = anteriores.get("zonas", {}).get(zona_layout.chave)
        if anterior is not None:
            zona = session.get(Zona, anterior)
            if zona is not None and zona.setor_id != setor.id:
                zona = None
        if zona is None:
            zona = _por_nome(session, Zona, zona_layout.nome, setor_id=setor.id)
        referencia = zona_layout.referencia_planta or f"sim-{zona_layout.chave}"
        if zona is None:
            zona = Zona(setor_id=setor.id, nome=zona_layout.nome,
                        nome_normalizado=normalizar_nome(zona_layout.nome),
                        referencia_planta=referencia)
            session.add(zona)
        elif zona.nome != zona_layout.nome:
            if _por_nome(session, Zona, zona_layout.nome, setor_id=setor.id) not in (None, zona):
                raise TopologiaRecusada(f"já existe outra zona '{zona_layout.nome}' no setor")
            zona.nome = zona_layout.nome
            zona.nome_normalizado = normalizar_nome(zona_layout.nome)
        zona.ativo = True
        if zona.referencia_planta in (None, f"sim-{zona_layout.chave}") or layout.cenario == "hupaa":
            zona.referencia_planta = referencia
        session.flush()
        vinculos["zonas"][zona_layout.chave] = zona.id
    if layout.cenario == "hupaa":
        # Setor exclusivo do layout: zona removida do desenho deixa de ser ativa.
        for zona in session.scalars(select(Zona).where(Zona.setor_id == setor.id)):
            if zona.id not in vinculos["zonas"].values():
                zona.ativo = False

    for portal_layout in layout.portais:
        zona_a = vinculos["zonas"][portal_layout.zona_a]
        zona_b = vinculos["zonas"][portal_layout.zona_b]
        portal = None
        anterior = anteriores.get("portais", {}).get(portal_layout.chave)
        if anterior is not None:
            portal = session.get(Portal, anterior)
        if portal is None:
            portal = session.scalar(select(Portal).where(
                Portal.nome == portal_layout.nome, Portal.zona_a_id == zona_a,
                Portal.zona_b_id == zona_b).order_by(Portal.ativo.desc(), Portal.id))
        if portal is None:
            portal = Portal(nome=portal_layout.nome, zona_a_id=zona_a, zona_b_id=zona_b,
                            localizacao_fisica="Simulação web")
            session.add(portal)
        else:
            portal.nome = portal_layout.nome
            portal.zona_a_id, portal.zona_b_id = zona_a, zona_b
        portal.ativo = True
        session.flush()
        vinculos["portais"][portal_layout.chave] = portal.id
    if layout.cenario == "hupaa":
        for chave, portal_id in anteriores.get("portais", {}).items():
            if portal_id not in vinculos["portais"].values():
                portal = session.get(Portal, portal_id)
                if portal is not None:
                    portal.ativo = False

    leitores_do_layout = set()
    for leitor_layout in layout.leitores:
        serial = serial_virtual(registro.id, leitor_layout.reader_id)
        modelo = f"{MODELOS_LEITOR[leitor_layout.modelo]['nome'].removeprefix('Identix ')} (virtual)"
        leitor = session.scalar(select(Leitor).where(Leitor.reader_id == leitor_layout.reader_id))
        if leitor is not None and leitor.identificador_serial != serial:
            if not leitor.identificador_serial.startswith("SIM-"):
                raise TopologiaRecusada(f"identificador lógico '{leitor_layout.reader_id}' já é "
                                        "usado por um leitor físico")
            dono = _layout_dono(session, leitor.identificador_serial)
            if dono is not None and not dono.arquivado:
                raise TopologiaRecusada(
                    f"o identificador lógico '{leitor_layout.reader_id}' já é usado pelo layout "
                    f"“{dono.nome}”; troque o identificador deste leitor ou exclua aquele layout")
            # Layout dono excluído: o leitor virtual passa para este layout. Os mapeamentos
            # antigos são encerrados logo abaixo, ao versionar cada antena.
            leitor.identificador_serial = serial
        if leitor is None:
            leitor = Leitor(reader_id=leitor_layout.reader_id, fabricante=FABRICANTE_VIRTUAL,
                            modelo=modelo, identificador_serial=serial,
                            parametros_ingestao={"adapter": "ez700"})
            session.add(leitor)
        leitor.modelo = modelo
        leitor.ativo = True
        session.flush()
        leitores_do_layout.add(leitor.id)
        vinculos["leitores"][leitor_layout.chave] = leitor.id

        portas = set()
        for antena_layout in leitor_layout.antenas:
            portas.add(antena_layout.porta)
            zona_id = vinculos["zonas"][antena_layout.zona]
            portal_id = (vinculos["portais"][antena_layout.portal]
                         if antena_layout.portal else None)
            funcao = {"a": "entrada", "b": "saida"}.get(antena_layout.lado or "", "indefinido")
            antena = session.scalar(select(Antena).where(
                Antena.leitor_id == leitor.id, Antena.porta_numero == antena_layout.porta,
                Antena.ativo.is_(True)))
            if antena is None:
                antena = Antena(leitor_id=leitor.id, porta_numero=antena_layout.porta,
                                zona_associada_id=zona_id, funcao=funcao, portal_id=portal_id)
                session.add(antena)
                session.flush()
            mapeamento = session.scalar(select(MapeamentoAntenaPortal).where(
                MapeamentoAntenaPortal.antena_id == antena.id,
                MapeamentoAntenaPortal.fim.is_(None)))
            desejado = ((portal_id, antena_layout.lado, zona_id, funcao)
                        if portal_id is not None else None)
            atual = ((mapeamento.portal_id, mapeamento.lado, mapeamento.zona_id, mapeamento.funcao)
                     if mapeamento is not None else None)
            antena.zona_associada_id, antena.portal_id, antena.funcao = zona_id, portal_id, funcao
            if desejado != atual:
                if mapeamento is not None:
                    mapeamento.fim = agora
                    session.flush()
                if desejado is not None:
                    session.add(MapeamentoAntenaPortal(
                        antena_id=antena.id, portal_id=portal_id, lado=antena_layout.lado,
                        zona_id=zona_id, funcao=funcao, inicio=agora))
            session.flush()
            vinculos["antenas"][antena_layout.chave] = antena.id
        for antena in session.scalars(select(Antena).where(
                Antena.leitor_id == leitor.id, Antena.ativo.is_(True))):
            if antena.porta_numero not in portas:
                _encerrar_mapeamento(session, antena.id, agora)
                antena.ativo = False

    # Leitores virtuais deste layout que saíram do desenho: inativos, sem mapeamento.
    _desligar_leitores(session, registro.id, agora, manter=leitores_do_layout)

    session.flush()
    registro.vinculos = vinculos
    registro.aplicado_em = agora
    return vinculos


def _layout_dono(session: Session, serial: str) -> SimulacaoLayout | None:
    """Layout que cadastrou o leitor virtual, pelo serial `SIM-L<id>-...`."""
    numero = serial.removeprefix("SIM-L").split("-", 1)[0]
    return session.get(SimulacaoLayout, int(numero)) if numero.isdigit() else None


def _desligar_leitores(session: Session, layout_id: int, agora: datetime,
                       manter: set[int] = frozenset()) -> None:
    """Inativa os leitores virtuais do layout (exceto `manter`) e encerra os mapeamentos."""
    for leitor in session.scalars(select(Leitor).where(
            Leitor.identificador_serial.like(f"SIM-L{layout_id}-%"))):
        if leitor.id in manter:
            continue
        for antena in session.scalars(select(Antena).where(Antena.leitor_id == leitor.id,
                                                           Antena.ativo.is_(True))):
            _encerrar_mapeamento(session, antena.id, agora)
            antena.ativo = False
        leitor.ativo = False


def liberar(session: Session, registro: SimulacaoLayout) -> None:
    """Layout excluído: leitores virtuais saem de operação e ficam livres para outro layout."""
    _desligar_leitores(session, registro.id, datetime.now(timezone.utc))
    session.flush()
