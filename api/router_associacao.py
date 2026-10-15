"""
Router HTTP da associação EPC <-> equipamento (ISS-010, RF-003).

Responsabilidade única: validar/serializar payload e traduzir as
exceções de domínio de `api.service_associacao` para status code.
Nenhuma regra de negócio mora aqui — mesmo padrão de
`api/router_equipamento.py` e `api/router_tipos_equipamento.py`.

Mapeamento de erro:
- `EquipamentoInvalido`              -> 422 (equipamento não existe ou inativo)
- `NenhumVinculoAtivo`               -> 404
- `TagJaAssociada`                   -> 409
- `EquipamentoJaPossuiVinculoAtivo`  -> 409
- `TagJaEhAAtiva`                    -> 409
- payload inválido (EPC malformado)  -> 422, direto pelo Pydantic
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import service_associacao as service
from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo
from api.schemas_associacao import (
    AssociacaoOut,
    AssociarPayload,
    ResolucaoEpcOut,
    SubstituirPayload,
)
from db.models import AssociacaoTagEquipamento

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.EQUIPAMENTOS_CONSULTAR, alterar=Permissao.EQUIPAMENTOS_ALTERAR
)
router = APIRouter(tags=["associacoes"], dependencies=[Depends(_PERMISSAO)])


def _para_saida(associacao: AssociacaoTagEquipamento) -> AssociacaoOut:
    return AssociacaoOut(
        id=associacao.id,
        epc=associacao.tag.epc,
        equipamento_id=associacao.equipamento_id,
        equipamento_nome=associacao.equipamento.nome if associacao.equipamento else "",
        inicio=associacao.inicio,
        fim=associacao.fim,
    )


@router.post(
    "/equipamentos/{equipamento_id}/tag",
    response_model=AssociacaoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Associar tag (EPC) a um equipamento",
)
def associar_tag(
    equipamento_id: int, payload: AssociarPayload, db: Session = Depends(get_db)
) -> AssociacaoOut:
    try:
        associacao = service.associar(db, equipamento_id, payload.epc)
    except service.EquipamentoInvalido as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except (service.TagJaAssociada, service.EquipamentoJaPossuiVinculoAtivo) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _para_saida(service.vinculo_ativo_por_equipamento(db, equipamento_id) or associacao)


@router.put(
    "/equipamentos/{equipamento_id}/tag",
    response_model=AssociacaoOut,
    summary="Substituir a tag ativa de um equipamento",
)
def substituir_tag(
    equipamento_id: int, payload: SubstituirPayload, db: Session = Depends(get_db)
) -> AssociacaoOut:
    try:
        associacao = service.substituir(db, equipamento_id, payload.epc_novo)
    except service.EquipamentoInvalido as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except service.NenhumVinculoAtivo as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (service.TagJaAssociada, service.TagJaEhAAtiva) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _para_saida(associacao)


@router.get(
    "/equipamentos/{equipamento_id}/tag",
    response_model=AssociacaoOut,
    summary="Consultar o vínculo de tag ativo de um equipamento",
)
def obter_vinculo_ativo(equipamento_id: int, db: Session = Depends(get_db)) -> AssociacaoOut:
    vinculo = service.vinculo_ativo_por_equipamento(db, equipamento_id)
    if vinculo is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="equipamento não possui vínculo ativo"
        )
    return _para_saida(vinculo)


@router.delete(
    "/equipamentos/{equipamento_id}/tag",
    response_model=AssociacaoOut,
    summary="Encerrar o vínculo de tag ativo de um equipamento",
)
def encerrar_vinculo(equipamento_id: int, db: Session = Depends(get_db)) -> AssociacaoOut:
    try:
        associacao = service.encerrar(db, equipamento_id)
    except service.NenhumVinculoAtivo as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return _para_saida(associacao)


@router.get(
    "/equipamentos/{equipamento_id}/tag/historico",
    response_model=list[AssociacaoOut],
    summary="Histórico completo de vínculos de tag de um equipamento",
)
def historico_vinculos(
    equipamento_id: int, db: Session = Depends(get_db)
) -> list[AssociacaoOut]:
    return [_para_saida(item) for item in service.historico_por_equipamento(db, equipamento_id)]


@router.get(
    "/tags/{epc}",
    response_model=ResolucaoEpcOut,
    summary="Resolver um EPC para o equipamento que ele identifica atualmente",
)
def resolver_epc(epc: str, db: Session = Depends(get_db)) -> ResolucaoEpcOut:
    associacao = service.resolver_epc(db, epc)
    if associacao is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="EPC desconhecido ou sem vínculo ativo no momento",
        )
    return ResolucaoEpcOut(
        epc=associacao.tag.epc,
        equipamento_id=associacao.equipamento_id,
        equipamento_nome=associacao.equipamento.nome,
        associacao_id=associacao.id,
        inicio=associacao.inicio,
    )
