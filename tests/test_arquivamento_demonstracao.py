"""Ocultar cadastros inativos não apaga EPCs, leituras ou acesso ao inventário completo."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from db.models import Antena, Equipamento, LeituraBruta, Tag
from tools.lab_launcher.seed import semear, semear_equipamentos


def test_inventory_summary_readings_keep_archived_records(engine, truncate_all):
    now = datetime.now(timezone.utc)
    epcs = [f'E2804C41000000000000000{n}' for n in (1, 2, 3)]
    unknown = 'E2804C410000000000000099'
    with Session(engine) as db:
        semear(db)
        semear_equipamentos(db, list(zip(epcs, ['Bomba 01', 'Ensaio 01', 'Ensaio 02'])))
        items = db.scalars(select(Equipamento).order_by(Equipamento.id)).all()
        for item in items[1:]:
            item.status = 'inativo'
        antenna = db.scalar(select(Antena).order_by(Antena.id))
        for epc in [epcs[0], epcs[1], unknown]:
            db.add(LeituraBruta(event_id=str(uuid4()), antena_id=antenna.id,
                               epc=epc, rssi=-5000, lido_em=now, recebido_em=now, dados_origem={}))
        db.commit()
    def dependency():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    try:
        with TestClient(app) as client:
            all_items = client.get('/api/ativos').json()
            active = client.get('/api/ativos?somente_ativos=true&page_size=1').json()
            assert all_items['total'] == 3
            assert active['total'] == 1
            assert active['items'][0]['nome'] == 'Bomba 01'
            assert client.get('/api/dashboard/resumo').json()['registered'] == 3
            assert client.get('/api/dashboard/resumo?somente_ativos=true').json()['registered'] == 1
            summary = client.get('/api/leituras/resumo?somente_ativos=true').json()
            assert summary['total_leituras'] == 2
            assert summary['cadastradas_detectadas'] == 1
            assert summary['cadastradas_sem_leitura'] == 0
            assert summary['nao_cadastradas'] == 1
            assert {item['epc'] for item in summary['items']} == {epcs[0], unknown}
            assert client.get('/api/leituras/resumo').json()['cadastradas_sem_leitura'] == 1
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Equipamento)) == 3
            assert db.scalar(select(func.count()).select_from(Tag)) == 3
            assert db.scalar(select(func.count()).select_from(LeituraBruta)) == 3
    finally:
        app.dependency_overrides.pop(get_db, None)
