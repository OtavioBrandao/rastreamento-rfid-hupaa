"""
Domain and service tests for logical portal topology and antenna mappings (ISS-013).

Validates:
- Bidirectional portals and A -> B / B -> A directional interpretation semantics.
- Rejection of invalid third zones and side/zone mismatches.
- Hardware and logical topology coherence.
- Support for multiple antennas on the same side.
- Uniqueness of active mappings per antenna (application and DB levels).
- Temporal replacement semantics (old.fim = T, new.inicio = T).
- Deactivation and exclusion from active topology.
- Guards blocking portal zone edits and antenna updates while active mappings exist.
"""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.service_hardware import (
    AntenaComMapeamentoAtivo,
    PortalComMapeamentosAtivos,
    atualizar_antena,
    atualizar_portal,
    criar_antena,
    criar_leitor,
    criar_portal,
    inativar_antena,
    inativar_portal,
)
from api.service_localizacao import (
    ZonaEmUso,
    criar_andar,
    criar_setor,
    criar_zona,
    inativar_zona,
)
from api.service_topologia_portal import (
    AntenaInativa,
    AntenaNaoEncontrada,
    AntenaNaoPertenceAoPortal,
    FuncaoInvalida,
    LadoInvalido,
    MapeamentoAtivoExistente,
    MapeamentoJaEncerrado,
    PortalInativo,
    PortalNaoEncontrado,
    ZonaIncompativelComAntena,
    ZonaIncompativelComLado,
    atualizar_mapeamento,
    buscar_mapeamento_por_id,
    criar_mapeamento,
    inativar_mapeamento,
    listar_historico_antena,
    listar_mapeamentos_portal,
    obter_topologia_portal,
)

_COUNTER = itertools.count(1)


def _serial() -> str:
    return str(next(_COUNTER))


def _cenario_base(db):
    """Sets up a complete physical hierarchy and reader for topology tests."""
    andar = criar_andar(db, f"Andar {_serial()}")
    setor = criar_setor(db, andar.id, f"Setor {_serial()}")
    zona_a = criar_zona(db, setor.id, f"Zona A {_serial()}")
    zona_b = criar_zona(db, setor.id, f"Zona B {_serial()}")
    zona_c = criar_zona(db, setor.id, f"Zona C {_serial()}")

    leitor = criar_leitor(
        db,
        reader_id=f"reader-{_serial()}",
        fabricante="Identix",
        modelo="EZ700",
        identificador_serial=f"ser-{_serial()}",
    )
    portal = criar_portal(db, f"Portal {_serial()}", zona_a.id, zona_b.id)
    return andar, setor, zona_a, zona_b, zona_c, leitor, portal


def test_criar_mapeamento_valido_bidirecional(db):
    """
    Validates bidirectional portal configuration:
    Antenna A -> Side A -> Zone A
    Antenna B -> Side B -> Zone B
    Topology query returns unambiguous A/B arrangement.
    """
    _, _, zona_a, zona_b, _, leitor, portal = _cenario_base(db)

    antena_a = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )
    antena_b = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=2,
        zona_associada_id=zona_b.id,
        funcao="saida",
        portal_id=portal.id,
    )

    map_a = criar_mapeamento(
        db,
        portal_id=portal.id,
        antena_id=antena_a.id,
        lado="a",
        funcao="entrada",
        zona_id=zona_a.id,
    )
    map_b = criar_mapeamento(
        db,
        portal_id=portal.id,
        antena_id=antena_b.id,
        lado="b",
        funcao="saida",
        zona_id=zona_b.id,
    )

    assert map_a.id is not None
    assert map_a.lado == "a"
    assert map_a.zona_id == zona_a.id
    assert map_a.funcao == "entrada"
    assert map_a.fim is None

    assert map_b.id is not None
    assert map_b.lado == "b"
    assert map_b.zona_id == zona_b.id
    assert map_b.funcao == "saida"
    assert map_b.fim is None

    topologia = obter_topologia_portal(db, portal.id)
    assert topologia.portal_id == portal.id
    assert topologia.zona_a_id == zona_a.id
    assert topologia.zona_b_id == zona_b.id
    assert len(topologia.antenas) == 2

    lado_a_item = next(it for it in topologia.antenas if it.lado == "a")
    lado_b_item = next(it for it in topologia.antenas if it.lado == "b")

    assert lado_a_item.antena_id == antena_a.id
    assert lado_a_item.reader_id == leitor.reader_id
    assert lado_a_item.porta_numero == 1
    assert lado_a_item.zona_id == zona_a.id

    assert lado_b_item.antena_id == antena_b.id
    assert lado_b_item.reader_id == leitor.reader_id
    assert lado_b_item.porta_numero == 2
    assert lado_b_item.zona_id == zona_b.id


