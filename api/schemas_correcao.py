"""
Schemas da correção manual (ISS-025). `extra="forbid"`: campo desconhecido
é 422, nunca ignorado em silêncio — numa correção auditada, um campo com
nome errado não pode virar "nada mudou".
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _CorrecaoBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    justificativa: str = Field(..., max_length=1000)
    referencia: str | None = Field(default=None, max_length=255)
    versao_esperada: int = Field(..., ge=1)

    @field_validator("justificativa")
    @classmethod
    def _justificativa_preenchida(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("justificativa é obrigatória")
        return valor

    @field_validator("referencia")
    @classmethod
    def _referencia_opcional(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return valor.strip() or None


class CorrecaoLocalizacaoEntrada(_CorrecaoBase):
    zona_id: int = Field(..., gt=0)


class CorrecaoCadastroEntrada(_CorrecaoBase):
    """Campos opcionais; só os informados são considerados (e só os diferentes mudam)."""

    nome: str | None = Field(default=None, max_length=255)
    tipo_id: int | None = Field(default=None, gt=0)
    identificador_interno: str | None = Field(default=None, max_length=255)
    descricao: str | None = None

    @field_validator("nome", "identificador_interno")
    @classmethod
    def _texto_preenchido(cls, valor: str | None) -> str | None:
        if valor is None:
            raise ValueError("não pode ser nulo")
        valor = valor.strip()
        if not valor:
            raise ValueError("campo não pode ser vazio nem conter apenas espaços")
        return valor


class CorrecaoLocalizacaoResposta(BaseModel):
    equipamento_id: int
    zona_anterior_id: int | None
    zona_id: int
    movimentacao_id: int
    movimentada_em: datetime
    versao: int
