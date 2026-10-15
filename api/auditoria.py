"""
Registro central da trilha de auditoria (ISS-028).

Em vez de cada serviço gravar `auditorias` à mão, um listener `after_flush`
na CLASSE `Session` (vale para toda sessão) inspeciona o que o flush acabou
de escrever nas tabelas auditadas e insere as linhas da trilha por SQL Core,
na MESMA conexão e transação: se o commit falhar, a trilha some junto; se a
trilha falhar, o commit não acontece.

Contexto de cada linha:
- autor: `definir_autor(db, usuario_id)`, chamado por `sessao_autenticada`;
- motivo: `definir_motivo(db, texto)` (ex.: comando de terminal);
- correlação: a `ContextVar` posta pelo middleware HTTP de `api/main.py`;
  fora de HTTP, um uuid4 por sessão do banco.

Eventos sem mudança de cadastro (login, logout, acesso negado) entram por
`registrar(...)`. Nada aqui grava segredo: hash de senha vira apenas
`"senha": "alterada"`.

Limites: escrita por SQL direto ou por SQLAlchemy Core (ex.: o pipeline de
ingestão) não passa pelo ORM e NÃO é auditada aqui; a ISS-018 cobre a
movimentação.
"""

import re
import uuid
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, insert, inspect, select
from sqlalchemy.orm import Session

from db.models import (
    Andar,
    Antena,
    AssociacaoTagEquipamento,
    Auditoria,
    Equipamento,
    Leitor,
    MapeamentoAntenaPortal,
    Perfil,
    Portal,
    Setor,
    Tag,
    TipoEquipamento,
    Usuario,
    Zona,
)

MODELOS_AUDITADOS = (
    TipoEquipamento, Equipamento, AssociacaoTagEquipamento, Andar, Setor, Zona,
    Leitor, Antena, Portal, MapeamentoAntenaPortal, Usuario,
)
TABELAS_AUDITADAS = frozenset(modelo.__table__.name for modelo in MODELOS_AUDITADOS)

# Nunca entram em dados_antes/dados_depois.
CAMPOS_FORA_SEMPRE = frozenset({"id", "created_at", "updated_at"})
CAMPOS_FORA_POR_TABELA = {
    # Segredo e estado de login (ruído a cada tentativa).
    "usuarios": frozenset({"senha_hash", "tentativas_falhas", "bloqueado_ate", "ultimo_login_em"}),
    # Projeção da última localização: escrita pelo pipeline (ISS-017), não é cadastro.
    # `versao` (ISS-025) é controle de concorrência, também não é cadastro.
    "equipamentos": frozenset({
        "ultima_zona_id", "ultima_deteccao_em", "ultima_passagem_id", "ultima_movimentacao_id",
        "versao",
    }),
    # Conectividade ao vivo, não cadastro.
    "leitores": frozenset({"status", "ultimo_heartbeat_em"}),
}

CHAVE_AUTOR = "auditoria.autor"
CHAVE_MOTIVO = "auditoria.motivo"
CHAVE_CORRELACAO = "auditoria.correlacao"
CHAVE_CORRECAO = "auditoria.correcao"  # ISS-025: referência da correção em curso

correlacao_da_requisicao: ContextVar[str | None] = ContextVar(
    "correlacao_da_requisicao", default=None
)
_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# --- contexto -----------------------------------------------------------------


def definir_autor(db: Session, usuario_id: int | None) -> None:
    db.info[CHAVE_AUTOR] = usuario_id


def definir_motivo(db: Session, texto: str | None) -> None:
    db.info[CHAVE_MOTIVO] = texto


def definir_correcao(db: Session, justificativa: str, referencia: str | None) -> None:
    """
    ISS-025: o próximo flush é uma correção manual — a alteração vira
    `correcao_manual`, com a justificativa como motivo. Sempre pareado com
    `encerrar_correcao` (em `finally`) para a marca não vazar na sessão.
    """
    db.info[CHAVE_MOTIVO] = justificativa
    db.info[CHAVE_CORRECAO] = {"referencia": referencia}


