"""
Schemas Pydantic da associação EPC <-> equipamento (ISS-010).

Módulo próprio, mesmo padrão de `api/schemas_equipamento.py`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.epc import EpcInvalido, normalizar_epc


class AssociarPayload(BaseModel):
    epc: str = Field(..., min_length=1, max_length=64)

    @field_validator("epc")
    @classmethod
    def validar_epc(cls, valor: str) -> str:
        try:
            return normalizar_epc(valor)
        except EpcInvalido as error:
            raise ValueError(str(error)) from error


class SubstituirPayload(BaseModel):
    epc_novo: str = Field(..., min_length=1, max_length=64)

    @field_validator("epc_novo")
    @classmethod
    def validar_epc(cls, valor: str) -> str:
        try:
            return normalizar_epc(valor)
        except EpcInvalido as error:
            raise ValueError(str(error)) from error


class AssociacaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    epc: str
    equipamento_id: int
    equipamento_nome: str
    inicio: datetime
    fim: datetime | None


class ResolucaoEpcOut(BaseModel):
    epc: str
    equipamento_id: int
    equipamento_nome: str
    associacao_id: int
    inicio: datetime
