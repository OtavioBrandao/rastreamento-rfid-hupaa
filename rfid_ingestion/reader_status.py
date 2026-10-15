"""Monitoramento de leitores por contato MQTT observado, sem inferir presença de tags.

O heartbeat é um contrato opcional do software, independente do payload EZ700.
Estados são calculados com relógio UTC injetável e os mesmos limites na API e
no ingestor. Nenhum endereço, credencial ou payload arbitrário entra no painel.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import Leitor
from rfid_ingestion.repository import _safe_persistence_error
from rfid_ingestion.topics import validate_topic

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatusPolicy:
    """Limites em segundos: online até degradação, offline a partir do timeout."""

    degraded_after: float = 30
    offline_after: float = 90

    def __post_init__(self) -> None:
        """Recusa limites não finitos, não positivos ou invertidos."""
        if not (math.isfinite(self.degraded_after) and math.isfinite(self.offline_after)
                and 0 < self.degraded_after < self.offline_after):
            raise ValueError("Status exige 0 < RFID_READER_DEGRADED_SECONDS < RFID_READER_OFFLINE_SECONDS")

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> StatusPolicy:
        """Lê os mesmos limites na API e no receptor; valor vazio usa o padrão."""
        values = os.environ if source is None else source
        return cls(float(values.get("RFID_READER_DEGRADED_SECONDS") or 30),
                   float(values.get("RFID_READER_OFFLINE_SECONDS") or 90))


def classify(last_seen: datetime | None, health: str | None, now: datetime,
             policy: StatusPolicy) -> tuple[str, str]:
    """Classifica contato: limites inclusivos e degradação explícita até novo contato.

    ``now`` e ``last_seen`` exigem fuso. Ausência de mensagem indica silêncio
    observado, não diagnóstico físico. Um heartbeat degradado só é limpo por
    heartbeat online; leituras provam contato, mas não curam falha reportada.
    """
    if now.tzinfo is None or (last_seen is not None and last_seen.tzinfo is None):
        raise ValueError("Monitoramento exige instantes com fuso horário")
    if last_seen is None:
        return "nunca_conectado", "sem_contato_observado"
    age = max(0, (now - last_seen).total_seconds())
    if age >= policy.offline_after:
        return "offline", "timeout_sem_mensagens"
    if health == "degradado":
        return "degradado", "degradacao_reportada"
    if age >= policy.degraded_after:
        return "degradado", "contato_atrasado"
    return "online", "contato_recente"


def validate_heartbeat_topic(topic: str, *, subscription: bool = False) -> None:
    """Valida escopo e identidade com a gramática de leituras, trocando só o sufixo."""
    if not topic.endswith("/heartbeat"):
        raise ValueError("Tópico de heartbeat deve terminar em /heartbeat")
    validate_topic(topic[:-9] + "readings", subscription=subscription)


def heartbeat_event(topic: str, payload: bytes, retain: bool, policy: StatusPolicy,
                    now: datetime | None = None) -> dict:
    """Valida heartbeat não retido e recente; audita somente campos permitidos.

    Contrato: JSON exato ``{\"status\":\"online|degradado\",\"sent_at\":\"RFC3339\"}``.
    Até 1024 bytes, fuso obrigatório, tolerância futura de 5 s. Mensagens retidas
    ou com idade >= timeout não comprovam conexão atual. Erros nunca carregam
    o payload recebido, que poderia conter segredos ou dados indevidos.
    """
    received = now or datetime.now(timezone.utc)
    envelope = {"event_type": "reader_heartbeat", "received_at_utc": received.isoformat(),
                "canonical_event": None, "heartbeat": None, "reason": "heartbeat_invalido"}
    try:
        validate_heartbeat_topic(topic)
        if retain or len(payload) > 1024:
            return envelope
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {"status", "sent_at"}:
            return envelope
        if value["status"] not in ("online", "degradado") or not isinstance(value["sent_at"], str):
            return envelope
        sent = datetime.fromisoformat(value["sent_at"].replace("Z", "+00:00"))
        if sent.tzinfo is None or not (-5 <= (received - sent).total_seconds() < policy.offline_after):
            return envelope
        envelope["heartbeat"] = {"reader_id": topic.split("/")[4],
                                 "sent_at": sent.isoformat(), "health": value["status"]}
        envelope["reason"] = None
    except (ValueError, TypeError, UnicodeDecodeError):
        pass
    return envelope


def contacts(envelopes: list[dict]) -> list[dict]:
    """Extrai contatos válidos; leituras retidas e mensagens inválidas não renovam status."""
    result = []
    for event in envelopes:
        heartbeat = event.get("heartbeat")
        if heartbeat:
            seen = min(datetime.fromisoformat(event["received_at_utc"]),
                       datetime.fromisoformat(heartbeat["sent_at"]))
            result.append({**heartbeat, "seen": seen,
                           "source": "heartbeat"})
        elif event.get("canonical_event") and not event.get("retain"):
            result.append({"reader_id": event["reader_id"],
                           "seen": datetime.fromisoformat(event["received_at_utc"]),
                           "source": "leitura"})
    return result


class ReaderMonitor:
    """Persiste contatos e transições sem criar leituras nem movimentações.

    Uma instância pertence à thread de persistência. O sweep avança estados
    mesmo sem tráfego; o cálculo da API independe de esse worker estar ativo.
    Locks em ordem de PK evitam regressão com lotes e receptores concorrentes.
    """

    def __init__(self, engine: Engine, policy: StatusPolicy | None = None,
                 *, clock: Callable[[], datetime] | None = None) -> None:
        """Injeta banco, política e relógio; contador representa transições confirmadas."""
        self.engine = engine
        self.policy = policy or StatusPolicy.from_env()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.next_sweep: datetime | None = None
        self.transitions = 0

    def observe(self, observations: list[dict]) -> None:
        """Grava contatos monotônicos de leitores ativos conhecidos, antes do PUBACK.

        Heartbeats atrasados não revertem saúde nem heartbeat mais novo. Leituras
        renovam contato, preservando eventual degradação explícita. A identificação
        vem do tópico autorizado no broker; o payload não escolhe outro leitor.
        """
        if not observations:
            return
        self._persist(observations)

    def sweep(self) -> None:
        """Reavalia silêncio uma vez por segundo; falhas de banco seguem recuperação MQTT."""
        now = self.clock()
        if self.next_sweep is not None and now < self.next_sweep:
            return
        self._persist([])
        self.next_sweep = now + timedelta(seconds=1)

    def _persist(self, observations: list[dict]) -> None:
        """Confirma atualizações e depois emite logs seguros para cada transição."""
        changes = []
        now = self.clock()
        try:
            with Session(self.engine) as db, db.begin():
                readers = db.scalars(select(Leitor).where(Leitor.ativo.is_(True))
                                     .order_by(Leitor.id).with_for_update()).all()
                by_id = {reader.reader_id: reader for reader in readers}
                for contact in observations:
                    reader = by_id.get(contact["reader_id"])
                    if reader is None:
                        continue
                    seen = contact["seen"]
                    if contact["source"] == "heartbeat":
                        sent = datetime.fromisoformat(contact["sent_at"])
                        if reader.ultimo_heartbeat_em is not None and sent <= reader.ultimo_heartbeat_em:
                            continue
                        reader.ultimo_heartbeat_em = sent
                        if reader.ultimo_contato_em is None or seen >= reader.ultimo_contato_em:
                            reader.saude_reportada = contact["health"]
                    if reader.ultimo_contato_em is None or seen > reader.ultimo_contato_em:
                        reader.ultimo_contato_em = seen
                        reader.origem_ultimo_contato = contact["source"]
                for reader in readers:
                    state, reason = classify(reader.ultimo_contato_em, reader.saude_reportada, now, self.policy)
                    if reader.status != state:
                        changes.append({"leitor_id": reader.id, "anterior": reader.status,
                                        "status": state, "motivo": reason})
                        reader.status = state
        except SQLAlchemyError as error:
            raise _safe_persistence_error(error) from None
        for change in changes:
            self.transitions += 1
            LOGGER.info(json.dumps({"event_type": "reader_status_changed", **change,
                                    "transitions_total": self.transitions}))
