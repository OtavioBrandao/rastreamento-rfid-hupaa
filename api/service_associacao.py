"""
Camada de serviço da associação EPC <-> equipamento (ISS-010, RF-003).

Mesmo padrão de `api/service_equipamento.py` e `api/service_tipos_equipamento.py`:
roda contra uma `Session` recebida por parâmetro, sem dependência de HTTP,
e levanta exceções de DOMÍNIO — nunca `HTTPException`.

A garantia de "um EPC ativo resolve pra exatamente um equipamento, mesmo
sob concorrência" NÃO vem de check-then-act na aplicação (isso tem
race condition clássica). Vem dos dois índices únicos parciais que já
existem no banco desde a ISS-002a (`uq_tag_ativa` em `tag_id WHERE fim IS
NULL`, `uq_equipamento_tag_ativa` em `equipamento_id WHERE fim IS NULL`):
o INSERT concorrente que perde é rejeitado pelo Postgres com
`IntegrityError`, e o serviço traduz isso para exceção de domínio
inspecionando `error.orig.diag.constraint_name` (atributo de diagnóstico
do psycopg2). O SELECT antes do INSERT só existe para dar mensagem de
erro melhor no caminho feliz sem concorrência — a garantia real é do
banco.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from api.epc import EpcInvalido, normalizar_epc
from db.models import AssociacaoTagEquipamento, Auditoria, Equipamento, Tag


class EquipamentoInvalido(Exception):
    def __init__(self, equipamento_id: int):
        self.equipamento_id = equipamento_id
        super().__init__(
            f"equipamento {equipamento_id} não existe ou está inativo — "
            "não pode receber vínculo de tag"
        )


class TagJaAssociada(Exception):
    def __init__(self, epc: str):
        self.epc = epc
        super().__init__(f"EPC '{epc}' já está associado a outro equipamento ativo")


class EquipamentoJaPossuiVinculoAtivo(Exception):
    def __init__(self, equipamento_id: int):
        self.equipamento_id = equipamento_id
        super().__init__(
            f"equipamento {equipamento_id} já possui um vínculo de tag ativo — "
            "use substituir() em vez de associar()"
        )


class NenhumVinculoAtivo(Exception):
    def __init__(self, equipamento_id: int):
        self.equipamento_id = equipamento_id
        super().__init__(f"equipamento {equipamento_id} não possui vínculo de tag ativo")


class TagJaEhAAtiva(Exception):
    def __init__(self, epc: str, equipamento_id: int):
        self.epc = epc
        self.equipamento_id = equipamento_id
        super().__init__(f"EPC '{epc}' já é a tag ativa do equipamento {equipamento_id}")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _carregar_equipamento_ativo(db: Session, equipamento_id: int) -> Equipamento:
    equipamento = db.get(Equipamento, equipamento_id)
    if equipamento is None or equipamento.status != "ativo":
        raise EquipamentoInvalido(equipamento_id)
    return equipamento


def _obter_ou_criar_tag(db: Session, epc_normalizado: str) -> Tag:
    tag = db.scalar(select(Tag).where(Tag.epc == epc_normalizado))
    if tag is not None:
        return tag

    tag = Tag(epc=epc_normalizado)
    db.add(tag)
    try:
        db.flush()
    except IntegrityError:
        # Corrida real: duas threads tentaram criar a MESMA tag nova ao
        # mesmo tempo (nenhuma das duas a encontrou no SELECT acima
        # porque, até então, ela não existia). `tags.epc` tem UNIQUE
        # próprio (`tags_epc_key`), independente dos dois índices
        # parciais de associação — sem este except, a thread perdedora
        # explodiria com um IntegrityError cru em vez da exceção de
        # domínio esperada mais adiante (TagJaAssociada). Não é erro de
        # negócio: a tag existe, só foi outra transação que a criou
        # primeiro — buscamos de novo e reaproveitamos a linha vencedora.
        db.rollback()
        tag = db.scalar(select(Tag).where(Tag.epc == epc_normalizado))
        if tag is None:
            raise
    return tag


def _vinculo_ativo_do_equipamento(
    db: Session, equipamento_id: int
) -> AssociacaoTagEquipamento | None:
    return db.scalar(
        select(AssociacaoTagEquipamento)
        .options(joinedload(AssociacaoTagEquipamento.tag))
        .where(
            AssociacaoTagEquipamento.equipamento_id == equipamento_id,
            AssociacaoTagEquipamento.fim.is_(None),
        )
    )


def _registrar_auditoria(
    db: Session,
    acao: str,
    associacao_id: int,
    dados_antes: dict | None,
    dados_depois: dict | None,
) -> None:
    db.add(
        Auditoria(
            usuario_id=None,
            entidade="associacoes_tag_equipamento",
            entidade_id=associacao_id,
            acao=acao,
            dados_antes=dados_antes,
            dados_depois=dados_depois,
        )
    )


def _inserir_associacao(
    db: Session, tag_id: int, equipamento_id: int, epc_para_erro: str
) -> AssociacaoTagEquipamento:
    associacao = AssociacaoTagEquipamento(
        tag_id=tag_id, equipamento_id=equipamento_id, inicio=_agora()
    )
    db.add(associacao)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", "") or ""
        if "uq_tag_ativa" in constraint:
            raise TagJaAssociada(epc_para_erro) from error
        if "uq_equipamento_tag_ativa" in constraint:
            raise EquipamentoJaPossuiVinculoAtivo(equipamento_id) from error
        raise
    return associacao


def associar(db: Session, equipamento_id: int, epc: str) -> AssociacaoTagEquipamento:
    epc_normalizado = normalizar_epc(epc)
    _carregar_equipamento_ativo(db, equipamento_id)

    if _vinculo_ativo_do_equipamento(db, equipamento_id) is not None:
        raise EquipamentoJaPossuiVinculoAtivo(equipamento_id)

    tag = _obter_ou_criar_tag(db, epc_normalizado)
    if db.scalar(
        select(AssociacaoTagEquipamento).where(
            AssociacaoTagEquipamento.tag_id == tag.id, AssociacaoTagEquipamento.fim.is_(None)
        )
    ):
        raise TagJaAssociada(epc_normalizado)

    associacao = _inserir_associacao(db, tag.id, equipamento_id, epc_normalizado)
    _registrar_auditoria(
        db,
        "create",
        associacao.id,
        dados_antes=None,
        dados_depois={"tag_id": tag.id, "epc": epc_normalizado, "equipamento_id": equipamento_id},
    )
    db.commit()
    db.refresh(associacao)
    return associacao


def substituir(db: Session, equipamento_id: int, epc_novo: str) -> AssociacaoTagEquipamento:
    epc_normalizado = normalizar_epc(epc_novo)
    _carregar_equipamento_ativo(db, equipamento_id)

    vinculo_atual = _vinculo_ativo_do_equipamento(db, equipamento_id)
    if vinculo_atual is None:
        raise NenhumVinculoAtivo(equipamento_id)
    if vinculo_atual.tag.epc == epc_normalizado:
        raise TagJaEhAAtiva(epc_normalizado, equipamento_id)

    tag_nova = _obter_ou_criar_tag(db, epc_normalizado)
    if db.scalar(
        select(AssociacaoTagEquipamento).where(
            AssociacaoTagEquipamento.tag_id == tag_nova.id,
            AssociacaoTagEquipamento.fim.is_(None),
        )
    ):
        raise TagJaAssociada(epc_normalizado)

    agora = _agora()
    vinculo_anterior_id = vinculo_atual.id
    epc_anterior = vinculo_atual.tag.epc
    vinculo_atual.fim = agora
    db.flush()

    nova_associacao = _inserir_associacao(db, tag_nova.id, equipamento_id, epc_normalizado)
    _registrar_auditoria(
        db,
        "update",
        nova_associacao.id,
        dados_antes={"associacao_anterior_id": vinculo_anterior_id, "epc_anterior": epc_anterior},
        dados_depois={
            "tag_id": tag_nova.id,
            "epc": epc_normalizado,
            "equipamento_id": equipamento_id,
        },
    )
    db.commit()
    db.refresh(nova_associacao)
    return nova_associacao


def encerrar(db: Session, equipamento_id: int) -> AssociacaoTagEquipamento:
    vinculo = _vinculo_ativo_do_equipamento(db, equipamento_id)
    if vinculo is None:
        raise NenhumVinculoAtivo(equipamento_id)

    epc_atual = vinculo.tag.epc
    vinculo.fim = _agora()
    db.flush()
    _registrar_auditoria(
        db,
        "delete",
        vinculo.id,
        dados_antes={"fim": None, "epc": epc_atual},
        dados_depois={"fim": vinculo.fim.isoformat(), "epc": epc_atual},
    )
    db.commit()
    db.refresh(vinculo)
    return vinculo


def vinculo_ativo_por_equipamento(
    db: Session, equipamento_id: int
) -> AssociacaoTagEquipamento | None:
    return _vinculo_ativo_do_equipamento(db, equipamento_id)


def historico_por_equipamento(db: Session, equipamento_id: int) -> list[AssociacaoTagEquipamento]:
    return list(
        db.scalars(
            select(AssociacaoTagEquipamento)
            .options(joinedload(AssociacaoTagEquipamento.tag))
            .where(AssociacaoTagEquipamento.equipamento_id == equipamento_id)
            .order_by(AssociacaoTagEquipamento.inicio.desc())
        )
    )


def resolver_epc(db: Session, epc: str) -> AssociacaoTagEquipamento | None:
    """Retorna None — nunca lança — se o EPC não existe ou não tem vínculo
    ativo. É o comportamento que a futura ISS-006 (ingestão) precisa: uma
    leitura de EPC desconhecido tem que continuar sendo persistida como
    leitura bruta, nunca descartada por causa de exceção daqui."""
    try:
        epc_normalizado = normalizar_epc(epc)
    except EpcInvalido:
        return None
    return db.scalar(
        select(AssociacaoTagEquipamento)
        .join(Tag, AssociacaoTagEquipamento.tag_id == Tag.id)
        .options(joinedload(AssociacaoTagEquipamento.equipamento))
        .where(Tag.epc == epc_normalizado, AssociacaoTagEquipamento.fim.is_(None))
    )
