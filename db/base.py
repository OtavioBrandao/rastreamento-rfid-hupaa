"""
Base declarativa compartilhada por todos os models.
Importar `Base` aqui garante que o Alembic (env.py) enxergue
o metadata completo para autogenerate/comparação futura.
"""
from sqlalchemy.orm import declarative_base

Base = declarative_base()
