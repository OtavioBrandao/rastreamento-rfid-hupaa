"""Consolidação temporal de leituras RFID por EPC e antena física."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock


@dataclass(frozen=True, slots=True)
class DebounceReading:
    """Leitura bruta já persistida e elegível para o debounce."""

    event_id: str
    reading_id: int
    epc: str
    antenna_id: int
    observed_at: datetime
    rssi: float | None = None

    def __post_init__(self) -> None:
        """Valida as invariantes dos campos após a construção da estrutura."""
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at exige fuso horário")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))


@dataclass(frozen=True, slots=True)
class ConsolidatedObservation:
    """Rajada de leituras consecutivas da mesma origem física."""

    epc: str
    antenna_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    reading_count: int
    first_reading_id: int
    last_reading_id: int
    first_event_id: str
    last_event_id: str
    rssi_min: float | None
    rssi_max: float | None
    rssi_mean: float | None


@dataclass(frozen=True, slots=True)
class DebounceCounters:
    """Estrutura Debounce Counters usada por rfid_inference.debounce.

    Campos: readings_received, readings_incorporated, observations_finalized, late_events."""
    readings_received: int = 0
    readings_incorporated: int = 0
    observations_finalized: int = 0
    late_events: int = 0


@dataclass(frozen=True, slots=True)
class DebounceResult:
    """Estrutura Debounce Result usada por rfid_inference.debounce.

    Campos: accepted, incorporated, late, finalized."""
    accepted: bool
    incorporated: bool
    late: bool
    finalized: tuple[ConsolidatedObservation, ...] = ()


@dataclass(slots=True)
class _KeyState:
    """Estrutura _Key State usada por rfid_inference.debounce.

    Campos: readings, max_seen_at, last_received_at_monotonic, finalized_until."""
    readings: list[DebounceReading]
    max_seen_at: datetime
    last_received_at_monotonic: float
    finalized_until: datetime | None = None


class DebounceProcessor:
    """Agrupa leituras usando event time e tolerância de reordenação.

    Leituras com intervalo menor ou igual à janela pertencem à mesma
    observação. A tolerância mantém um buffer ordenável; eventos anteriores ao
    watermark são tardios e não alteram resultados já finalizados.

    ``max_observation`` limita a duração de uma observação que segue recebendo
    leituras: a parte já estável (até o watermark) é finalizada e a seguinte
    continua como nova observação. Sem isso, uma tag parada no alcance da
    antena de destino só gerava observação ao sair dele, atrasando a passagem
    ou deixando o candidato de origem expirar.
    """

    def __init__(self, window: timedelta, out_of_order_tolerance: timedelta,
                 max_observation: timedelta | None = None) -> None:
        """Inicializa DebounceProcessor com as dependências e valores recebidos."""
        if window <= timedelta(0):
            raise ValueError("window deve ser positiva")
        if out_of_order_tolerance < timedelta(0):
            raise ValueError("out_of_order_tolerance não pode ser negativa")
        if max_observation is not None and max_observation <= timedelta(0):
            raise ValueError("max_observation deve ser positiva")
        self.window = window
        self.out_of_order_tolerance = out_of_order_tolerance
        self.max_observation = max_observation
        self._states: dict[tuple[str, int], _KeyState] = {}
        self._counters = DebounceCounters()
        self._lock = Lock()

    @classmethod
    def from_milliseconds(
        cls, window_ms: int, out_of_order_tolerance_ms: int, max_observation_ms: int = 0
    ) -> DebounceProcessor:
        """Constrói o processador em milissegundos; ``max_observation_ms`` 0 desativa o limite."""
        return cls(
            timedelta(milliseconds=window_ms),
            timedelta(milliseconds=out_of_order_tolerance_ms),
            timedelta(milliseconds=max_observation_ms) if max_observation_ms else None,
        )

    @property
    def counters(self) -> DebounceCounters:
        """Devolve o snapshot atual dos contadores sob proteção do lock do processador."""
        with self._lock:
            return self._counters

    def add(
        self, reading: DebounceReading, *, received_at_monotonic: float | None = None
    ) -> DebounceResult:
        """Adiciona uma leitura e devolve observações que ficaram estáveis."""

        if received_at_monotonic is None:
            received_at_monotonic = time.monotonic()
        key = (reading.epc, reading.antenna_id)
        with self._lock:
            self._increment(readings_received=1)
            state = self._states.get(key)
            if state is None:
                state = _KeyState([], reading.observed_at, received_at_monotonic)
                self._states[key] = state
            else:
                watermark = state.max_seen_at - self.out_of_order_tolerance
                if reading.observed_at < watermark or (
                    state.finalized_until is not None
                    and reading.observed_at <= state.finalized_until
                ):
                    self._increment(late_events=1)
                    return DebounceResult(False, False, True)
                state.max_seen_at = max(state.max_seen_at, reading.observed_at)
                state.last_received_at_monotonic = received_at_monotonic

            state.readings.append(reading)
            state.readings.sort(key=lambda item: (item.observed_at, item.event_id))
            groups = self._group(state.readings)
            incorporated = any(
                reading in group and len(group) > 1 for group in groups
            )
            if incorporated:
                self._increment(readings_incorporated=1)

            watermark = state.max_seen_at - self.out_of_order_tolerance
            finalized_groups: list[list[DebounceReading]] = []
            for group in groups:
                if group[-1].observed_at + self.window >= watermark:
                    break
                finalized_groups.append(group)

            finalized = self._finalize(state, finalized_groups)
            open_groups = groups[len(finalized_groups):]
            if (
                self.max_observation is not None
                and open_groups
                and watermark - open_groups[0][0].observed_at >= self.max_observation
            ):
                stable = [item for item in open_groups[0] if item.observed_at <= watermark]
                finalized += self._finalize(state, [stable], continuing=True)
            return DebounceResult(True, incorporated, False, finalized)

    def advance_time(self, now_monotonic: float) -> tuple[ConsolidatedObservation, ...]:
        """Finaliza chaves silenciosas sem exigir outra leitura da mesma antena.

        O relógio monotônico mede apenas o silêncio desde a última chegada.
        Timestamps das leituras continuam determinando grupos e referências.
        """

        with self._lock:
            finalized: list[ConsolidatedObservation] = []
            silence_seconds = (self.window + self.out_of_order_tolerance).total_seconds()
            for state in self._states.values():
                if (
                    state.readings
                    and now_monotonic - state.last_received_at_monotonic > silence_seconds
                ):
                    finalized.extend(self._finalize(state, self._group(state.readings)))
            finalized.sort(
                key=lambda item: (
                    item.first_seen_at,
                    item.epc,
                    item.antenna_id,
                    item.first_event_id,
                )
            )
            return tuple(finalized)

    def flush(self) -> tuple[ConsolidatedObservation, ...]:
        """Finaliza deterministicamente todas as observações ainda pendentes."""

        with self._lock:
            finalized: list[ConsolidatedObservation] = []
            for key in sorted(self._states):
                state = self._states[key]
                finalized.extend(self._finalize(state, self._group(state.readings)))
            finalized.sort(
                key=lambda item: (
                    item.first_seen_at,
                    item.epc,
                    item.antenna_id,
                    item.first_event_id,
                )
            )
            return tuple(finalized)

    def _finalize(
        self, state: _KeyState, groups: list[list[DebounceReading]], *,
        continuing: bool = False,
    ) -> tuple[ConsolidatedObservation, ...]:
        """Consolida grupos, remove leituras finalizadas e avança o limite de event time do estado.

        ``continuing`` corta uma observação ainda ativa: o limite fica na última
        leitura finalizada, para a continuação seguinte não ser tratada como tardia.
        """
        observations = tuple(self._observation(group) for group in groups)
        if observations:
            finalized_ids = {item.event_id for group in groups for item in group}
            state.readings = [
                item for item in state.readings if item.event_id not in finalized_ids
            ]
            margin = timedelta(0) if continuing else self.window
            state.finalized_until = max(
                observation.last_seen_at + margin for observation in observations
            )
            self._increment(observations_finalized=len(observations))
        return observations

    def _group(
        self, readings: list[DebounceReading]
    ) -> list[list[DebounceReading]]:
        """Agrupa leituras ordenadas quando o intervalo entre vizinhas não supera a janela."""
        groups: list[list[DebounceReading]] = []
        for reading in readings:
            if not groups or reading.observed_at - groups[-1][-1].observed_at > self.window:
                groups.append([reading])
            else:
                groups[-1].append(reading)
        return groups

    @staticmethod
    def _observation(readings: list[DebounceReading]) -> ConsolidatedObservation:
        """Resume um grupo em primeira/última evidência, contagem e estatísticas de RSSI conhecido."""
        first = readings[0]
        last = readings[-1]
        rssi_values = [float(item.rssi) for item in readings if item.rssi is not None]
        return ConsolidatedObservation(
            epc=first.epc,
            antenna_id=first.antenna_id,
            first_seen_at=first.observed_at,
            last_seen_at=last.observed_at,
            reading_count=len(readings),
            first_reading_id=first.reading_id,
            last_reading_id=last.reading_id,
            first_event_id=first.event_id,
            last_event_id=last.event_id,
            rssi_min=min(rssi_values) if rssi_values else None,
            rssi_max=max(rssi_values) if rssi_values else None,
            rssi_mean=sum(rssi_values) / len(rssi_values) if rssi_values else None,
        )

    def _increment(
        self,
        *,
        readings_received: int = 0,
        readings_incorporated: int = 0,
        observations_finalized: int = 0,
        late_events: int = 0,
    ) -> None:
        """Substitui o snapshot de contadores somando os incrementos informados."""
        current = self._counters
        self._counters = DebounceCounters(
            readings_received=current.readings_received + readings_received,
            readings_incorporated=current.readings_incorporated + readings_incorporated,
            observations_finalized=(
                current.observations_finalized + observations_finalized
            ),
            late_events=current.late_events + late_events,
        )
