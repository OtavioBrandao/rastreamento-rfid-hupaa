"""
Correção manual de equipamento (ISS-025): localização e cadastro.

Exige `equipamentos:corrigir` (só administrador). Toda recusa sai no
formato `{"detail": {"codigo": ..., "mensagem": ...}}`:

| status | codigo |
|---|---|
| 404 | equipamento_inexistente |
| 409 | conflito_de_versao (+ versao_atual), equipamento_inativo, identificador_duplicado, anterior_a_ultima_localizacao, conflito_de_horario |
| 422 | sem_mudanca, zona_invalida, tipo_invalido |
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import service_correcoes as service
from api.config_auth import obter_agora
from api.database import get_db
from api.permissoes import Permissao, exigir
from api.router_equipamento import get_recency_context, para_resposta
from api.schemas_correcao import (
    CorrecaoCadastroEntrada,
    CorrecaoLocalizacaoEntrada,
    CorrecaoLocalizacaoResposta,
)
from api.schemas_equipamento import EquipamentoResposta
from api.service_auth import SessaoAutenticada
from api.timestamps import em_utc

# Mesma instância no router e na rota que precisa do autor: resolvida uma vez.
corrigir_equipamentos = exigir(Permissao.EQUIPAMENTOS_CORRIGIR)

router = APIRouter(
    prefix="/equipamentos", tags=["correção manual"],
    dependencies=[Depends(corrigir_equipamentos)],
)

_STATUS_POR_CODIGO = {
    "equipamento_inexistente": status.HTTP_404_NOT_FOUND,
    "anterior_a_ultima_localizacao": status.HTTP_409_CONFLICT,
    "conflito_de_horario": status.HTTP_409_CONFLICT,
    "sem_mudanca": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _erro(status_code: int, codigo: str, mensagem: str, **extra) -> HTTPException:
    return HTTPException(status_code, detail={"codigo": codigo, "mensagem": mensagem, **extra})


def _traduzir(erro: Exception) -> HTTPException:
    if isinstance(erro, service.ConflitoDeVersao):
        return _erro(status.HTTP_409_CONFLICT, "conflito_de_versao",
                     "O equipamento foi alterado por outra operação. Recarregue e revise.",
                     versao_atual=erro.versao_atual)
    if isinstance(erro, service.CorrecaoRecusada):
        return _erro(_STATUS_POR_CODIGO.get(erro.codigo, status.HTTP_422_UNPROCESSABLE_CONTENT),
                     erro.codigo, str(erro))
    if isinstance(erro, service.EquipamentoNaoEncontrado):
        return _erro(status.HTTP_404_NOT_FOUND, "equipamento_inexistente", str(erro))
    if isinstance(erro, service.EquipamentoInativo):
        return _erro(status.HTTP_409_CONFLICT, "equipamento_inativo", str(erro))
    if isinstance(erro, service.IdentificadorDuplicado):
        return _erro(status.HTTP_409_CONFLICT, "identificador_duplicado", str(erro))
    if isinstance(erro, service.SemMudanca):
        return _erro(status.HTTP_422_UNPROCESSABLE_CONTENT, "sem_mudanca", str(erro))
    if isinstance(erro, service.ZonaInvalida):
        return _erro(status.HTTP_422_UNPROCESSABLE_CONTENT, "zona_invalida", str(erro))
    if isinstance(erro, service.TipoEquipamentoInvalido):
        return _erro(status.HTTP_422_UNPROCESSABLE_CONTENT, "tipo_invalido", str(erro))
    raise erro


_ERROS = (
    service.ConflitoDeVersao, service.CorrecaoRecusada, service.EquipamentoNaoEncontrado,
    service.EquipamentoInativo, service.IdentificadorDuplicado, service.SemMudanca,
    service.ZonaInvalida, service.TipoEquipamentoInvalido,
)


@router.post(
    "/{equipamento_id}/correcoes/localizacao", response_model=CorrecaoLocalizacaoResposta,
    summary="Corrigir a última localização (vale a partir de agora)",
)
def corrigir_localizacao(
    equipamento_id: int,
    payload: CorrecaoLocalizacaoEntrada,
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    admin: SessaoAutenticada = Depends(corrigir_equipamentos),
) -> CorrecaoLocalizacaoResposta:
    try:
        resultado = service.corrigir_localizacao_equipamento(
            db, autor_id=admin.usuario.id, equipamento_id=equipamento_id,
            zona_id=payload.zona_id, justificativa=payload.justificativa,
            referencia=payload.referencia, versao_esperada=payload.versao_esperada, agora=agora,
        )
    except _ERROS as erro:
        raise _traduzir(erro) from erro
    return CorrecaoLocalizacaoResposta(
        equipamento_id=equipamento_id, zona_anterior_id=resultado.previous_zone_id,
        zona_id=resultado.destination_zone_id, movimentacao_id=resultado.movement_id,
        movimentada_em=em_utc(resultado.movement_at), versao=resultado.versao,
    )


@router.post(
    "/{equipamento_id}/correcoes/cadastro", response_model=EquipamentoResposta,
    summary="Corrigir nome, tipo, descrição e patrimônio",
)
def corrigir_cadastro(
    equipamento_id: int,
    payload: CorrecaoCadastroEntrada,
    db: Session = Depends(get_db),
    recency_context: tuple[datetime, timedelta] = Depends(get_recency_context),
) -> EquipamentoResposta:
    try:
        equipamento = service.corrigir_cadastro(
            db, equipamento_id=equipamento_id, justificativa=payload.justificativa,
            referencia=payload.referencia, versao_esperada=payload.versao_esperada,
            nome=payload.nome, tipo_id=payload.tipo_id,
            identificador_interno=payload.identificador_interno, descricao=payload.descricao,
            descricao_informada="descricao" in payload.model_fields_set,
        )
    except _ERROS as erro:
        raise _traduzir(erro) from erro
    return para_resposta(equipamento, recency_context)
