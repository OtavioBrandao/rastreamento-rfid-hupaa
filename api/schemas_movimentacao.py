"""Contrato de leitura paginada do ledger ISS-018."""

from datetime import datetime

from pydantic import BaseModel


class MovimentacaoResposta(BaseModel):
    id: int
    equipamento_id: int
    epc: str | None
    origem_registro: str
    zona_origem_id: int | None
    zona_origem: str | None
    zona_destino_id: int
    zona_destino: str
    portal_id: int | None
    portal: str | None
    passagem_id: int | None
    leitura_origem_id: int | None
    leitura_destino_id: int | None
    movimentada_em: datetime | None
    registrado_em: datetime
    justificativa: str | None
    registro_anterior_id: int | None
    referencia: str | None = None


class MovimentacaoPagina(BaseModel):
    items: list[MovimentacaoResposta]
    page: int
    size: int
    total: int
    pages: int