def encerrar_correcao(db: Session) -> None:
    db.info.pop(CHAVE_MOTIVO, None)
    db.info.pop(CHAVE_CORRECAO, None)


def correlation_id_valido(valor: str | None) -> str:
    """Aceita o id do cliente se bem formado; senão gera um novo (uuid4 hex, 32 caracteres)."""
    if valor is not None and _CORRELATION_ID.fullmatch(valor):
        return valor
    return uuid.uuid4().hex


def correlacao(db: Session) -> str:
    da_requisicao = correlacao_da_requisicao.get()
    if da_requisicao:
        return da_requisicao
    return db.info.setdefault(CHAVE_CORRELACAO, uuid.uuid4().hex)


def _autor(db: Session) -> int | None:
    return db.info.get(CHAVE_AUTOR)


# --- serialização ---------------------------------------------------------------


def _json(valor):
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def _json_raso(dados: dict | None) -> dict | None:
    """Serializa um nível (datetimes viram texto) para caber em JSONB."""
    return None if dados is None else {chave: _json(valor) for chave, valor in dados.items()}


def _colunas(objeto):
    """(chave do atributo, nome da coluna) de cada coluna mapeada."""
    for atributo in inspect(objeto).mapper.column_attrs:
        yield atributo.key, atributo.columns[0].name


def _auditavel(tabela: str, coluna: str) -> bool:
    return not (
        coluna in CAMPOS_FORA_SEMPRE
        or coluna.endswith("_normalizado")
        or coluna in CAMPOS_FORA_POR_TABELA.get(tabela, ())
    )


def _estado(objeto) -> dict:
    tabela = objeto.__table__.name
    return {
        coluna: _json(getattr(objeto, chave))
        for chave, coluna in _colunas(objeto) if _auditavel(tabela, coluna)
    }


def _epc(conexao, tag_id) -> str | None:
    return conexao.scalar(select(Tag.epc).where(Tag.id == tag_id)) if tag_id else None


def _perfil(conexao, perfil_id) -> str | None:
    return conexao.scalar(select(Perfil.nome).where(Perfil.id == perfil_id)) if perfil_id else None


# --- linhas do flush ------------------------------------------------------------


def _linha(db: Session, acao: str, objeto, antes: dict | None, depois: dict | None) -> dict:
    autor = _autor(db)
    return {
        "usuario_id": autor,
        "origem": "usuario" if autor is not None else "sistema",
        "entidade": objeto.__table__.name,
        "entidade_id": objeto.id,  # identity key ainda não existe em after_flush
        "acao": acao,
        "motivo": db.info.get(CHAVE_MOTIVO),
        "correlation_id": correlacao(db),
        "dados_antes": antes,
        "dados_depois": depois,
    }


def _criacao(db: Session, conexao, objeto) -> dict:
    depois = _estado(objeto)
    acao = "criar"
    if isinstance(objeto, AssociacaoTagEquipamento):
        acao = "vincular_epc"
        depois["epc"] = _epc(conexao, objeto.tag_id)
    elif isinstance(objeto, Usuario):
        depois["perfil"] = _perfil(conexao, objeto.perfil_id)
    return _linha(db, acao, objeto, None, depois)


