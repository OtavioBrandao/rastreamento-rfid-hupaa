"""
Pydantic schemas for logical portal topology and antenna mappings (ISS-013).

Defines request/response contracts separating hardware inventory CRUD from
inference-oriented logical topology (sides A/B, zones, and operational functions).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LadoMapeamento = Literal["a", "b"]
FuncaoMapeamento = Literal["entrada", "saida", "auxiliar"]


class MapeamentoCriar(BaseModel):
    """Contrato de dados Mapeamento Criar; valida campos e serializa a resposta da API."""
    antena_id: int = Field(..., gt=0, description="ID da antena física cadastrada.")
    lado: LadoMapeamento = Field(..., description="Lado lógico do portal ('a' ou 'b').")
    funcao: FuncaoMapeamento = Field(
        ..., description="Função operacional ('entrada', 'saida' ou 'auxiliar')."
    )
    zona_id: int | None = Field(
        default=None,
        gt=0,
        description="ID opcional da zona adjacente (se informado, deve coincidir com o lado do portal).",
    )


class MapeamentoAtualizar(BaseModel):
    """Contrato de dados Mapeamento Atualizar; valida campos e serializa a resposta da API."""
    lado: LadoMapeamento | None = Field(
        default=None, description="Novo lado lógico do portal ('a' ou 'b')."
    )
    funcao: FuncaoMapeamento | None = Field(
        default=None, description="Nova função operacional ('entrada', 'saida' ou 'auxiliar')."
    )
    zona_id: int | None = Field(
        default=None,
        gt=0,
        description="ID da nova zona adjacente (se informado, deve coincidir com o novo lado).",
    )


class MapeamentoResposta(BaseModel):
    """Contrato de dados Mapeamento Resposta; valida campos e serializa a resposta da API."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    antena_id: int
    portal_id: int
    lado: str
    zona_id: int
    funcao: str
    inicio: datetime
    fim: datetime | None
    created_at: datetime


class ZonaResumo(BaseModel):
    """Contrato de dados Zona Resumo; valida campos e serializa a resposta da API."""
    id: int
    nome: str


class ItemTopologiaAntenaResposta(BaseModel):
    """Contrato de dados Item Topologia Antena Resposta; valida campos e serializa a resposta da API."""
    mapeamento_id: int
    antena_id: int
    reader_id: str
    porta_numero: int
    lado: str
    zona_id: int
    funcao: str
    inicio: datetime


class TopologiaPortalResposta(BaseModel):
    """
    Complete active portal topology payload for the ISS-015 passage inference engine.
    Supplies all mapping details and reader identification in a single query path.
    """

    portal_id: int
    nome: str
    ativo: bool
    zona_a: ZonaResumo
    zona_b: ZonaResumo
    antenas: list[ItemTopologiaAntenaResposta]