def test_semantica_direcional_a_para_b_e_b_para_a(db):
    """
    Proves that the topology provides enough information to interpret directions:
    Side A -> Side B means Zone A -> Zone B
    Side B -> Side A means Zone B -> Zone A
    """
    _, _, zona_a, zona_b, _, leitor, portal = _cenario_base(db)

    antena_1 = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )
    antena_2 = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=2,
        zona_associada_id=zona_b.id,
        funcao="saida",
        portal_id=portal.id,
    )

    criar_mapeamento(db, portal.id, antena_1.id, lado="a", funcao="entrada")
    criar_mapeamento(db, portal.id, antena_2.id, lado="b", funcao="saida")

    topologia = obter_topologia_portal(db, portal.id)
    antenas_map = {item.antena_id: item for item in topologia.antenas}

    # Simulate sequence antenna 1 -> antenna 2
    origem_1 = antenas_map[antena_1.id]
    destino_1 = antenas_map[antena_2.id]
    assert origem_1.lado == "a" and destino_1.lado == "b"
    assert origem_1.zona_id == topologia.zona_a_id
    assert destino_1.zona_id == topologia.zona_b_id

    # Simulate sequence antenna 2 -> antenna 1
    origem_2 = antenas_map[antena_2.id]
    destino_2 = antenas_map[antena_1.id]
    assert origem_2.lado == "b" and destino_2.lado == "a"
    assert origem_2.zona_id == topologia.zona_b_id
    assert destino_2.zona_id == topologia.zona_a_id


def test_rejeitar_terceira_zona_invalida(db):
    """Mapping: Portal A=Zone 10, B=Zone 20. Side A -> Zone 30 must be rejected."""
    _, _, zona_a, _, zona_c, leitor, portal = _cenario_base(db)

    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    with pytest.raises(ZonaIncompativelComLado) as exc:
        criar_mapeamento(
            db, portal_id=portal.id, antena_id=antena.id, lado="a", funcao="entrada", zona_id=zona_c.id
        )
    assert f"Zona {zona_c.id} não pertence ao lado 'A'" in str(exc.value)


def test_rejeitar_mismatch_lado_e_zona(db):
    """Mapping side A -> zone B must be rejected."""
    _, _, zona_a, zona_b, _, leitor, portal = _cenario_base(db)

    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    with pytest.raises(ZonaIncompativelComLado):
        criar_mapeamento(
            db, portal_id=portal.id, antena_id=antena.id, lado="a", funcao="entrada", zona_id=zona_b.id
        )

    with pytest.raises(ZonaIncompativelComLado):
        criar_mapeamento(
            db, portal_id=portal.id, antena_id=antena.id, lado="b", funcao="saida", zona_id=zona_a.id
        )


def test_rejeitar_mismatch_zona_antena_hardware(db):
    """
    If antenna's hardware zona_associada_id points to Zone A,
    mapping it to Side B (Zone B) without matching zone must be rejected.
    """
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)

    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    with pytest.raises(ZonaIncompativelComAntena) as exc:
        # Omits explicit zona_id, but side B expects zona_b, while antenna has zona_a
        criar_mapeamento(db, portal_id=portal.id, antena_id=antena.id, lado="b", funcao="saida")
    assert f"A antena {antena.id} possui zona_associada_id={zona_a.id}" in str(exc.value)


def test_rejeitar_antena_sem_portal_ou_outro_portal(db):
    _, _, zona_a, zona_b, _, leitor, portal_1 = _cenario_base(db)
    portal_2 = criar_portal(db, f"Portal 2 {_serial()}", zona_a.id, zona_b.id)

    antena_sem_portal = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=None,
    )
    antena_portal_2 = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=2,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal_2.id,
    )

    with pytest.raises(AntenaNaoPertenceAoPortal) as exc1:
        criar_mapeamento(db, portal_1.id, antena_sem_portal.id, lado="a", funcao="entrada")
    assert "portal_id é null" in str(exc1.value)

    with pytest.raises(AntenaNaoPertenceAoPortal) as exc2:
        criar_mapeamento(db, portal_1.id, antena_portal_2.id, lado="a", funcao="entrada")
    assert f"está associada ao portal {portal_2.id}" in str(exc2.value)


