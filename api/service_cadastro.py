"""Cadastro operacional de equipamentos pelo dashboard (manual ou por EPC detectado).

Reúne três consultas que o cadastro pelo terminal fazia de forma dispersa:

- **Descoberta de EPCs**: consolida `leituras_brutas` recentes por EPC, com o
  leitor/antena da última leitura, o estado do leitor e se a tag já tem vínculo
  ativo. Não toca no pipeline de inferência: uma leitura de EPC desconhecido já
  é persistida pelo ingestor (sem FK para `tags`), e a passagem dela não move
  nenhum equipamento, porque a projeção de localização só resolve EPCs com
  vínculo vigente no instante da leitura.
- **Situação de etiquetagem**: equipamento sem tag x com tag ativa.
- **Cadastro atômico**: cria o equipamento e, opcionalmente, associa o EPC na
  MESMA transação. Ou os dois existem, ou nenhum — um EPC já vinculado não
  deixa para trás um equipamento órfão.

Nomes repetidos são permitidos de propósito (três macas podem se chamar
"Maca hospitalar"); a identidade do registro é o `id` interno e a do ativo
físico é o `identificador_interno` (patrimônio), único. Quando o operador não
informa patrimônio, é gerado um identificador `EQ-AAAAMMDD-XXXXXX`.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.epc import normalizar_epc
from api.normalizacao import normalizar_nome
from api.service_associacao import TagJaAssociada
from api.service_equipamento import IdentificadorDuplicado, _validar_tipo_ativo
from api.timestamps import em_utc
from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    Leitor,
    LeituraBruta,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_ingestion.reader_status import StatusPolicy, classify

LIMITE_EPCS = 200
PREFIXO_SERIAL_SIMULADO = "SIM-"
SITUACOES_EPC = ("todos", "desconhecidos", "cadastrados")
SITUACOES_EQUIPAMENTO = ("todos", "sem_tag", "com_tag")


class CadastroInvalido(ValueError):
    """Regra de cadastro recusada; `codigo` é estável para a API e a interface."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        """Guarda o código estável junto da mensagem legível."""
        super().__init__(mensagem)
        self.codigo = codigo


def origem_do_leitor(identificador_serial: str | None) -> str:
    """Leitores virtuais do simulador web têm serial `SIM-...`; os demais são físicos."""
    if identificador_serial and identificador_serial.startswith(PREFIXO_SERIAL_SIMULADO):
        return "simulado"
    return "fisico"


def gerar_identificador_interno(agora: datetime | None = None) -> str:
    """Patrimônio provisório quando o operador não informa um: `EQ-20261023-7F3A9C`."""
    agora = agora or datetime.now(timezone.utc)
    return f"EQ-{agora:%Y%m%d}-{secrets.token_hex(3).upper()}"


def _vinculos_ativos(db: Session, epcs: list[str]) -> dict[str, dict]:
    """Equipamento com vínculo ATIVO para cada EPC informado."""
    if not epcs:
        return {}
    linhas = db.execute(
        select(Tag.epc, Equipamento.id, Equipamento.nome, Equipamento.status,
               Equipamento.identificador_interno, TipoEquipamento.nome.label("tipo"))
        .join(AssociacaoTagEquipamento, and_(
            AssociacaoTagEquipamento.tag_id == Tag.id, AssociacaoTagEquipamento.fim.is_(None)))
        .join(Equipamento, Equipamento.id == AssociacaoTagEquipamento.equipamento_id)
        .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .where(Tag.epc.in_(epcs))
    ).all()
    return {
        linha.epc: {"id": linha.id, "nome": linha.nome, "status": linha.status,
                    "identificador_interno": linha.identificador_interno, "tipo": linha.tipo}
        for linha in linhas
    }


def epcs_detectados(
    db: Session, *, now: datetime, janela: timedelta, recente: timedelta,
    leitor: str | None = None, antena_id: int | None = None, situacao: str = "todos",
    policy: StatusPolicy | None = None,
) -> dict:
    """EPCs lidos na janela, consolidados (uma linha por EPC), mais recentes primeiro.

    `recente` separa uma leitura "ao vivo" (a tag está perto da antena agora) de
    uma leitura antiga da janela; a interface só destaca as recentes para evitar
    associar a tag errada. Leitores offline aparecem no resumo `leitores`.
    """
    if situacao not in SITUACOES_EPC:
        raise CadastroInvalido("situacao_invalida", f"situacao deve ser {', '.join(SITUACOES_EPC)}")
    policy = policy or StatusPolicy.from_env()
    corte = now - janela
    filtros = [LeituraBruta.lido_em >= corte]
    if leitor:
        filtros.append(Leitor.reader_id == leitor)
    if antena_id is not None:
        filtros.append(LeituraBruta.antena_id == antena_id)
    agregado = db.execute(
        select(LeituraBruta.epc, LeituraBruta.antena_id,
               func.count().label("leituras"),
               func.min(LeituraBruta.lido_em).label("primeira"),
               func.max(LeituraBruta.lido_em).label("ultima"))
        .join(Antena, Antena.id == LeituraBruta.antena_id)
        .join(Leitor, Leitor.id == Antena.leitor_id)
        .where(*filtros)
        .group_by(LeituraBruta.epc, LeituraBruta.antena_id)
    ).all()

    antenas_ids = {linha.antena_id for linha in agregado}
    antenas = {
        linha.id: {"antena_id": linha.id, "porta": linha.porta_numero, "leitor": linha.reader_id,
                   "leitor_modelo": linha.modelo, "zona": linha.zona,
                   "origem": origem_do_leitor(linha.identificador_serial)}
        for linha in db.execute(
            select(Antena.id, Antena.porta_numero, Leitor.reader_id, Leitor.modelo,
                   Leitor.identificador_serial, Zona.nome.label("zona"))
            .join(Leitor, Leitor.id == Antena.leitor_id)
            .outerjoin(Zona, Zona.id == Antena.zona_associada_id)
            .where(Antena.id.in_(antenas_ids or {0}))
        ).all()
    }

    por_epc: dict[str, list] = {}
    for linha in agregado:
        por_epc.setdefault(linha.epc, []).append(linha)
    vinculos = _vinculos_ativos(db, list(por_epc))

    items = []
    for epc, linhas in por_epc.items():
        ultima = max(linhas, key=lambda linha: linha.ultima)
        equipamento = vinculos.get(epc)
        if situacao == "desconhecidos" and equipamento is not None:
            continue
        if situacao == "cadastrados" and equipamento is None:
            continue
        items.append({
            "epc": epc,
            "situacao": "cadastrado" if equipamento else "desconhecido",
            "equipamento": equipamento,
            "leituras": sum(linha.leituras for linha in linhas),
            "primeira_leitura_em": em_utc(min(linha.primeira for linha in linhas)),
            "ultima_leitura_em": em_utc(ultima.ultima),
            "recente": ultima.ultima >= now - recente,
            "ultima_antena": antenas.get(ultima.antena_id),
            "antenas": sorted(
                ({**antenas.get(linha.antena_id, {"antena_id": linha.antena_id}),
                  "leituras": linha.leituras, "ultima_leitura_em": em_utc(linha.ultima)}
                 for linha in linhas),
                key=lambda item: item["antena_id"]),
        })
    items.sort(key=lambda item: (item["situacao"] != "desconhecido",
                                 -item["ultima_leitura_em"].timestamp(), item["epc"]))
    total = len(items)

    leitores = [
        {"reader_id": linha.reader_id, "modelo": linha.modelo,
         "origem": origem_do_leitor(linha.identificador_serial),
         "ultimo_contato_em": em_utc(linha.ultimo_contato_em),
         "status": classify(linha.ultimo_contato_em, linha.saude_reportada, now, policy)[0],
         "antenas": [{"antena_id": antena.id, "porta": antena.porta_numero}
                     for antena in db.scalars(
                         select(Antena).where(Antena.leitor_id == linha.id,
                                              Antena.ativo.is_(True))
                         .order_by(Antena.porta_numero))]}
        for linha in db.execute(
            select(Leitor.id, Leitor.reader_id, Leitor.modelo, Leitor.identificador_serial,
                   Leitor.ultimo_contato_em, Leitor.saude_reportada)
            .where(Leitor.ativo.is_(True)).order_by(Leitor.reader_id)
        ).all()
    ]
    return {
        "gerado_em": em_utc(now),
        "janela_segundos": int(janela.total_seconds()),
        "recente_segundos": int(recente.total_seconds()),
        "total": total,
        "desconhecidos": sum(1 for item in items if item["situacao"] == "desconhecido"),
        "items": items[:LIMITE_EPCS],
        "leitores": leitores,
    }


@dataclass(frozen=True)
class PaginaCadastro:
    """Página de equipamentos com a situação de etiquetagem de cada um."""

    items: list[dict]
    page: int
    size: int
    total: int

    @property
    def pages(self) -> int:
        """Quantidade de páginas para o tamanho pedido."""
        return math.ceil(self.total / self.size) if self.size else 0


def listar_equipamentos(
    db: Session, *, situacao: str = "todos", busca: str | None = None,
    incluir_inativos: bool = False, page: int = 1, size: int = 20,
) -> PaginaCadastro:
    """Equipamentos com o EPC ativo (ou nenhum), filtráveis por situação e texto."""
    if situacao not in SITUACOES_EQUIPAMENTO:
        raise CadastroInvalido(
            "situacao_invalida", f"situacao deve ser {', '.join(SITUACOES_EQUIPAMENTO)}")
    vinculo = (
        select(AssociacaoTagEquipamento.equipamento_id, Tag.epc, AssociacaoTagEquipamento.inicio)
        .join(Tag, Tag.id == AssociacaoTagEquipamento.tag_id)
        .where(AssociacaoTagEquipamento.fim.is_(None))
        .subquery()
    )
    filtros = []
    if not incluir_inativos:
        filtros.append(Equipamento.status == "ativo")
    if situacao == "sem_tag":
        filtros.append(vinculo.c.epc.is_(None))
    elif situacao == "com_tag":
        filtros.append(vinculo.c.epc.is_not(None))
    if busca and busca.strip():
        termo = f"%{busca.strip().upper()}%"
        filtros.append(or_(
            func.upper(Equipamento.nome).like(termo),
            func.upper(Equipamento.identificador_interno).like(termo),
            vinculo.c.epc.like(termo),
        ))
    base = (
        select(Equipamento.id, Equipamento.nome, Equipamento.identificador_interno,
               Equipamento.status, Equipamento.descricao, Equipamento.tipo_id,
               TipoEquipamento.nome.label("tipo_nome"), Zona.nome.label("ultima_zona"),
               Equipamento.created_at, vinculo.c.epc, vinculo.c.inicio.label("vinculo_inicio"))
        .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .outerjoin(vinculo, vinculo.c.equipamento_id == Equipamento.id)
        .outerjoin(Zona, Zona.id == Equipamento.ultima_zona_id)
        .where(*filtros)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    linhas = db.execute(
        base.order_by(Equipamento.created_at.desc(), Equipamento.id.desc())
        .limit(size).offset((page - 1) * size)
    ).all()
    return PaginaCadastro(
        items=[{
            "id": linha.id, "nome": linha.nome,
            "identificador_interno": linha.identificador_interno,
            "status": linha.status, "descricao": linha.descricao,
            "tipo_id": linha.tipo_id, "tipo_nome": linha.tipo_nome,
            "ultima_zona": linha.ultima_zona, "epc": linha.epc,
            "situacao_tag": "com_tag" if linha.epc else "sem_tag",
            "vinculo_inicio": em_utc(linha.vinculo_inicio),
            "created_at": em_utc(linha.created_at),
        } for linha in linhas],
        page=page, size=size, total=total or 0,
    )


def epc_disponivel(db: Session, epc: str) -> dict:
    """Informa se o EPC pode receber um vínculo novo (sem vínculo ativo)."""
    epc = normalizar_epc(epc)
    equipamento = _vinculos_ativos(db, [epc]).get(epc)
    ultima = db.scalar(select(func.max(LeituraBruta.lido_em)).where(LeituraBruta.epc == epc))
    return {"epc": epc, "disponivel": equipamento is None, "equipamento": equipamento,
            "ultima_leitura_em": em_utc(ultima)}


def cadastrar(
    db: Session, *, nome: str, tipo_id: int, identificador_interno: str | None = None,
    descricao: str | None = None, epc: str | None = None,
) -> tuple[Equipamento, str | None]:
    """Cria o equipamento e, se houver EPC, o vínculo — tudo em uma transação.

    A checagem prévia do EPC só melhora a mensagem; a garantia contra corrida é
    o índice parcial `uq_tag_ativa`, traduzido para `TagJaAssociada`.
    """
    _validar_tipo_ativo(db, tipo_id)
    epc_normalizado = normalizar_epc(epc) if epc else None
    if epc_normalizado and _vinculos_ativos(db, [epc_normalizado]):
        raise TagJaAssociada(epc_normalizado)
    identificador = (identificador_interno or "").strip() or gerar_identificador_interno()
    equipamento = Equipamento(
        nome=nome.strip(), tipo_id=tipo_id, identificador_interno=identificador,
        identificador_interno_normalizado=normalizar_nome(identificador),
        descricao=(descricao or "").strip() or None,
    )
    db.add(equipamento)
    try:
        db.flush()
    except IntegrityError as erro:
        db.rollback()
        raise IdentificadorDuplicado(identificador) from erro
    if epc_normalizado:
        try:
            tag = db.scalar(select(Tag).where(Tag.epc == epc_normalizado))
            if tag is None:
                tag = Tag(epc=epc_normalizado)
                db.add(tag)
                db.flush()
            db.add(AssociacaoTagEquipamento(
                tag_id=tag.id, equipamento_id=equipamento.id, inicio=datetime.now(timezone.utc)))
            db.flush()
        except IntegrityError as erro:
            # Outra transação criou a tag ou o vínculo no meio: nada deste cadastro fica.
            db.rollback()
            raise TagJaAssociada(epc_normalizado) from erro
    db.commit()
    db.refresh(equipamento)
    db.refresh(equipamento, attribute_names=["tipo"])
    return equipamento, epc_normalizado
