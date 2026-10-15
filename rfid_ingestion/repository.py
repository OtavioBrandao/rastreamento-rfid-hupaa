"""Persistência transacional de eventos canônicos, independente de MQTT."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy import and_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, DisconnectionError, OperationalError, SQLAlchemyError

from db.models import Antena, Leitor, LeituraBruta
from rfid_ingestion.resilience import FailureCategory


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """Estrutura Persistence Result usada por rfid_ingestion.repository.

    Campos: status, reading_id, reason, antenna_id."""
    status: Literal["inserted", "duplicate", "rejected"]
    reading_id: int | None = None
    reason: str | None = None
    antenna_id: int | None = None


class PersistenceError(RuntimeError):
    """Falha de banco: não confirmar processamento nem divulgar parâmetros."""

    def __init__(
        self,
        message: str,
        category: FailureCategory = FailureCategory.TEMPORARY_DATABASE,
    ) -> None:
        """Inicializa PersistenceError com as dependências e valores recebidos."""
        super().__init__(message)
        self.category = category


def _database_failure_category(error: SQLAlchemyError) -> FailureCategory:
    """Classifica SQLSTATE e falhas DBAPI como indisponibilidade temporária ou erro permanente."""
    original = getattr(error, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if isinstance(sqlstate, str):
        if sqlstate.startswith("08") or sqlstate in {
            "53300",  # too_many_connections
            "53400",  # configuration_limit_exceeded
            "57P01",  # admin_shutdown
            "57P02",  # crash_shutdown
            "57P03",  # cannot_connect_now
        }:
            return FailureCategory.TEMPORARY_DATABASE
        return FailureCategory.PERMANENT_CONFIGURATION
    message = str(original).lower()
    if any(
        marker in message
        for marker in (
            "password authentication failed",
            "authentication method",
            "no password supplied",
            "pg_hba.conf rejects connection",
            "does not exist",
            "certificate verify failed",
        )
    ):
        return FailureCategory.PERMANENT_CONFIGURATION
    if isinstance(error, (OperationalError, DisconnectionError)):
        return FailureCategory.TEMPORARY_DATABASE
    if isinstance(error, DBAPIError) and error.connection_invalidated:
        return FailureCategory.TEMPORARY_DATABASE
    return FailureCategory.PERMANENT_CONFIGURATION


def _safe_persistence_error(error: SQLAlchemyError) -> PersistenceError:
    """Converte erro SQLAlchemy em PersistenceError sem divulgar parâmetros de conexão."""
    return PersistenceError("falha PostgreSQL", _database_failure_category(error))

def _utc(value: str) -> datetime:
    """Converte texto ISO em datetime UTC e recusa instante sem fuso."""
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp de persistência exige fuso horário")
    return instant.astimezone(timezone.utc)


def _linha(canonical: dict, envelope: dict, antena_id: int) -> dict:
    """Monta a linha PostgreSQL a partir do evento canônico e do envelope de recepção."""
    return {
        "event_id": canonical["event_id"], "antena_id": antena_id,
        "epc": canonical["epc"], "rssi": canonical["rssi"],
        "lido_em": _utc(canonical["timestamp"]),
        "recebido_em": _utc(envelope["received_at_utc"]),
        "dados_origem": {"metadata": canonical.get("metadata", {}),
                         **{key: envelope[key] for key in
                            ("topic", "adapter", "qos", "retain")}},
    }


class RawReadingRepository:
    # Topologia ativa muda raramente; o cache evita uma ida ao banco por leitura
    # em bancos remotos. Só resultados encontrados são guardados.
    """Persiste eventos canônicos idempotentes e resolve antenas ativas.

    O caminho em lote utiliza conexão dedicada em autocommit e cache topológico
    com TTL de 30 s. A instância pertence à thread de persistência; não é um
    repositório compartilhável livremente entre threads."""
    TOPOLOGY_TTL_SECONDS = 30.0

    def __init__(self, engine: Engine, *, clock: Callable[[], float] = time.monotonic):
        """Inicializa RawReadingRepository com as dependências e valores recebidos."""
        self.engine = engine
        self._clock = clock
        self._topology: dict[tuple[str, int], tuple[int, float]] = {}
        self._conexao_lote: Connection | None = None

    def _conexao(self) -> Connection:
        """Conexão dedicada aos lotes, em autocommit e mantida aberta.

        Evita o ping do pool, o BEGIN e o COMMIT a cada lote: com a topologia em
        cache, o lote é um único INSERT, atômico por ser um só comando.
        """
        conexao = self._conexao_lote
        if conexao is None or conexao.closed or conexao.invalidated:
            conexao = self.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            self._conexao_lote = conexao
        return conexao

    def _descartar_conexao(self) -> None:
        """Invalida e fecha a conexão dedicada de lotes após uma falha PostgreSQL."""
        conexao, self._conexao_lote = self._conexao_lote, None
        if conexao is not None:
            try:
                conexao.invalidate()
                conexao.close()
            except SQLAlchemyError:
                pass

    def _antenas(self, connection, chaves: set[tuple[str, int]]
                 ) -> dict[tuple[str, int], int | None]:
        """Antena ativa por (reader_id, porta); ``None`` se leitor ou antena faltar.

        A chave ausente do resultado indica leitor desconhecido.
        """
        agora = self._clock()
        resultado: dict[tuple[str, int], int | None] = {}
        faltantes = set()
        for chave in chaves:
            guardado = self._topology.get(chave)
            if guardado is not None and agora - guardado[1] < self.TOPOLOGY_TTL_SECONDS:
                resultado[chave] = guardado[0]
            else:
                faltantes.add(chave)
        if faltantes:
            leitores = {reader for reader, _ in faltantes}
            linhas = connection.execute(
                select(Leitor.reader_id, Antena.porta_numero, Antena.id).outerjoin(
                    Antena, and_(Antena.leitor_id == Leitor.id, Antena.ativo.is_(True))
                ).where(Leitor.reader_id.in_(leitores))
            ).all()
            conhecidos = {reader for reader, _, _ in linhas}
            antenas = {(reader, porta): antena for reader, porta, antena in linhas
                       if antena is not None}
            for chave in faltantes:
                if chave[0] not in conhecidos:
                    continue
                antena = antenas.get(chave)
                resultado[chave] = antena
                if antena is not None:
                    self._topology[chave] = (antena, agora)
        return resultado

    def persist_many(self, envelopes: list[dict]) -> list[PersistenceResult]:
        """Grava o lote num único INSERT; resultados na ordem dos envelopes.

        Com banco remoto, o custo é dominado pelas idas e voltas. Com a topologia
        em cache, o lote inteiro custa uma: o INSERT de várias linhas em
        autocommit, atômico por ser um só comando. Só usado pela thread de
        gravação, dona da conexão dedicada.
        """
        resultados: list[PersistenceResult | None] = [None] * len(envelopes)
        validos = []
        for indice, envelope in enumerate(envelopes):
            if envelope["canonical_event"] is None:
                resultados[indice] = PersistenceResult("rejected", reason="invalid_input")
            else:
                validos.append(indice)
        if not validos:
            return resultados  # type: ignore[return-value]
        try:
            connection = self._conexao()
            chaves = {(envelopes[i]["canonical_event"]["reader_id"],
                       envelopes[i]["canonical_event"]["antenna"]) for i in validos}
            antenas = self._antenas(connection, chaves)
            linhas = []
            destino: list[tuple[int, int]] = []
            for indice in validos:
                canonical = envelopes[indice]["canonical_event"]
                chave = (canonical["reader_id"], canonical["antenna"])
                if chave not in antenas:
                    resultados[indice] = PersistenceResult("rejected",
                                                           reason="unknown_reader")
                elif antenas[chave] is None:
                    resultados[indice] = PersistenceResult("rejected",
                                                           reason="unknown_antenna")
                else:
                    linhas.append(_linha(canonical, envelopes[indice], antenas[chave]))
                    destino.append((indice, antenas[chave]))
            inseridos: dict[str, int] = {}
            if linhas:
                statement = insert(LeituraBruta).values(linhas).on_conflict_do_nothing(
                    index_elements=[LeituraBruta.event_id]
                ).returning(LeituraBruta.event_id, LeituraBruta.id)
                inseridos = dict(connection.execute(statement).all())
            # Em autocommit, o INSERT já está confirmado quando retorna.
            for indice, antena_id in destino:
                event_id = envelopes[indice]["canonical_event"]["event_id"]
                # Repetição no mesmo lote: só a primeira ocorrência foi inserida.
                reading_id = inseridos.pop(event_id, None)
                resultados[indice] = (
                    PersistenceResult("inserted", reading_id, antenna_id=antena_id)
                    if reading_id is not None else PersistenceResult("duplicate"))
            return resultados  # type: ignore[return-value]
        except SQLAlchemyError as error:
            self._descartar_conexao()
            raise _safe_persistence_error(error) from None

    def persist(self, envelope: dict) -> PersistenceResult:
        """Grava uma leitura em transação, deduplicada por event_id.

        Resolve leitor/porta em antena ativa. Devolve inserted, duplicate ou rejected
        somente depois de finalizar a transação; erros de banco viram PersistenceError."""
        canonical = envelope["canonical_event"]
        if canonical is None:
            return PersistenceResult("rejected", reason="invalid_input")
        try:
            with self.engine.begin() as connection:
                topology = connection.execute(
                    select(Leitor.id, Antena.id).outerjoin(
                        Antena, and_(Antena.leitor_id == Leitor.id,
                                     Antena.porta_numero == canonical["antenna"],
                                     Antena.ativo.is_(True))
                    ).where(Leitor.reader_id == canonical["reader_id"])
                ).one_or_none()
                if topology is None:
                    return PersistenceResult("rejected", reason="unknown_reader")
                if topology[1] is None:
                    return PersistenceResult("rejected", reason="unknown_antenna")
                statement = insert(LeituraBruta).values(
                    event_id=canonical["event_id"], antena_id=topology[1],
                    epc=canonical["epc"], rssi=canonical["rssi"],
                    lido_em=_utc(canonical["timestamp"]),
                    recebido_em=_utc(envelope["received_at_utc"]),
                    dados_origem={"metadata": canonical.get("metadata", {}),
                                  **{key: envelope[key] for key in
                                     ("topic", "adapter", "qos", "retain")}},
                ).on_conflict_do_nothing(
                    index_elements=[LeituraBruta.event_id]
                ).returning(LeituraBruta.id)
                reading_id = connection.execute(statement).scalar_one_or_none()
            # Só devolver sucesso após a confirmação da transação.
            return (
                PersistenceResult(
                    "inserted", reading_id, antenna_id=topology[1]
                )
                if reading_id is not None
                else PersistenceResult("duplicate")
            )
        except SQLAlchemyError as error:
            raise _safe_persistence_error(error) from None

    def check_available(self) -> None:
        """Executa uma sonda mínima; nunca inclui a URL ou parâmetros no erro."""

        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise _safe_persistence_error(error) from None
