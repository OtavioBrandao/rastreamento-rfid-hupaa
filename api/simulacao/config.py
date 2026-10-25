"""Configuração do simulador web por variáveis de ambiente (lidas só no servidor).

- `SIMULADOR_HABILITADO=true` liga o simulador; o padrão é desligado.
- Em `APP_ENV=production` o simulador nunca liga: pedir isso impede a subida.
- Broker: `SIMULADOR_MQTT_*` quando presentes; no modo local, sem elas, usa o
  mesmo Mosquitto do ingestor (`MQTT_*`). No broker externo, a credencial de
  PUBLICAÇÃO precisa ser própria (nunca a de assinatura do ingestor).
- `SIMULADOR_MQTT_TOPICO_PERMITIDO`: filtro da ACL do publicador (opcional),
  conferido antes de publicar para falhar com mensagem clara.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from api.ambiente import ambiente_atual

from .publicador import ASSINATURA_PADRAO

CHAVES_MQTT = ("MQTT_MODE", "MQTT_HOST", "MQTT_PORT", "MQTT_TLS_ENABLED", "MQTT_INSECURE_LAB",
               "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CA_CERT", "MQTT_KEEPALIVE")


@dataclass(frozen=True)
class ConfigSimulador:
    """Valores resolvidos; `motivo` explica por que está desabilitado."""

    habilitado: bool
    ambiente: str
    motivo: str | None = None
    mqtt: dict[str, str] = field(default_factory=dict, repr=False)
    assinatura: str = ASSINATURA_PADRAO
    topico_permitido: str | None = None
    # Broker com ACL de um tópico só (perfil de um leitor): todos os leitores virtuais
    # publicam nele e se identificam por `sim_reader_id` (ver rfid_ingestion.normalization).
    topico_relay: str | None = None
    tick_s: float = 0.1
    periodo_leitura_s: float = 0.2

    def publico(self) -> dict:
        """Forma segura para a interface: sem host, usuário nem senha."""
        return {"habilitado": self.habilitado, "ambiente": self.ambiente, "motivo": self.motivo,
                "periodo_leitura_ms": round(self.periodo_leitura_s * 1000)}


def _bool(source: Mapping[str, str], nome: str) -> bool:
    """Interpreta true/false; outro valor é erro de configuração."""
    valor = (source.get(nome) or "false").strip().lower()
    if valor not in ("true", "false"):
        raise ValueError(f"{nome} deve ser true ou false")
    return valor == "true"


def carregar(environ: Mapping[str, str] | None = None) -> ConfigSimulador:
    """Resolve a configuração; recusa ligar o simulador em produção."""
    source = os.environ if environ is None else environ
    ambiente = ambiente_atual(source)
    pedido = _bool(source, "SIMULADOR_HABILITADO")
    if ambiente == "production":
        if pedido:
            raise ValueError("SIMULADOR_HABILITADO=true não é permitido com APP_ENV=production")
        return ConfigSimulador(False, ambiente, "bloqueado em produção")
    if not pedido:
        return ConfigSimulador(False, ambiente, "SIMULADOR_HABILITADO não está ativo neste servidor")
    mqtt = {chave: source[chave] for chave in CHAVES_MQTT if source.get(chave) is not None}
    mqtt.update({chave.removeprefix("SIMULADOR_"): valor for chave, valor in source.items()
                 if chave.startswith("SIMULADOR_MQTT_") and chave != "SIMULADOR_MQTT_TOPICO_PERMITIDO"
                 and valor is not None})
    modo = mqtt.get("MQTT_MODE", "local")
    if modo != "local" and not source.get("SIMULADOR_MQTT_USERNAME") \
            and mqtt.get("MQTT_INSECURE_LAB") != "true":
        return ConfigSimulador(False, ambiente, "broker externo exige credencial de publicação "
                               "própria (SIMULADOR_MQTT_USERNAME/SIMULADOR_MQTT_PASSWORD)")
    if modo != "local" and source.get("SIMULADOR_MQTT_USERNAME") == source.get("MQTT_USERNAME"):
        return ConfigSimulador(False, ambiente, "use uma credencial MQTT de publicação separada "
                               "da assinatura do ingestor")
    periodo = float(source.get("SIMULADOR_PERIODO_LEITURA_MS") or 200) / 1000
    tick = float(source.get("SIMULADOR_TICK_MS") or 100) / 1000
    if not 0.05 <= periodo <= 5 or not 0.02 <= tick <= 1:
        raise ValueError("SIMULADOR_PERIODO_LEITURA_MS (50–5000) ou SIMULADOR_TICK_MS (20–1000) "
                         "fora do intervalo")
    return ConfigSimulador(
        True, ambiente, None, mqtt,
        assinatura=source.get("SIMULADOR_TOPICO_INGESTOR") or source.get("MQTT_TOPIC")
        or ASSINATURA_PADRAO,
        topico_permitido=source.get("SIMULADOR_MQTT_TOPICO_PERMITIDO") or None,
        topico_relay=source.get("SIMULADOR_MQTT_TOPICO_RELAY") or None,
        tick_s=tick, periodo_leitura_s=periodo)
