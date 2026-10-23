"""Cadastro de equipamentos e tags pelo dashboard (manual e por leitura RFID).

Consulta exige `equipamentos:consultar`; criar e associar exigem
`equipamentos:alterar` — verificados aqui, no backend, como no restante da API.
A trilha de auditoria (criar + vincular_epc) sai do registro central.

Mapeamento de erro:
- `TipoEquipamentoInvalido` / EPC inválido / associação sem confirmação -> 422
- `IdentificadorDuplicado` / `TagJaAssociada`                            -> 409
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from api import service_cadastro as service
from api.database import get_db
from api.epc import EpcInvalido, normalizar_epc
from api.permissoes import Permissao, exigir_por_metodo
from api.schemas_equipamento import _validar_texto_preenchido
from api.service_associacao import TagJaAssociada
from api.service_equipamento import IdentificadorDuplicado, TipoEquipamentoInvalido

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.EQUIPAMENTOS_CONSULTAR, alterar=Permissao.EQUIPAMENTOS_ALTERAR
)
router = APIRouter(prefix="/api/cadastro", tags=["cadastro"], dependencies=[Depends(_PERMISSAO)])


class CadastroPayload(BaseModel):
    """Equipamento novo, com EPC opcional (manual ou escolhido entre os detectados)."""

    nome: str = Field(..., max_length=255)
    tipo_id: int = Field(..., gt=0)
    identificador_interno: str | None = Field(default=None, max_length=255)
    descricao: str | None = Field(default=None, max_length=2000)
    epc: str | None = Field(default=None, max_length=64)
    origem_epc: str = Field(default="manual", pattern="^(manual|leitura)$")
    # Associar uma tag exige confirmação explícita do operador (evita vínculo por clique acidental).
    confirmar_associacao: bool = False

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)

    @field_validator("epc")
    @classmethod
    def validar_epc(cls, valor: str | None) -> str | None:
        """Normaliza o EPC informado; vazio significa cadastro sem tag."""
        if valor is None or not valor.strip():
            return None
        try:
            return normalizar_epc(valor)
        except EpcInvalido as error:
            raise ValueError(str(error)) from error

    @model_validator(mode="after")
    def exigir_confirmacao(self) -> CadastroPayload:
        """Com EPC, o vínculo só é criado com `confirmar_associacao=true`."""
        if self.epc and not self.confirmar_associacao:
            raise ValueError("confirme a associação da tag ao equipamento")
        return self


class CadastroResposta(BaseModel):
    """Resultado do cadastro, já com o EPC vinculado (ou nenhum)."""

    id: int
    nome: str
    tipo_id: int
    tipo_nome: str
    identificador_interno: str
    descricao: str | None
    status: str
    epc: str | None
    situacao_tag: str
    origem_epc: str | None


def _contexto_descoberta() -> datetime:
    """Relógio UTC da requisição, isolado para os testes."""
    return datetime.now(UTC)


@router.get("/epcs-detectados", summary="EPCs detectados recentemente, consolidados por tag")
def listar_epcs_detectados(
    janela_segundos: int = Query(900, ge=10, le=7 * 86400),
    recente_segundos: int = Query(120, ge=5, le=3600),
    leitor: str | None = Query(None, max_length=64),
    antena_id: int | None = Query(None, ge=1),
    situacao: str = Query("todos", pattern="^(todos|desconhecidos|cadastrados)$"),
    db: Session = Depends(get_db),
    agora: datetime = Depends(_contexto_descoberta),
) -> dict:
    """Leituras brutas da janela agrupadas por EPC, com leitor, antena e vínculo."""
    return service.epcs_detectados(
        db, now=agora, janela=timedelta(seconds=janela_segundos),
        recente=timedelta(seconds=recente_segundos), leitor=leitor or None,
        antena_id=antena_id, situacao=situacao)


@router.get("/epcs/{epc}", summary="Disponibilidade de um EPC para associação")
def consultar_epc(epc: str, db: Session = Depends(get_db)) -> dict:
    """Diz se o EPC está livre ou já vinculado a um equipamento ativo."""
    try:
        return service.epc_disponivel(db, epc)
    except EpcInvalido as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get("/equipamentos", summary="Equipamentos e situação de etiquetagem")
def listar_equipamentos(
    situacao: str = Query("todos", pattern="^(todos|sem_tag|com_tag)$"),
    busca: str | None = Query(None, max_length=100),
    incluir_inativos: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Lista equipamentos com o EPC ativo de cada um (ou a ausência dele)."""
    pagina = service.listar_equipamentos(db, situacao=situacao, busca=busca,
                                         incluir_inativos=incluir_inativos, page=page, size=size)
    return {"items": pagina.items, "page": pagina.page, "size": pagina.size,
            "total": pagina.total, "pages": pagina.pages}


@router.post("/equipamentos", response_model=CadastroResposta,
             status_code=status.HTTP_201_CREATED, summary="Cadastrar equipamento (com ou sem tag)")
def cadastrar_equipamento(payload: CadastroPayload, db: Session = Depends(get_db)
                          ) -> CadastroResposta:
    """Cria o equipamento e, se houver EPC confirmado, o vínculo na mesma transação."""
    try:
        equipamento, epc = service.cadastrar(
            db, nome=payload.nome, tipo_id=payload.tipo_id,
            identificador_interno=payload.identificador_interno,
            descricao=payload.descricao, epc=payload.epc)
    except TipoEquipamentoInvalido as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)) from erro
    except (IdentificadorDuplicado, TagJaAssociada) as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(erro)) from erro
    return CadastroResposta(
        id=equipamento.id, nome=equipamento.nome, tipo_id=equipamento.tipo_id,
        tipo_nome=equipamento.tipo.nome, identificador_interno=equipamento.identificador_interno,
        descricao=equipamento.descricao, status=equipamento.status, epc=epc,
        situacao_tag="com_tag" if epc else "sem_tag",
        origem_epc=payload.origem_epc if epc else None)
