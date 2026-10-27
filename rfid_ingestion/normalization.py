"""Adapters explícitos e contrato canônico v1, sem dependência do transporte."""

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone

from .topics import validate_topic


def utc_timestamp(value, *, epoch_ms=False):
    """Valida RFC3339 com fuso (ou epoch_ms explícito) e devolve texto UTC com microssegundos."""
    if not isinstance(value, str):
        raise ValueError("timestamp deve ser texto")
    if epoch_ms:
        if not re.fullmatch(r"[0-9]{13}", value):
            raise ValueError("timestamp deve conter 13 dígitos de epoch_ms configurado")
        instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(value))
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
            raise ValueError("timestamp exige RFC3339 com fuso explícito e até 6 casas decimais")
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("timestamp inválido") from None
    try:
        return instant.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        raise ValueError("timestamp fora do intervalo suportado") from None


def finite_number(value):
    """Informa se o valor é int/float finito, excluindo booleanos e overflow."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def ez700(payload, settings):
    """Unidade RSSI não comprovada: não transformar -3880 em dBm."""
    return (payload.get("epc"), payload.get("antenna"), payload.get("rssi"),
            payload.get("timestamp"), "unknown", False,
            {k: v for k, v in payload.items() if k not in {"epc", "antenna", "rssi", "timestamp", "readerid", "reader_id"}})


def simulator(payload, settings):
    """Extrai tag, porta, sinal com unidade e observed_at do contrato do adapter simulator."""
    signal = payload.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("signal deve ser objeto com value e unit")
    extras = {k: v for k, v in payload.items() if k not in {"tag", "port", "signal", "observed_at", "reader_id", "readerid"}}
    extras["signal"] = signal
    return (payload.get("tag"), payload.get("port"), signal.get("value"),
            payload.get("observed_at"), signal.get("unit"), False, extras)


# Mesmo formato de api/simulacao/esquema.py: leitores virtuais nunca colidem com físicos.
READER_ID_VIRTUAL = re.compile(r"sim-[a-z0-9][a-z0-9-]{0,40}")

# Novo adapter: função com o mesmo contrato e registro aqui; consumidor não muda.
ADAPTERS = {"ez700": ez700, "simulator": simulator}


def normalize(payload, topic, raw, settings, *, received_at_utc=None):
    """Normaliza o payload pelo adapter do leitor e devolve evento, erros, leitor e adapter.

    O hash inclui tópico, adapter, formato temporal e bytes originais. Contadores
    EZ700 usam received_at_utc; a unidade de RSSI desconhecida permanece em metadata.
    Erros de entrada viram uma lista de motivos, sem interromper o receptor."""
    reader_id = None
    adapter = settings.normalization_adapter
    try:
        validate_topic(topic)
        reader_id = topic.split("/")[4]
        relay = None
        if isinstance(payload, dict) and "sim_reader_id" in payload:
            # Simulador web no broker externo: a ACL só libera o tópico do leitor de
            # laboratório, então os leitores virtuais publicam por ele e se identificam
            # aqui. Só vale num tópico habilitado como relay e só para ids `sim-*`.
            if reader_id not in getattr(settings, "relay_virtual_readers", ()):
                raise ValueError("sim_reader_id recusado: este tópico não é relay de leitores virtuais")
            virtual = payload["sim_reader_id"]
            if not isinstance(virtual, str) or not READER_ID_VIRTUAL.fullmatch(virtual):
                raise ValueError("sim_reader_id deve ser um leitor virtual (sim-...)")
            relay, reader_id = reader_id, virtual
        adapter = settings.reader_adapters.get(reader_id, adapter)
        if adapter not in ADAPTERS:
            raise ValueError("adapter desconhecido")
        if not isinstance(payload, dict):
            raise ValueError("payload deve ser objeto JSON")
        for key in ("reader_id", "readerid"):
            if key in payload and payload[key] != reader_id:
                raise ValueError("reader_id do payload diverge do tópico")
        epc, antenna, rssi, timestamp, unit, epoch_ms, extras = ADAPTERS[adapter](payload, settings)
        if not isinstance(epc, str) or not epc.strip():
            raise ValueError("epc deve ser texto não vazio")
        if type(antenna) is not int or antenna < 1:
            raise ValueError("antenna deve ser inteiro positivo")
        if not finite_number(rssi):
            raise ValueError("rssi deve ser numérico finito")
        if unit not in ("dBm", "unknown"):
            raise ValueError("unidade de rssi desconhecida; use dBm ou unknown")
        if unit == "dBm" and rssi > 0:
            raise ValueError("rssi em dBm deve ser menor ou igual a zero")
        timestamp_format = "epoch_ms" if epoch_ms else "rfc3339"
        if adapter == "ez700" and (
            (type(timestamp) is int and timestamp >= 0)
            or (isinstance(timestamp, str) and re.fullmatch(r"[0-9]+", timestamp))
        ):
            # O contador físico não representa uma data, nem mesmo com 13 dígitos.
            timestamp = (
                received_at_utc if received_at_utc is not None
                else datetime.now(timezone.utc).isoformat()
            )
            timestamp_format = "received_at_utc"
        if "sim_lido_em" in payload:
            # Simulador web com o tempo acelerado/adiantado: o instante vem do relógio
            # da simulação. Só de leitores virtuais, fora de produção e nunca antes
            # do recebimento (não serve para reescrever o passado).
            if not READER_ID_VIRTUAL.fullmatch(reader_id):
                raise ValueError("sim_lido_em só vale para leitores virtuais (sim-...)")
            if getattr(settings, "app_env", "development") == "production":
                raise ValueError("sim_lido_em recusado em produção")
            simulado = utc_timestamp(payload["sim_lido_em"])
            recebido = received_at_utc or datetime.now(timezone.utc).isoformat()
            if (datetime.fromisoformat(simulado.replace("Z", "+00:00"))
                    < datetime.fromisoformat(recebido.replace("Z", "+00:00")) - timedelta(seconds=120)):
                raise ValueError("sim_lido_em anterior ao recebimento")
            timestamp, epoch_ms, timestamp_format = simulado, False, "sim_clock"
        timestamp = utc_timestamp(timestamp, epoch_ms=epoch_ms)
        identity = b"rfid-v1\0" + topic.encode() + b"\0" + adapter.encode() + b"\0" + timestamp_format.encode() + b"\0" + raw
        event = dict(event_id="sha256:" + hashlib.sha256(identity).hexdigest(),
                     epc=epc, antenna=antenna, rssi=rssi if unit == "dBm" else None,
                     reader_id=reader_id, timestamp=timestamp,
                     metadata=dict(adapter=adapter, source_fields=extras,
                                   rssi_original=rssi, rssi_unit=unit,
                                   timestamp_original=payload.get("timestamp", payload.get("observed_at")),
                                   timestamp_format=timestamp_format))
        if relay is not None:
            event["metadata"]["relay_reader_id"] = relay
        return event, [], reader_id, adapter
    except ValueError as error:
        return None, [str(error)], reader_id, adapter
    except Exception:
        # Falhas de extensões também não interrompem a coleta; não expor payload/exceção.
        return None, ["falha interna do adapter"], reader_id, adapter
