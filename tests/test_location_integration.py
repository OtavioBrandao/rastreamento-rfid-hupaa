"""ISS-017: atomicidade, recência, reconciliação e concorrência no PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from db.models import (
    Andar,
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    Passagem,
    Portal,
    Setor,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_location.service import LocationProjectionService

T = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)


@pytest.fixture
def setup(pg_engine):
    with pg_engine.begin() as c:
        floor = c.scalar(Andar.__table__.insert().values(
            nome="andar", nome_normalizado="andar").returning(Andar.id))
        sector = c.scalar(Setor.__table__.insert().values(
            andar_id=floor, nome="setor", nome_normalizado="setor").returning(Setor.id))
        zones = [c.scalar(Zona.__table__.insert().values(
            setor_id=sector, nome=f"zona {i}", nome_normalizado=f"zona {i}"
        ).returning(Zona.id)) for i in range(3)]
        portal = c.scalar(Portal.__table__.insert().values(
            nome="portal", zona_a_id=zones[0], zona_b_id=zones[1]
        ).returning(Portal.id))
        reader = c.scalar(Leitor.__table__.insert().values(
            reader_id="reader", identificador_serial="serial", fabricante="f", modelo="m"
        ).returning(Leitor.id))
        antennas = [c.scalar(Antena.__table__.insert().values(
            leitor_id=reader, porta_numero=i + 1, zona_associada_id=zones[i],
            funcao="indefinido",
        ).returning(Antena.id)) for i in range(2)]
        kind = c.scalar(TipoEquipamento.__table__.insert().values(
            nome="tipo", nome_normalizado="tipo").returning(TipoEquipamento.id))
        equipment = [c.scalar(Equipamento.__table__.insert().values(
            nome=f"eq {i}", tipo_id=kind, identificador_interno=f"EQ-{i}",
            identificador_interno_normalizado=f"eq-{i}",
        ).returning(Equipamento.id)) for i in range(2)]
        tag = c.scalar(Tag.__table__.insert().values(epc="EPC-X").returning(Tag.id))
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=tag, equipamento_id=equipment[0], inicio=T - timedelta(days=1),
            fim=T + timedelta(hours=1),
        ))
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=tag, equipamento_id=equipment[1], inicio=T + timedelta(hours=1),
        ))
    return {"zones": zones, "portal": portal, "antennas": antennas,
            "equipment": equipment, "tag": tag}


def passage(engine, setup, at, *, epc="EPC-X", origin=0, destination=1,
            status="confirmed"):
    with engine.begin() as c:
        readings = [c.scalar(LeituraBruta.__table__.insert().values(
            event_id=uuid4().hex,
            antena_id=setup["antennas"][side], epc=epc,
            lido_em=at - timedelta(seconds=1 - index),
        ).returning(LeituraBruta.id)) for index, side in enumerate((origin, destination))]
        values = dict(
            epc=epc, portal_id=setup["portal"],
            antena_origem_id=setup["antennas"][origin],
            antena_destino_id=setup["antennas"][destination],
            leitura_origem_id=readings[0], leitura_destino_id=readings[1],
            detectada_em=at, direcao="a_para_b" if origin == 0 else "b_para_a",
            direcao_status=status, direcao_regra="temporal_side_order_v1",
            zona_origem_id=setup["zones"][origin],
            zona_destino_id=setup["zones"][destination],
        )
        if status != "confirmed":
            values.update(direcao="indeterminada", direcao_regra="temporal_proximity_v1",
                          zona_origem_id=None, zona_destino_id=None)
        return c.scalar(Passagem.__table__.insert().values(**values).returning(Passagem.id))


def state(engine, equipment_id):
    with engine.connect() as c:
        return c.execute(select(
            Equipamento.ultima_zona_id, Equipamento.ultima_deteccao_em,
            Equipamento.ultima_passagem_id, Equipamento.ultima_movimentacao_id,
        ).where(Equipamento.id == equipment_id)).one()


def count(engine):
    with engine.connect() as c:
        return c.scalar(select(func.count()).select_from(HistoricoMovimentacao))


def test_projection_retry_recovery_and_existing_history(pg_engine, setup):
    first = passage(pg_engine, setup, T)
    service = LocationProjectionService(pg_engine)
    service.process_pending()
    result = service.process_passage(first)
    assert result.status == "duplicate"
    assert state(pg_engine, setup["equipment"][0]) == (
        setup["zones"][1], T, first, result.movement_id,
    )
    service.process_pending()
    assert count(pg_engine) == 1
    with pg_engine.begin() as c:
        c.execute(Equipamento.__table__.update().where(
            Equipamento.id == setup["equipment"][0]
        ).values(ultima_zona_id=None, ultima_deteccao_em=None,
                 ultima_passagem_id=None, ultima_movimentacao_id=None))
    service.process_pending()
    assert state(pg_engine, setup["equipment"][0]) == (
        setup["zones"][1], T, first, result.movement_id,
    )
    assert count(pg_engine) == 1


def test_out_of_order_equal_time_and_historical_owner(pg_engine, setup):
    service = LocationProjectionService(pg_engine)
    older = passage(pg_engine, setup, T)
    newer = passage(pg_engine, setup, T + timedelta(minutes=5), origin=1, destination=0)
    equal = passage(pg_engine, setup, T + timedelta(minutes=5))
    assert service.process_passage(newer).status == "updated"
    assert service.process_passage(older).status == "stale"
    assert service.process_passage(equal).status == "same_timestamp_conflict"
    assert state(pg_engine, setup["equipment"][0])[0:3] == (
        setup["zones"][0], T + timedelta(minutes=5), newer,
    )
    assert count(pg_engine) == 3
    after_transfer = passage(pg_engine, setup, T + timedelta(hours=2))
    assert service.process_passage(after_transfer).equipment_id == setup["equipment"][1]
    assert state(pg_engine, setup["equipment"][1])[2] == after_transfer


def test_invalid_unresolved_and_ambiguous_do_not_project(pg_engine, setup):
    service = LocationProjectionService(pg_engine)
    assert service.process_passage(999999).status == "passage_missing"
    ambiguous = passage(pg_engine, setup, T, status="ambiguous")
    assert service.process_passage(ambiguous).status == "invalid_passage"
    unknown_epc = passage(pg_engine, setup, T + timedelta(minutes=1), epc="NO-TAG")
    assert service.process_passage(unknown_epc).status == "unresolved_epc"
    assert state(pg_engine, setup["equipment"][0]) == (None, None, None, None)
    assert count(pg_engine) == 0
    with pg_engine.begin() as c:
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=setup["tag"], equipamento_id=setup["equipment"][1],
            inicio=T - timedelta(minutes=1), fim=T + timedelta(minutes=1),
        ))
    valid = passage(pg_engine, setup, T + timedelta(seconds=2))
    assert service.process_passage(valid).status == "ambiguous_association"
    assert count(pg_engine) == 0


def test_atomic_rollback_and_failed_update(pg_engine, setup, monkeypatch):
    first = passage(pg_engine, setup, T)
    service = LocationProjectionService(pg_engine)
    from rfid_location import repository
    original = repository.update_location

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("falha antes de commit")

    monkeypatch.setattr(repository, "update_location", broken)
    with pytest.raises(RuntimeError):
        service.process_passage(first)
    assert count(pg_engine) == 0
    assert state(pg_engine, setup["equipment"][0]) == (None, None, None, None)
    monkeypatch.setattr(repository, "update_location", original)
    assert service.process_passage(first).status == "updated"


def test_manual_correction_atomic_and_temporal(pg_engine, setup):
    service = LocationProjectionService(pg_engine)
    first = passage(pg_engine, setup, T)
    automatic = service.process_passage(first)
    correction = service.apply_manual_location_correction(
        equipment_id=setup["equipment"][0], destination_zone_id=setup["zones"][2],
        movimentada_em=T + timedelta(minutes=10), justificativa="confirmado fisicamente",
    )
    assert state(pg_engine, setup["equipment"][0]) == (
        setup["zones"][2], T + timedelta(minutes=10), None, correction.movement_id,
    )
    with pg_engine.connect() as c:
        row = c.execute(select(HistoricoMovimentacao.__table__).where(
            HistoricoMovimentacao.id == correction.movement_id
        )).mappings().one()
        assert (row["origem_registro"], row["zona_origem_id"], row["registro_anterior_id"]) == (
            "correcao_manual", setup["zones"][1], automatic.movement_id,
        )
        assert row["justificativa"] == "confirmado fisicamente"
    with pytest.raises(ValueError):
        service.apply_manual_location_correction(
            equipment_id=setup["equipment"][0], destination_zone_id=setup["zones"][0],
            movimentada_em=T, justificativa="antiga",
        )
    assert count(pg_engine) == 2


def test_manual_correction_rolls_back_with_projection(pg_engine, setup, monkeypatch):
    service = LocationProjectionService(pg_engine)
    first = passage(pg_engine, setup, T)
    automatic = service.process_passage(first)
    before = state(pg_engine, setup["equipment"][0])
    from rfid_location import repository

    def broken(*args, **kwargs):
        raise RuntimeError("falha no update")

    monkeypatch.setattr(repository, "update_location", broken)
    with pytest.raises(RuntimeError):
        service.apply_manual_location_correction(
            equipment_id=setup["equipment"][0],
            destination_zone_id=setup["zones"][2],
            movimentada_em=T + timedelta(minutes=10), justificativa="verificado",
        )
    assert state(pg_engine, setup["equipment"][0]) == before
    assert count(pg_engine) == 1
    assert before[3] == automatic.movement_id


@pytest.mark.parametrize("delayed_passage", ["earlier", "later"])
def test_concurrent_workers_keep_latest(pg_engine, setup, delayed_passage):
    earlier = passage(pg_engine, setup, T)
    later = passage(pg_engine, setup, T + timedelta(minutes=5), origin=1, destination=0)
    barrier = Barrier(2)
    service = LocationProjectionService(pg_engine)

    def worker(passage_id):
        barrier.wait()
        if passage_id == (earlier if delayed_passage == "earlier" else later):
            import time
            time.sleep(0.05)
        return service.process_passage(passage_id).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (earlier, later)))
    assert set(results) <= {"updated", "stale"}
    assert state(pg_engine, setup["equipment"][0])[0:3] == (
        setup["zones"][0], T + timedelta(minutes=5), later,
    )
    assert count(pg_engine) == 2


def test_pending_skips_epc_without_association_until_one_covers_it(pg_engine, setup):
    """Sessão de 25/10/2026: passagens de tags não cadastradas voltavam a cada ciclo
    (~1 s cada no Neon) e atrasavam toda a inferência. Só voltam quando resolvíveis."""
    from rfid_location import repository

    sem_tag = passage(pg_engine, setup, T + timedelta(minutes=5), epc="NO-TAG")
    assert sem_tag not in repository.pending_ids(pg_engine)
    with pg_engine.begin() as c:
        tag = c.scalar(Tag.__table__.insert().values(epc="NO-TAG").returning(Tag.id))
        # Associação só depois da passagem: continua sem resolver (regra de rfid_movement).
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=tag, equipamento_id=setup["equipment"][1], inicio=T + timedelta(minutes=6),
            fim=T + timedelta(days=1)))
    assert sem_tag not in repository.pending_ids(pg_engine)
    with pg_engine.begin() as c:
        c.execute(AssociacaoTagEquipamento.__table__.update()
                  .where(AssociacaoTagEquipamento.tag_id == tag)
                  .values(inicio=T + timedelta(minutes=4)))
    assert sem_tag in repository.pending_ids(pg_engine)
    assert LocationProjectionService(pg_engine).process_passage(sem_tag).equipment_id == setup["equipment"][1]
