"""Regras sem banco: só passagens confirmadas produzem evento."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from rfid_movement.service import append_automatic_movement, append_manual_correction

T = datetime(2026, 1, 15, tzinfo=timezone.utc)


def passage(**changes):
    result = {
        "id": 1, "epc": "EPC-X", "portal_id": 2,
        "direcao_status": "confirmed", "direcao": "a_para_b",
        "zona_origem_id": 3, "zona_destino_id": 4,
        "leitura_origem_id": 5, "leitura_destino_id": 6,
        "detectada_em": T,
    }
    result.update(changes)
    return result


def test_confirmed_builds_event_from_persisted_passage():
    with patch("rfid_movement.service.repository") as repo:
        repo.load_passage.return_value = passage()
        repo.get_automatic_for_passage.return_value = None
        repo.resolve_equipment.return_value = (42,)
        repo.append.return_value = (8, True)
        result = append_automatic_movement(Mock(), 1)
        assert result.status == "recorded"
        assert result.equipamento_id == 42
        event = repo.append.call_args.args[1]
        assert event.movimentada_em == T
        assert event.passagem_id == 1
        assert (event.epc, event.portal_id, event.leitura_origem_id,
                event.leitura_destino_id) == ("EPC-X", 2, 5, 6)
        repo.resolve_equipment.assert_called_once_with(repo.append.call_args.args[0], "EPC-X", T)


@pytest.mark.parametrize("changes", [
    {"direcao_status": "ambiguous", "direcao": "indeterminada"},
    {"direcao_status": "unknown", "direcao": "indeterminada"},
    {"direcao_status": None, "direcao": None},
    {"zona_origem_id": 4},
    {"leitura_destino_id": None},
    {"direcao": "indeterminada"},
])
def test_invalid_passage_never_resolves_or_inserts(changes):
    with patch("rfid_movement.service.repository") as repo:
        repo.load_passage.return_value = passage(**changes)
        assert append_automatic_movement(Mock(), 1).status == "invalid_passage"
        repo.resolve_equipment.assert_not_called()
        repo.append.assert_not_called()


@pytest.mark.parametrize("owners,status", [
    ((), "unresolved_epc"), ((1, 2), "ambiguous_association"),
])
def test_unresolved_or_ambiguous_epc_does_not_insert(owners, status):
    with patch("rfid_movement.service.repository") as repo:
        repo.load_passage.return_value = passage()
        repo.get_automatic_for_passage.return_value = None
        repo.resolve_equipment.return_value = owners
        assert append_automatic_movement(Mock(), 1).status == status
        repo.append.assert_not_called()


def test_retry_reports_duplicate():
    with patch("rfid_movement.service.repository") as repo:
        repo.load_passage.return_value = passage()
        repo.get_automatic_for_passage.return_value = None
        repo.resolve_equipment.return_value = (42,)
        repo.append.return_value = (8, False)
        assert append_automatic_movement(Mock(), 1).status == "duplicate"


def test_manual_requires_justification():
    with pytest.raises(ValueError, match="justificativa"):
        append_manual_correction(Mock(), equipamento_id=1, zona_destino_id=2,
                                 movimentada_em=T, justificativa="  ")
