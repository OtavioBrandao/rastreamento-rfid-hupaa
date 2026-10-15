"""Contrato de tópicos independente do fabricante e do broker."""

import re


def validate_topic(topic: str, *, subscription: bool = False) -> str:
    """Valida a estrutura easy/ambiente/site/portal/leitor/readings do tópico."""
    parts = topic.split("/")
    if len(parts) != 6 or parts[0] != "easy" or parts[-1] != "readings":
        raise ValueError("MQTT_TOPIC deve seguir easy/ambiente/site/portal/leitor/readings")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", part)
           and not (subscription and part == "+") for part in parts[1:5]):
        raise ValueError("Identificador de tópico inválido")
    return topic


def reading_topic(reader_id: str, environment: str = "dev", site: str = "hupaa",
                  portal: str = "portal-01") -> str:
    """Monta o tópico exato de publicação a partir dos identificadores do cenário."""
    return validate_topic(f"easy/{environment}/{site}/{portal}/{reader_id}/readings")
