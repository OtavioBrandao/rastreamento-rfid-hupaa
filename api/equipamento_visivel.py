"""Quais equipamentos o painel mostra quando esconde os cadastros encerrados.

- **fora de serviço** (`status = 'fora_de_servico'`, migration s042): o equipamento
  existe, mas não deve ser usado (ex.: maca quebrada). Continua no inventário, no
  mapa e nas abas por zona, em vermelho, e as transições dele seguem detectadas;
- **inativo** (baixa lógica: ensaio arquivado, reinício da demonstração): some no
  modo "somente ativos" e só aparece pedindo "mostrar inativos".
"""

from db.models import Equipamento

STATUS_FORA_DE_SERVICO = "fora_de_servico"


def nao_arquivado():
    """Predicado SQL: em serviço ou fora de serviço (tudo menos a baixa lógica)."""
    return Equipamento.status != "inativo"
