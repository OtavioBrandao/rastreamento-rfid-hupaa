"""Contrato de leitura incremental para o mapa EASY, sem banco gerenciado."""

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.database import get_db
from api.main import app


def test_leituras_recentes_cursor_e_validacao():
    consultas = []
    agora = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)

    class Banco:
        def execute(self, stmt):
            consultas.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            return SimpleNamespace(all=lambda: [
                SimpleNamespace(id=4, epc="E2804C414200000000000002",
                                porta_numero=1, recebido_em=agora),
                SimpleNamespace(id=3, epc="E2804C414200000000000003",
                                porta_numero=2, recebido_em=agora),
            ] if len(consultas) == 1 else [
                SimpleNamespace(id=5, epc="E2804C414200000000000002",
                                porta_numero=2, recebido_em=agora),
            ])

    app.dependency_overrides[get_db] = lambda: Banco()
    try:
        client = TestClient(app)
        first = client.get("/api/laboratorio/leituras").json()
        assert [item["id"] for item in first["items"]] == [3, 4]
        assert first["next_id"] == 4
        second = client.get("/api/laboratorio/leituras?after_id=4&epc=E2804C414200000000000002").json()
        assert second["next_id"] == 5
        assert "portais.nome = 'Portal de teste RFID'" in consultas[0]
        assert "leituras_brutas.id > 4" in consultas[1]
        assert "leituras_brutas.epc = 'E2804C414200000000000002'" in consultas[1]
        for query in ("after_id=-1", "limit=101", "epc=ZZZZ"):
            assert client.get(f"/api/laboratorio/leituras?{query}").status_code == 422
    finally:
        app.dependency_overrides.clear()
