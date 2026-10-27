"""Item que surge no centro do HU chegou de outro andar pelo elevador.

O simulador modela o mundo: um equipamento acrescentado sem posição surge junto ao
elevador central, então veio de outro andar. Quando esse equipamento está (ou passa
a estar) cadastrado e ainda não tem nenhuma localização no histórico, registra-se
"Outro andar (elevador)" no instante em que ele surgiu — uma correção justificada,
como qualquer registro manual. A partir daí só passagens confirmadas o movem.

Nada disso vale para o EASY nem para itens com posição escolhida, e nada é feito se
o equipamento já tem histórico (não se reescreve o passado).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.epc import EpcInvalido, normalizar_epc
from db.models import AssociacaoTagEquipamento, Equipamento, SimulacaoSessao, Tag
from rfid_location.service import corrigir_localizacao

JUSTIFICATIVA = "Chegou de outro andar pelo elevador central (simulador do HU)"


def registrar_chegada(db: Session, epc: str) -> bool:
    """Registra a chegada por outro andar do equipamento desta tag, se couber."""
    from .cenario_demo import _zona_outro_andar

    try:
        epc = normalizar_epc(epc)
    except EpcInvalido:
        return False
    sessoes = db.scalars(select(SimulacaoSessao).where(
        SimulacaoSessao.cenario == "hupaa", SimulacaoSessao.estado != "encerrada")
        .order_by(SimulacaoSessao.id.desc())).all()
    item, sessao = next(((i, s) for s in sessoes for i in s.itens
                         if i.get("epc") == epc and i.get("origem") == "outro_andar"), (None, None))
    if item is None:
        return False
    equipamento = db.scalar(select(Equipamento).join(
        AssociacaoTagEquipamento, AssociacaoTagEquipamento.equipamento_id == Equipamento.id).join(
        Tag, Tag.id == AssociacaoTagEquipamento.tag_id).where(
        Tag.epc == epc, AssociacaoTagEquipamento.fim.is_(None)))
    if equipamento is None or equipamento.ultima_deteccao_em is not None:
        return False
    zona_hu = next(iter((sessao.topologia or {}).get("zonas", {}).values()), None)
    if zona_hu is None:
        return False
    corrigir_localizacao(db.connection(), equipment_id=equipamento.id,
                         destination_zone_id=_zona_outro_andar(db, zona_hu),
                         movimentada_em=datetime.fromisoformat(item["chegou_em"]),
                         justificativa=JUSTIFICATIVA)
    db.commit()
    return True