def _alteracao(db: Session, conexao, objeto) -> dict | None:
    tabela = objeto.__table__.name
    estado = inspect(objeto)
    antes, depois, mudou = {}, {}, {}
    for chave, coluna in _colunas(objeto):
        historico = estado.attrs[chave].history
        if not historico.has_changes():
            continue
        velho = historico.deleted[0] if historico.deleted else None
        novo = historico.added[0] if historico.added else None
        if velho == novo:
            continue
        mudou[coluna] = (velho, novo)
        if _auditavel(tabela, coluna):
            antes[coluna], depois[coluna] = _json(velho), _json(novo)

    senha_mudou = tabela == "usuarios" and "senha_hash" in mudou
    if not depois and not senha_mudou:
        return None  # nada auditável mudou (ex.: só contador de login)
    if senha_mudou:
        depois["senha"] = "alterada"  # nunca o valor

    correcao = db.info.get(CHAVE_CORRECAO)
    if correcao is not None:
        acao = "correcao_manual"
        if correcao.get("referencia"):
            depois["referencia"] = correcao["referencia"]
    elif senha_mudou:
        acao = "alterar_senha"
    elif "ativo" in mudou:
        acao = "reativar" if mudou["ativo"][1] else "inativar"
    elif tabela == "equipamentos" and "status" in mudou:
        acao = "reativar" if mudou["status"][1] == "ativo" else "inativar"
    elif "fim" in mudou and mudou["fim"][0] is None and mudou["fim"][1] is not None:
        acao = "desvincular_epc" if tabela == "associacoes_tag_equipamento" else "inativar"
    else:
        acao = "atualizar"

    if tabela == "associacoes_tag_equipamento":
        antes["epc"] = depois["epc"] = _epc(conexao, objeto.tag_id)
    if tabela == "usuarios" and "perfil_id" in mudou:
        antes["perfil"] = _perfil(conexao, mudou["perfil_id"][0])
        depois["perfil"] = _perfil(conexao, mudou["perfil_id"][1])
    return _linha(db, acao, objeto, antes, depois)


def _exclusao(db: Session, objeto) -> dict:
    return _linha(db, "excluir", objeto, _estado(objeto), None)


def _auditado(objeto) -> bool:
    tabela = getattr(objeto, "__table__", None)
    return tabela is not None and tabela.name in TABELAS_AUDITADAS


def linhas_do_flush(db: Session) -> list[dict]:
    conexao = db.connection()
    linhas = [_criacao(db, conexao, objeto) for objeto in db.new if _auditado(objeto)]
    for objeto in db.dirty:
        if _auditado(objeto) and db.is_modified(objeto):
            linha = _alteracao(db, conexao, objeto)
            if linha is not None:
                linhas.append(linha)
    linhas.extend(_exclusao(db, objeto) for objeto in db.deleted if _auditado(objeto))
    return linhas


@event.listens_for(Session, "before_flush")
def _carregar_excluidos(db: Session, _contexto, _instancias) -> None:
    """Depois do DELETE a linha não existe mais: carrega o estado completo antes."""
    for objeto in db.deleted:
        if _auditado(objeto):
            for chave, _coluna in _colunas(objeto):
                getattr(objeto, chave)


@event.listens_for(Session, "after_flush")
def _auditar_flush(db: Session, _contexto) -> None:
    linhas = linhas_do_flush(db)
    if linhas:
        # Core, não `db.add`: estamos dentro do flush.
        db.connection().execute(insert(Auditoria.__table__), linhas)


# --- histórico ativo -----------------------------------------------------------
# Sem isto, atribuir a um atributo EXPIRADO (ex.: depois de um commit na mesma
# sessão) não carrega o valor antigo, e a trilha gravaria `antes = None`.


def _devolver_valor(_alvo, valor, _antigo, _iniciador):
    return valor


for _modelo in MODELOS_AUDITADOS:
    for _atributo in inspect(_modelo).column_attrs:
        event.listen(
            getattr(_modelo, _atributo.key), "set", _devolver_valor,
            active_history=True, retval=True,
        )


# --- eventos explícitos ----------------------------------------------------------


def registrar(
    db: Session,
    acao: str,
    *,
    entidade: str,
    entidade_id: int | None = None,
    usuario_id: int | None = None,
    origem: str | None = None,
    motivo: str | None = None,
    dados: dict | None = None,
    antes: dict | None = None,
) -> Auditoria:
    """Evento de segurança (login, logout, negação...). Sem commit: vai na transação do chamador."""
    linha = Auditoria(
        usuario_id=usuario_id,
        origem=origem or ("usuario" if usuario_id is not None else "sistema"),
        entidade=entidade,
        entidade_id=entidade_id,
        acao=acao,
        motivo=motivo,
        correlation_id=correlacao(db),
        dados_antes=_json_raso(antes),
        dados_depois=_json_raso(dados),
    )
    db.add(linha)
    return linha