def test_rejeitar_entidades_inativas_ou_inexistentes(db):
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)

    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    with pytest.raises(PortalNaoEncontrado):
        criar_mapeamento(db, 999_999, antena.id, lado="a", funcao="entrada")

    with pytest.raises(AntenaNaoEncontrada):
        criar_mapeamento(db, portal.id, 999_999, lado="a", funcao="entrada")

    inativar_portal(db, portal.id)
    with pytest.raises(PortalInativo):
        criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")

    portal.ativo = True
    db.commit()

    inativar_antena(db, antena.id)
    with pytest.raises(AntenaInativa):
        criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")


def test_rejeitar_lado_ou_funcao_invalidos(db):
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)
    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    with pytest.raises(LadoInvalido):
        criar_mapeamento(db, portal.id, antena.id, lado="c", funcao="entrada")

    with pytest.raises(FuncaoInvalida):
        criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="indefinido")

    with pytest.raises(FuncaoInvalida):
        criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="invalido")


def test_multiplas_antenas_por_lado(db):
    """
    Multiple antennas on the same portal side are explicitly allowed:
    Side A: Antenna 1, Antenna 2
    Side B: Antenna 3, Antenna 4
    """
    _, _, zona_a, zona_b, _, leitor, portal = _cenario_base(db)

    antenas_a = [
        criar_antena(
            db,
            leitor_id=leitor.id,
            porta_numero=i,
            zona_associada_id=zona_a.id,
            funcao="entrada",
            portal_id=portal.id,
        )
        for i in (1, 2)
    ]
    antenas_b = [
        criar_antena(
            db,
            leitor_id=leitor.id,
            porta_numero=i,
            zona_associada_id=zona_b.id,
            funcao="saida",
            portal_id=portal.id,
        )
        for i in (3, 4)
    ]

    for a in antenas_a:
        criar_mapeamento(db, portal.id, a.id, lado="a", funcao="entrada")

    for b in antenas_b:
        criar_mapeamento(db, portal.id, b.id, lado="b", funcao="saida")

    topologia = obter_topologia_portal(db, portal.id)
    assert len(topologia.antenas) == 4

    lados_a = [it for it in topologia.antenas if it.lado == "a"]
    lados_b = [it for it in topologia.antenas if it.lado == "b"]
    assert len(lados_a) == 2
    assert len(lados_b) == 2


def test_duplicidade_mapeamento_ativo_mesma_antena(db):
    """The same antenna cannot have two active mappings."""
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)
    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    m1 = criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")
    assert m1.fim is None

    # Application level guard rejects second active mapping
    with pytest.raises(MapeamentoAtivoExistente):
        criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="auxiliar")

    # DB partial unique index constraint verifies defense in depth
    with pytest.raises(IntegrityError):
        db.execute(
            text("""
                INSERT INTO mapeamentos_antena_portal (antena_id, portal_id, lado, zona_id, funcao, inicio, fim)
                VALUES (:antena_id, :portal_id, 'a', :zona_id, 'entrada', now(), NULL)
            """),
            {"antena_id": antena.id, "portal_id": portal.id, "zona_id": zona_a.id},
        )
        db.commit()
    db.rollback()


def test_historico_atualizacao_temporal(db):
    """
    Replacing an active mapping V1 creates V2:
    V1.fim is populated (not None)
    V2.fim is None
    Old row remains queryable in history.
    """
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)
    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    v1 = criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")
    v1_id = v1.id
    v1_inicio = v1.inicio
    assert v1.fim is None

    # Update operational function from 'entrada' to 'auxiliar'
    v2 = atualizar_mapeamento(db, v1_id, funcao="auxiliar")
    assert v2.id != v1_id
    assert v2.funcao == "auxiliar"
    assert v2.fim is None
    assert v2.inicio is not None

    # Check that V1 was closed and preserved
    db.expire_all()
    v1_db = buscar_mapeamento_por_id(db, v1_id)
    assert v1_db.fim is not None
    assert v1_db.funcao == "entrada"
    assert v1_db.inicio == v1_inicio

    # Cannot update an already closed mapping
    with pytest.raises(MapeamentoJaEncerrado):
        atualizar_mapeamento(db, v1_id, funcao="saida")

    # History queries return both
    historico = listar_historico_antena(db, antena.id)
    assert len(historico) == 2
    assert historico[0].id == v2.id
    assert historico[1].id == v1_id

    # Current portal mappings only returns V2
    mapeamentos_ativos = listar_mapeamentos_portal(db, portal.id, incluir_historico=False)
    assert len(mapeamentos_ativos) == 1
    assert mapeamentos_ativos[0].id == v2.id

    mapeamentos_todos = listar_mapeamentos_portal(db, portal.id, incluir_historico=True)
    assert len(mapeamentos_todos) == 2


