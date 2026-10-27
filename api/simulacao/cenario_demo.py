"""Cenário padrão de demonstração do HU: 6 equipamentos antes, 9 ao iniciar, 11 no fim.

1. **Preparar** (também usado ao reiniciar): seis equipamentos cadastrados, dois em
   cada uma das três primeiras zonas comuns do layout padrão do HU, parados e com a
   última detecção antiga (correção manual justificada), para aparecerem em atenção
   pela regra de recência. A zona restrita começa vazia. Nenhuma sessão aberta.
2. **Iniciar**: a sessão do layout padrão começa com esses seis na planta (dentro das
   zonas, fora do alcance das antenas) e mais três equipamentos recém-cadastrados no
   centro do mapa, sem zona confirmada — nove no total.
3. Os dois itens seguintes são acrescentados à mão no controle, com etiqueta ainda
   não vinculada, e cadastrados pelo fluxo de cadastro por leitura: onze no total.
   Nada disso é automático.

Reiniciar volta sempre ao mesmo ponto: os equipamentos da rodada anterior (os nove
do cenário e os cadastrados a partir das etiquetas da sessão) recebem baixa lógica —
ficam inativos, sem etiqueta e com o identificador marcado ``-ARQ-`` — e o cenário é
recriado. Nada é apagado do banco; o histórico continua auditável. Recriar (em vez
de "voltar" a posição) evita que passagens antigas sejam reprojetadas no equipamento.

Nomes, tipos e EPCs ficam em ``EQUIPAMENTOS_ANTIGOS`` e ``EQUIPAMENTOS_NOVOS`` para
ajustar antes das apresentações.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api import service_cadastro
from api.normalizacao import normalizar_nome
from api.service_tipos_equipamento import criar as criar_tipo
from db.models import (
    AssociacaoTagEquipamento,
    Equipamento,
    Setor,
    SimulacaoLayout,
    SimulacaoSessao,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_location.recency import recency_threshold_from_env
from rfid_location.service import corrigir_localizacao

from . import relogio as relogio_sim
from . import service, topologia
from .geometria import antenas_do_layout, detectar
from .presets import NOMES_PRESET

PREFIXO_ID = "DEMO-HU-"
# (nome, tipo, EPC). Os seis antigos vão, em pares, para a 1ª, 2ª e 3ª zona comum.
EQUIPAMENTOS_ANTIGOS = [
    ("Bomba de infusão HU-01", "Bomba de infusão", "E2804C41000000000000A101"),
    ("Monitor multiparamétrico HU-02", "Monitor multiparamétrico", "E2804C41000000000000A102"),
    ("Maca HU-03", "Maca", "E2804C41000000000000A103"),
    ("Cadeira de rodas HU-04", "Cadeira de rodas", "E2804C41000000000000A104"),
    ("Desfibrilador HU-05", "Desfibrilador", "E2804C41000000000000A105"),
    ("Ventilador pulmonar HU-06", "Ventilador pulmonar", "E2804C41000000000000A106"),
]
EQUIPAMENTOS_NOVOS = [
    ("Maca HU-07", "Maca", "E2804C41000000000000A107"),
    ("Cadeira de rodas HU-08", "Cadeira de rodas", "E2804C41000000000000A108"),
    ("Bomba de infusão HU-09", "Bomba de infusão", "E2804C41000000000000A109"),
]
# Antiga o bastante para "atenção": o limite de recência mais esta folga.
FOLGA_ATENCAO = timedelta(hours=1, minutes=30)
JUSTIFICATIVA = "Cenário de demonstração do HU: posição inicial do equipamento parado"


def _identificador(indice: int) -> str:
    """Identificador interno estável do equipamento do cenário."""
    return f"{PREFIXO_ID}{indice:02d}"


def layout_padrao(db: Session) -> SimulacaoLayout:
    """Layout padrão do HU (o salvo com o nome do preset), o das apresentações."""
    registro = db.scalar(select(SimulacaoLayout).where(
        SimulacaoLayout.cenario == "hupaa", SimulacaoLayout.arquivado.is_(False),
        SimulacaoLayout.nome == NOMES_PRESET["hupaa"]).order_by(SimulacaoLayout.id.desc()))
    if registro is None:
        raise service.SimulacaoRecusada("sem_layout_padrao",
                                        f"salve o layout “{NOMES_PRESET['hupaa']}” no simulador")
    return registro


def _zonas_comuns(layout: dict) -> list[dict]:
    """As três primeiras zonas delimitadas que não são restritas."""
    zonas = [zona for zona in layout["zonas"] if zona.get("area") and not zona.get("restrita")]
    if len(zonas) < 3:
        raise service.SimulacaoRecusada("zonas_insuficientes",
                                        "o layout padrão precisa de três zonas comuns delimitadas")
    return zonas[:3]


def _tipo(db: Session, nome: str) -> int:
    """Tipo de equipamento pelo nome (criado se faltar)."""
    tipo = db.scalar(select(TipoEquipamento).where(
        TipoEquipamento.nome_normalizado == normalizar_nome(nome)))
    return tipo.id if tipo is not None else criar_tipo(db, nome).id


def _ativos_do_cenario(db: Session) -> dict[str, Equipamento]:
    """Equipamentos do cenário ainda não arquivados, pelo identificador."""
    linhas = db.scalars(select(Equipamento).where(
        Equipamento.identificador_interno.like(f"{PREFIXO_ID}%"),
        Equipamento.identificador_interno.not_like("%-ARQ-%"))).all()
    return {linha.identificador_interno: linha for linha in linhas}


def _dar_baixa(db: Session, equipamento: Equipamento, agora: datetime) -> None:
    """Baixa lógica: inativo, etiqueta liberada e identificador marcado como arquivado."""
    for vinculo in db.scalars(select(AssociacaoTagEquipamento).where(
            AssociacaoTagEquipamento.equipamento_id == equipamento.id,
            AssociacaoTagEquipamento.fim.is_(None))):
        vinculo.fim = agora
    sufixo = f"-ARQ-{agora:%Y%m%d%H%M%S}-{equipamento.id}"
    equipamento.status = "inativo"
    equipamento.identificador_interno = (equipamento.identificador_interno or f"ID-{equipamento.id}") + sufixo
    equipamento.identificador_interno_normalizado = normalizar_nome(equipamento.identificador_interno)


def _epcs_manuais(db: Session, layout_id: int) -> set[str]:
    """Etiquetas dos itens acrescentados à mão na última sessão do layout padrão."""
    sessao = db.scalar(select(SimulacaoSessao).where(SimulacaoSessao.layout_id == layout_id)
                       .order_by(SimulacaoSessao.id.desc()))
    do_cenario = {epc for _, _, epc in EQUIPAMENTOS_ANTIGOS + EQUIPAMENTOS_NOVOS}
    return {item["epc"] for item in (sessao.itens if sessao else []) if item.get("epc")} - do_cenario


def _cadastrar(db: Session, indice: int, nome: str, tipo: str, epc: str) -> Equipamento:
    """Cadastra pelo serviço normal; o vínculo começa no tempo da simulação.

    Com o relógio adiantado, as passagens da rodada anterior podem estar "depois"
    do agora real: o vínculo começando no agora simulado impede que elas sejam
    atribuídas ao equipamento recriado.
    """
    equipamento, _ = service_cadastro.cadastrar(db, nome=nome, tipo_id=_tipo(db, tipo),
                                                identificador_interno=_identificador(indice), epc=epc)
    inicio = relogio_sim.do_banco(db).agora(service._agora())
    for vinculo in db.scalars(select(AssociacaoTagEquipamento).where(
            AssociacaoTagEquipamento.equipamento_id == equipamento.id,
            AssociacaoTagEquipamento.fim.is_(None))):
        vinculo.inicio = max(vinculo.inicio, inicio)
    db.commit()
    return equipamento


def _ponto_na_zona(area: dict, layout: dict, ocupados: list[tuple[float, float]]) -> tuple[float, float]:
    """Ponto dentro da zona, fora do alcance das antenas e longe dos outros itens."""
    antenas, proporcao = antenas_do_layout(layout), float(layout["proporcao"])
    cx, cy = area["x"] + area["largura"] / 2, area["y"] + area["altura"] / 2
    for raio in [0.0] + [passo * 1.5 for passo in range(1, 30)]:
        voltas = 1 if raio == 0 else max(8, int(2 * math.pi * raio / 1.5))
        for indice in range(voltas):
            angulo = 2 * math.pi * indice / voltas
            x, y = round(cx + raio * math.cos(angulo) / proporcao, 3), round(cy + raio * math.sin(angulo), 3)
            dentro = (area["x"] + 1 <= x <= area["x"] + area["largura"] - 1
                      and area["y"] + 1 <= y <= area["y"] + area["altura"] - 1)
            if dentro and not detectar(x, y, antenas, proporcao) and all(
                    service.distancia_na_tela((x, y), outro, proporcao) >= service.DISTANCIA_ENTRE_ITENS
                    for outro in ocupados):
                return x, y
    return round(cx, 3), round(cy, 3)


def preparar(db: Session, *, encerrar_sessoes: bool = True) -> dict:
    """Volta ao início do cenário: seis equipamentos antigos em atenção, nada em execução."""
    registro = layout_padrao(db)
    layout = service.validar_layout(registro.configuracao)
    zonas = _zonas_comuns(service._layout_dict(layout))
    agora = service._agora()
    relogio = relogio_sim.do_banco(db, agora)
    for sessao in db.scalars(select(SimulacaoSessao).where(
            SimulacaoSessao.layout_id == registro.id,
            SimulacaoSessao.estado.in_(service.ESTADOS_ABERTOS)).with_for_update()):
        if encerrar_sessoes:
            service._encerrar(sessao, agora)
            sessao.versao += 1
    manuais = _epcs_manuais(db, registro.id)
    anteriores = list(_ativos_do_cenario(db).values())
    if manuais:
        anteriores += db.scalars(select(Equipamento).join(
            AssociacaoTagEquipamento, AssociacaoTagEquipamento.equipamento_id == Equipamento.id).join(
            Tag, Tag.id == AssociacaoTagEquipamento.tag_id).where(
            Tag.epc.in_(manuais), AssociacaoTagEquipamento.fim.is_(None))).all()
    for equipamento in {item.id: item for item in anteriores}.values():
        _dar_baixa(db, equipamento, agora)
    db.flush()
    vinculos = topologia.aplicar(db, registro, layout)
    antigo = relogio.agora(agora) - recency_threshold_from_env() - FOLGA_ATENCAO
    for indice, (nome, tipo, epc) in enumerate(EQUIPAMENTOS_ANTIGOS, start=1):
        equipamento = _cadastrar(db, indice, nome, tipo, epc)
        zona = zonas[(indice - 1) // 2]
        corrigir_localizacao(db.connection(), equipment_id=equipamento.id,
                             destination_zone_id=vinculos["zonas"][zona["chave"]],
                             movimentada_em=antigo, justificativa=JUSTIFICATIVA)
    db.commit()
    return estado(db)


ZONA_OUTRO_ANDAR = "Outro andar (elevador)"
SETOR_OUTRO_ANDAR = "Chegada por elevador"
JUSTIFICATIVA_CHEGADA = "Cenário de demonstração do HU: chegou de outro andar pelo elevador central"


def _zona_outro_andar(db: Session, zona_do_hu: int) -> int:
    """Zona fora da planta ("Outro andar"), num setor próprio do mesmo andar do HU.

    Fica fora do setor do layout de propósito: aplicar o layout desativa as zonas
    do setor que não estão no desenho.
    """
    andar_id = db.scalar(select(Setor.andar_id).join(Zona, Zona.setor_id == Setor.id).where(Zona.id == zona_do_hu))
    setor = db.scalar(select(Setor).where(Setor.andar_id == andar_id,
                                         Setor.nome_normalizado == normalizar_nome(SETOR_OUTRO_ANDAR)))
    if setor is None:
        setor = Setor(andar_id=andar_id, nome=SETOR_OUTRO_ANDAR, nome_normalizado=normalizar_nome(SETOR_OUTRO_ANDAR))
        db.add(setor)
        db.flush()
    zona = db.scalar(select(Zona).where(Zona.setor_id == setor.id,
                                       Zona.nome_normalizado == normalizar_nome(ZONA_OUTRO_ANDAR)))
    if zona is None:
        zona = Zona(setor_id=setor.id, nome=ZONA_OUTRO_ANDAR, nome_normalizado=normalizar_nome(ZONA_OUTRO_ANDAR),
                    descricao="Equipamentos que chegaram de outro andar pelo elevador central")
        db.add(zona)
        db.flush()
    zona.ativo = setor.ativo = True
    return zona.id


def _cadastrar_novos(db: Session) -> None:
    """Os três que chegam ao iniciar: cadastrados e vindos de outro andar (elevador).

    A última localização deles é "Outro andar (elevador)", há instantes: acabaram de
    chegar ao centro do mapa e ainda não passaram por nenhum portal deste andar.
    """
    ativos = _ativos_do_cenario(db)
    registro = layout_padrao(db)
    zona_hu = next(iter((registro.vinculos or {}).get("zonas", {}).values()), None)
    chegada = relogio_sim.do_banco(db).agora(service._agora()) - timedelta(seconds=30)
    for indice, (nome, tipo, epc) in enumerate(EQUIPAMENTOS_NOVOS, start=len(EQUIPAMENTOS_ANTIGOS) + 1):
        if _identificador(indice) in ativos:
            continue
        equipamento = _cadastrar(db, indice, nome, tipo, epc)
        if zona_hu is not None:
            corrigir_localizacao(db.connection(), equipment_id=equipamento.id,
                                 destination_zone_id=_zona_outro_andar(db, zona_hu),
                                 movimentada_em=chegada, justificativa=JUSTIFICATIVA_CHEGADA)
            db.commit()


def _itens(db: Session, layout: dict) -> list[dict]:
    """Seis parados dentro das zonas (fora do alcance) e três no centro do mapa."""
    zonas = _zonas_comuns(layout)
    agora_sim = relogio_sim.do_banco(db).agora(service._agora())
    itens: list[dict] = []
    for indice, (nome, tipo, epc) in enumerate(EQUIPAMENTOS_ANTIGOS, start=1):
        x, y = _ponto_na_zona(zonas[(indice - 1) // 2]["area"], layout, [(i["x"], i["y"]) for i in itens])
        itens.append({"id": f"demo-{indice:02d}", "nome": nome, "tipo": tipo, "epc": epc,
                      "x": x, "y": y, "x0": x, "y0": y})
    for indice, (nome, tipo, epc) in enumerate(EQUIPAMENTOS_NOVOS, start=len(EQUIPAMENTOS_ANTIGOS) + 1):
        x, y = service._posicao_livre(layout, itens, agora_sim)
        itens.append({"id": f"demo-{indice:02d}", "nome": nome, "tipo": tipo, "epc": epc,
                      "x": x, "y": y, "x0": x, "y0": y})
    return itens


def e_layout_padrao(db: Session, layout_id: int) -> bool:
    """A sessão deste layout segue o cenário de demonstração?"""
    try:
        return layout_padrao(db).id == layout_id
    except service.SimulacaoRecusada:
        return False


def iniciar(db: Session, usuario_id: int | None) -> SimulacaoSessao:
    """Abre a sessão com os seis antigos e três novos no centro; sem duplicar nada."""
    registro = layout_padrao(db)
    aberta = db.scalar(select(SimulacaoSessao).where(
        SimulacaoSessao.layout_id == registro.id,
        SimulacaoSessao.estado.in_(service.ESTADOS_ABERTOS)))
    if aberta is not None:
        return aberta  # já iniciada: iniciar de novo não acrescenta nada
    ativos = _ativos_do_cenario(db)
    if any(_identificador(i) not in ativos for i in range(1, len(EQUIPAMENTOS_ANTIGOS) + 1)):
        preparar(db)
    _cadastrar_novos(db)
    sessao = service.iniciar_sessao(db, registro.id, usuario_id)
    sessao = service.obter_sessao(db, sessao.codigo, travar=True)
    sessao.itens = _itens(db, sessao.layout)
    sessao.versao += 1
    db.commit()
    db.refresh(sessao)
    return sessao


def reiniciar(db: Session, codigo: str) -> SimulacaoSessao:
    """Mesmo ponto de partida sempre (nove equipamentos), no mesmo link de controle."""
    sessao = service.obter_sessao(db, codigo)
    if sessao.estado == "encerrada":
        raise service.SimulacaoRecusada("sessao_encerrada", "esta sessão já foi encerrada")
    preparar(db, encerrar_sessoes=False)
    _cadastrar_novos(db)
    registro = layout_padrao(db)
    layout = service.validar_layout(registro.configuracao)
    sessao = service.obter_sessao(db, codigo, travar=True)
    relogio = relogio_sim.do_banco(db)
    sessao.layout = service._layout_dict(layout)
    sessao.topologia = topologia.aplicar(db, registro, layout)
    relogio_sim.gravar(sessao, relogio)
    sessao.itens = _itens(db, sessao.layout)
    sessao.estado = "em_execucao"
    sessao.versao += 1
    sessao.atualizada_em = service._agora()
    db.commit()
    db.refresh(sessao)
    return sessao


def estado(db: Session) -> dict:
    """Quantos equipamentos do cenário existem e se a demonstração está em execução."""
    registro = layout_padrao(db)
    ativos = _ativos_do_cenario(db)
    aberta = db.scalar(select(SimulacaoSessao.codigo).where(
        SimulacaoSessao.layout_id == registro.id, SimulacaoSessao.estado.in_(service.ESTADOS_ABERTOS)))
    return {"layout_id": registro.id, "layout": registro.nome, "sessao": aberta,
            "antigos": sum(_identificador(i) in ativos for i in range(1, len(EQUIPAMENTOS_ANTIGOS) + 1)),
            "novos": sum(_identificador(i) in ativos for i in range(len(EQUIPAMENTOS_ANTIGOS) + 1,
                                                                  len(EQUIPAMENTOS_ANTIGOS) + len(EQUIPAMENTOS_NOVOS) + 1))}


MARCAS = Path(__file__).resolve().parents[2] / "data" / "dev"


def restaurar_na_subida(engine, execucao: str, *, tentativas: int = 60, espera_s: float = 5.0) -> bool:
    """Cada execução do ``dev.py`` começa na demonstração padrão (seis parados, três no centro).

    Roda uma vez por execução (marca em ``data/dev``): as recargas automáticas da API
    na mesma execução não desfazem o que foi feito na apresentação. Espera o banco e o
    layout padrão ficarem disponíveis (no modo local o banco sobe depois da API).
    """
    import time

    from sqlalchemy.orm import Session as Sessao

    marca = MARCAS / f"demo-padrao-{execucao}.feito"
    if marca.exists():
        return False
    for _ in range(tentativas):
        try:
            with Sessao(engine) as db:
                layout_padrao(db)
                aberta = db.scalar(select(SimulacaoSessao.codigo).where(
                    SimulacaoSessao.layout_id == layout_padrao(db).id,
                    SimulacaoSessao.estado.in_(service.ESTADOS_ABERTOS)))
                if aberta:
                    reiniciar(db, aberta)  # mesmo link de controle
                else:
                    preparar(db)
                    iniciar(db, None)
            MARCAS.mkdir(parents=True, exist_ok=True)
            marca.write_text(datetime.now().isoformat(), encoding="utf-8")
            return True
        except service.SimulacaoRecusada:
            return False  # sem layout padrão: nada a restaurar
        except Exception:  # noqa: BLE001 - banco ainda subindo ou migrando
            time.sleep(espera_s)
    return False
