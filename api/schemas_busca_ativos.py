"""Contrato público da busca operacional de ativos (ISS-019)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

StatusAtivo = Literal[
    "disponivel", "atencao", "offline", "fora_de_servico", "nunca_detectado"
]


class ZonaBusca(BaseModel):
    id: int
    nome: str
    referencia_planta: str | None
    setor: str
    andar: str
    caminho: str


class LeituraRecente(BaseModel):
    """Última leitura bruta da tag ativa; presença, não zona confirmada."""

    em: datetime
    leitor: str | None = None
    porta: int | None = None
    zona: str | None = None


class AtivoBusca(BaseModel):
    id: int
    nome: str
    identificador_interno: str
    tipo: str
    tipo_id: int
    epc: str | None
    status: StatusAtivo
    ultima_zona: ZonaBusca | None
    ultima_deteccao_em: datetime | None
    localizacao_desatualizada: bool | None
    ultima_leitura: LeituraRecente | None = None


class BuscaAtivosPagina(BaseModel):
    items: list[AtivoBusca]
    total: int
    page: int
    page_size: int