def test_inativar_mapeamento_preserva_historico_e_remove_da_topologia_ativa(db):
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)
    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )

    map_obj = criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")
    assert map_obj.fim is None

    topologia_antes = obter_topologia_portal(db, portal.id)
    assert len(topologia_antes.antenas) == 1

    inativado = inativar_mapeamento(db, map_obj.id)
    assert inativado.fim is not None

    # Deactivating again is idempotent
    inativado_2 = inativar_mapeamento(db, map_obj.id)
    assert inativado_2.fim == inativado.fim

    # Mapping no longer appears in current active topology
    topologia_depois = obter_topologia_portal(db, portal.id)
    assert len(topologia_depois.antenas) == 0

    # But remains in database
    db_obj = buscar_mapeamento_por_id(db, map_obj.id)
    assert db_obj.fim is not None


def test_guard_atualizar_portal_bloqueado_com_mapeamentos_ativos(db):
    """Changing portal zones when active mappings exist must be blocked."""
    _, _, zona_a, zona_b, zona_c, leitor, portal = _cenario_base(db)
    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )
    map_obj = criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")

    # Attempt to change zona_a_id to zona_c
    with pytest.raises(PortalComMapeamentosAtivos) as exc:
        atualizar_portal(db, portal.id, {"zona_a_id": zona_c.id})
    assert f"Portal {portal.id} possui 1 mapeamento(s) lógico(s) ativo(s)" in str(exc.value)

    # Inactivate the mapping
    inativar_mapeamento(db, map_obj.id)

    # Now changing portal zones is allowed
    portal_atualizado = atualizar_portal(db, portal.id, {"zona_a_id": zona_c.id})
    assert portal_atualizado.zona_a_id == zona_c.id


def test_guard_atualizar_antena_bloqueado_com_mapeamento_ativo(db):
    """Changing antenna portal_id or zona_associada_id while mapped must be blocked."""
    _, _, zona_a, zona_b, zona_c, leitor, portal_1 = _cenario_base(db)
    portal_2 = criar_portal(db, f"Portal 2 {_serial()}", zona_a.id, zona_b.id)

    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal_1.id,
    )
    map_obj = criar_mapeamento(db, portal_1.id, antena.id, lado="a", funcao="entrada")

    # Changing portal_id to another portal is blocked
    with pytest.raises(AntenaComMapeamentoAtivo):
        atualizar_antena(db, antena.id, {"portal_id": portal_2.id})

    # Setting portal_id to None is blocked
    with pytest.raises(AntenaComMapeamentoAtivo):
        atualizar_antena(db, antena.id, {"portal_id": None})

    # Changing zona_associada_id is blocked
    with pytest.raises(AntenaComMapeamentoAtivo):
        atualizar_antena(db, antena.id, {"zona_associada_id": zona_c.id})

    # Inactivate the mapping
    inativar_mapeamento(db, map_obj.id)

    # Now changing portal_id and zona_associada_id is allowed
    atualizar_antena(db, antena.id, {"portal_id": portal_2.id, "zona_associada_id": zona_a.id})
    db.refresh(antena)
    assert antena.portal_id == portal_2.id


def test_inativar_zona_bloqueada_por_mapeamento_antena_portal(db):
    """A zone referenced in mapeamentos_antena_portal cannot be inactivated."""
    _, _, zona_a, _, _, leitor, portal = _cenario_base(db)
    antena = criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=1,
        zona_associada_id=zona_a.id,
        funcao="entrada",
        portal_id=portal.id,
    )
    criar_mapeamento(db, portal.id, antena.id, lado="a", funcao="entrada")

    with pytest.raises(ZonaEmUso) as exc:
        inativar_zona(db, zona_a.id)
    assert f"Zona {zona_a.id} não pode ser inativada" in str(exc.value)
    assert "mapeamentos_antena_portal" in str(exc.value)
