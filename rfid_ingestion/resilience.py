"""Primitivos pequenos e testáveis para recuperação do ingestor."""

from __future__ import annotations

import math
import random
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
        self.policy = policy
        self.random_source = random_source
        self.attempt = 0

    def next_delay(self) -> float:
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
        self.attempt = 0

    def wait(self, stop_event: Event) -> tuple[bool, float]:
        """Retorna ``False`` quando shutdown interrompe a espera."""

        delay = self.next_delay()
        return not stop_event.wait(delay), delay
