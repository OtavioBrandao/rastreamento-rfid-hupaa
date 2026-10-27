"""Quais equipamentos o painel mostra quando esconde os cadastros encerrados.

"Fora de serviço" e "baixa lógica" usam o mesmo status (`inativo`), mas não são a
mesma coisa:

- **fora de serviço**: o equipamento existe e continua com a etiqueta vinculada
  (ex.: maca quebrada). Deve continuar aparecendo, em vermelho, no inventário, no
  mapa e nas abas por zona — e as transições dele continuam sendo detectadas;
- **arquivado** (baixa lógica, ex.: reinício da demonstração, ensaios antigos):
  inativo e sem etiqueta vinculada. Só aparece pedindo "mostrar inativos".
"""

from sqlalchemy import exists, or_
from sqlalchemy.orm import aliased

from db.models import AssociacaoTagEquipamento, Equipamento


def nao_arquivado():
    """Predicado SQL: ativo, ou inativo que ainda tem etiqueta (fora de serviço)."""
    # Alias próprio: consultas que já juntam as associações não "engolem" o EXISTS.
    vinculo = aliased(AssociacaoTagEquipamento)
    return or_(Equipamento.status == "ativo", exists().where(
        vinculo.equipamento_id == Equipamento.id, vinculo.fim.is_(None)))
