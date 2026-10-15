"""
Correção manual de localização e de cadastro (ISS-025).

Regras comuns:
- só administrador chega aqui (`equipamentos:corrigir`, no router);
- justificativa obrigatória e referência opcional, gravadas na trilha;
- concorrência pela versão otimista do equipamento: o cliente envia a
  `versao_esperada` que viu; se mudou (PATCH, outra correção, passagem do
  pipeline), `ConflitoDeVersao` (409) e nada é gravado;
- o equipamento é TRAVADO antes de qualquer conferência, então duas
  correções simultâneas se serializam e a segunda vê a versão nova;
- um único commit; qualquer recusa faz rollback antes de subir.

Localização: vale A PARTIR DE AGORA (relógio do servidor), entra no ledger
da ISS-018 como `correcao_manual` e move a projeção pelo mesmo
`update_location` do pipeline. Cadastro: nome, tipo, descrição e
identificador interno (patrimônio) — a única forma de corrigir o
patrimônio; não toca no histórico de movimentações.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import auditoria
from api.normalizacao import normalizar_nome
from api.service_equipamento import (
    EquipamentoNaoEncontrado,
    IdentificadorDuplicado,
    TipoEquipamentoInvalido,
    _validar_tipo_ativo,
    buscar_por_id,
)
from db.models import Equipamento, Zona
from rfid_location.repository import lock_equipment
from rfid_location.service import ConflitoDeVersao, CorrecaoRecusada, corrigir_localizacao

__all__ = [
    "ConflitoDeVersao", "CorrecaoRecusada", "EquipamentoInativo", "EquipamentoNaoEncontrado",
    "IdentificadorDuplicado", "SemMudanca", "TipoEquipamentoInvalido", "ZonaInvalida",
    "corrigir_cadastro", "corrigir_localizacao_equipamento",
]


class EquipamentoInativo(Exception):
    """Falha de domínio: equipamento inativo; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, equipamento_id: int) -> None:
        """Inicializa EquipamentoInativo com as dependências e valores recebidos."""
        super().__init__(f"Equipamento {equipamento_id} está inativo: reative antes de corrigir.")


class ZonaInvalida(Exception):
    """Falha de domínio: zona invalida; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, zona_id: int) -> None:
        """Inicializa ZonaInvalida com as dependências e valores recebidos."""
        super().__init__(f"Zona {zona_id} inexistente ou inativa.")


class SemMudanca(Exception):
    """Falha de domínio: sem mudanca; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self) -> None:
        """Inicializa SemMudanca com as dependências e valores recebidos."""
        super().__init__("Nada a corrigir: os valores informados são iguais aos atuais.")


def _nome_da_zona(conexao, zona_id: int | None) -> str | None:
    """Resolve o nome da zona para a resposta de correção manual."""
    if zona_id is None:
        return None
    return conexao.scalar(select(Zona.nome).where(Zona.id == zona_id))


def corrigir_localizacao_equipamento(
    db: Session, *, autor_id: int, equipamento_id: int, zona_id: int, justificativa: str,
    referencia: str | None, versao_esperada: int, agora: datetime,
):
    """Corrige localizacao equipamento."""
    conexao = db.connection()
    atual = lock_equipment(conexao, equipamento_id)  # trava ANTES de conferir status
    if atual is None:
        db.rollback()
        raise EquipamentoNaoEncontrado(equipamento_id)
    if atual.status != "ativo":
        db.rollback()
        raise EquipamentoInativo(equipamento_id)
    zona = conexao.execute(
        select(Zona.id, Zona.nome, Zona.ativo).where(Zona.id == zona_id)
    ).one_or_none()
    if zona is None or not zona.ativo:
        db.rollback()
        raise ZonaInvalida(zona_id)

    antes = {
        "ultima_zona_id": atual.ultima_zona_id,
        "zona": _nome_da_zona(conexao, atual.ultima_zona_id),
        "ultima_deteccao_em": atual.ultima_deteccao_em,
    }
    try:
        resultado = corrigir_localizacao(
            conexao, equipment_id=equipamento_id, destination_zone_id=zona_id,
            movimentada_em=agora, justificativa=justificativa, referencia=referencia,
            versao_esperada=versao_esperada,
        )
    except (CorrecaoRecusada, ConflitoDeVersao):
        db.rollback()
        raise

    dados = {
        "ultima_zona_id": zona_id,
        "zona": zona.nome,
        "ultima_deteccao_em": agora,
        "movimentacao_id": resultado.movement_id,
    }
    if referencia:
        dados["referencia"] = referencia
    auditoria.registrar(
        db, "correcao_manual", entidade="equipamentos", entidade_id=equipamento_id,
        usuario_id=autor_id, motivo=justificativa, antes=antes, dados=dados,
    )
    db.commit()
    return resultado


def corrigir_cadastro(
    db: Session, *, equipamento_id: int, justificativa: str, referencia: str | None,
    versao_esperada: int, nome: str | None, tipo_id: int | None,
    identificador_interno: str | None, descricao: str | None, descricao_informada: bool,
) -> Equipamento:
    """Corrige cadastro."""
    equipamento = db.scalar(
        select(Equipamento).where(Equipamento.id == equipamento_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if equipamento is None:
        db.rollback()
        raise EquipamentoNaoEncontrado(equipamento_id)
    if equipamento.versao != versao_esperada:
        versao_atual = equipamento.versao
        db.rollback()
        raise ConflitoDeVersao(versao_atual)

    # Só o que é DIFERENTE do atual muda (e entra na trilha).
    mudancas: dict = {}
    if nome is not None and nome != equipamento.nome:
        mudancas["nome"] = nome
    if tipo_id is not None and tipo_id != equipamento.tipo_id:
        try:
            _validar_tipo_ativo(db, tipo_id)
        except TipoEquipamentoInvalido:
            db.rollback()
            raise
        mudancas["tipo_id"] = tipo_id
    if (identificador_interno is not None
            and identificador_interno != equipamento.identificador_interno):
        mudancas["identificador_interno"] = identificador_interno
        mudancas["identificador_interno_normalizado"] = normalizar_nome(identificador_interno)
    if descricao_informada and descricao != equipamento.descricao:
        mudancas["descricao"] = descricao
    if not mudancas:
        db.rollback()
        raise SemMudanca()

    auditoria.definir_correcao(db, justificativa, referencia)
    try:
        for campo, valor in mudancas.items():
            setattr(equipamento, campo, valor)
        db.flush()
    except IntegrityError as erro:
        db.rollback()
        raise IdentificadorDuplicado(identificador_interno or "") from erro
    finally:
        auditoria.encerrar_correcao(db)
    db.commit()
    return buscar_por_id(db, equipamento_id)
