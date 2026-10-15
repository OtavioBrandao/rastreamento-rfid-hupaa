"""Primitivos pequenos e testáveis para recuperação do ingestor."""

from __future__ import annotations

import errno
import math
import random
import socket
import ssl
from dataclasses import dataclass
from enum import StrEnum
from threading import Event
from typing import Callable


class FailureCategory(StrEnum):
    """Categorias operacionais sem detalhes sensíveis da exceção original."""

    PERMANENT_CONFIGURATION = "permanent_configuration"
    TEMPORARY_MQTT = "temporary_mqtt"
    TEMPORARY_DATABASE = "temporary_database"
    INVALID_MESSAGE = "invalid_message"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Parâmetros de espera exponencial com jitter proporcional."""

    initial_delay: float
    max_delay: float
    multiplier: float
    jitter: float

    def __post_init__(self) -> None:
        """Valida as invariantes dos campos após a construção da estrutura."""
        values = (self.initial_delay, self.max_delay, self.multiplier, self.jitter)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("parâmetros de backoff devem ser finitos")
        if self.initial_delay <= 0:
            raise ValueError("atraso inicial de backoff deve ser positivo")
        if self.max_delay < self.initial_delay:
            raise ValueError("atraso máximo deve ser maior ou igual ao inicial")
        if self.multiplier < 1:
            raise ValueError("multiplicador de backoff deve ser pelo menos 1")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter de backoff deve estar entre 0 e 1")


class Backoff:
    """Mantém o número de tentativas e permite interromper a espera."""

    def __init__(
        self,
        policy: BackoffPolicy,
        *,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        """Inicializa Backoff com as dependências e valores recebidos."""
        self.policy = policy
        self.random_source = random_source
        self.attempt = 0

    def next_delay(self) -> float:
        """Calcula o próximo atraso exponencial truncado com jitter e avança a tentativa."""
        base = min(
            self.policy.initial_delay
            * self.policy.multiplier**self.attempt,
            self.policy.max_delay,
        )
        self.attempt += 1
        sample = min(1.0, max(0.0, self.random_source()))
        factor = 1 - self.policy.jitter + (2 * self.policy.jitter * sample)
        return min(self.policy.max_delay, base * factor)

    def reset(self) -> None:
        """Reinicia a contagem de tentativas após recuperação confirmada."""
        self.attempt = 0

    def wait(self, stop_event: Event) -> tuple[bool, float]:
        """Retorna ``False`` quando shutdown interrompe a espera."""

        delay = self.next_delay()
        return not stop_event.wait(delay), delay


# Network unreachable error codes covering both standard POSIX and Windows socket (WSA) constants.
UNREACHABLE_ERRNOS: frozenset[int] = frozenset(
    filter(
        None,
        (
            getattr(errno, name, None)
            for name in (
                "ENETUNREACH",
                "EHOSTUNREACH",
                "ENETDOWN",
                "WSAENETUNREACH",
                "WSAEHOSTUNREACH",
                "WSAENETDOWN",
            )
        ),
    )
)

PERMANENT_CONNACK_CODES = frozenset({1, 2, 4, 5})

CONNACK_REASONS: dict[int, tuple[FailureCategory, str]] = {
    1: (FailureCategory.PERMANENT_CONFIGURATION, "protocol_rejected"),
    2: (FailureCategory.PERMANENT_CONFIGURATION, "client_id_rejected"),
    3: (FailureCategory.TEMPORARY_MQTT, "broker_unavailable"),
    4: (FailureCategory.PERMANENT_CONFIGURATION, "authentication_failure"),
    5: (FailureCategory.PERMANENT_CONFIGURATION, "authorization_failure"),
    132: (FailureCategory.PERMANENT_CONFIGURATION, "protocol_rejected"),
    133: (FailureCategory.PERMANENT_CONFIGURATION, "client_id_rejected"),
    134: (FailureCategory.PERMANENT_CONFIGURATION, "authentication_failure"),
    135: (FailureCategory.PERMANENT_CONFIGURATION, "authorization_failure"),
    136: (FailureCategory.TEMPORARY_MQTT, "broker_unavailable"),
    140: (FailureCategory.PERMANENT_CONFIGURATION, "authentication_failure"),
}


def classify_connection_exception(error: BaseException) -> tuple[FailureCategory, str]:
    """
    Classify low-level network connection exceptions into operational categories and safe reasons.

    Subclass check order is strictly preserved: ssl.SSLCertVerificationError, socket.gaierror,
    ConnectionRefusedError, and TimeoutError all inherit from OSError, so specific subclasses
    must be matched before the generic OSError fallback. Raw exception messages are never
    returned or logged to avoid leaking internal host addresses or credentials.
    """
    if isinstance(error, ssl.SSLCertVerificationError):
        return FailureCategory.PERMANENT_CONFIGURATION, "tls_certificate_failure"
    if isinstance(error, socket.gaierror):
        return FailureCategory.TEMPORARY_MQTT, "dns_failure"
    if isinstance(error, ConnectionRefusedError):
        return FailureCategory.TEMPORARY_MQTT, "broker_unavailable"
    if isinstance(error, TimeoutError):
        return FailureCategory.TEMPORARY_MQTT, "network_timeout"
    if isinstance(error, OSError):
        if error.errno in UNREACHABLE_ERRNOS:
            return FailureCategory.TEMPORARY_MQTT, "network_unreachable"
        return FailureCategory.TEMPORARY_MQTT, "network_error"
    return FailureCategory.TEMPORARY_MQTT, "network_error"


def classify_connack_code(code: int | None) -> tuple[FailureCategory, str]:
    """
    Classify MQTT CONNACK return codes (MQTT 3.1.1 return codes and MQTT 5.0 reason codes).

    Permanent configuration or authentication refusals must halt supervisor loops rather
    than retry indefinitely, while temporary broker unavailability triggers exponential backoff.
    """
    if code is not None and code in CONNACK_REASONS:
        return CONNACK_REASONS[code]
    if code in PERMANENT_CONNACK_CODES or (code is not None and code >= 128):
        return FailureCategory.PERMANENT_CONFIGURATION, "connection_rejected"
    return FailureCategory.TEMPORARY_MQTT, "broker_unavailable"
