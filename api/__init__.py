"""API HTTP do MVP de rastreamento RFID (EASY/HUPAA)."""

# ISS-028: ativa o registro central da trilha (listeners de Session) em
# qualquer uso do pacote `api`, inclusive scripts como `api.criar_admin`.
from api import auditoria as auditoria  # noqa: E402,F401
