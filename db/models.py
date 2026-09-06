"""
Models SQLAlchemy do MVP de rastreamento RFID (EASY/HUPAA).

Espelha 1:1 o documento "Modelagem_Dados_MVP_RFID.md" e o diagrama
"ER_Diagrama_MVP_RFID.mermaid". Qualquer mudança aqui deve ser refletida
nos dois artefatos (e vice-versa), para não divergirem.

Convenções:
- Tabelas em português, plural, snake_case.
- PK interna: BigInteger autoincremento (identity).
- Timestamps: sempre TIMESTAMP(timezone=True); a aplicação grava em UTC.
"""
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from db.base import Base


class TipoEquipamento(Base):
    __tablename__ = "tipos_equipamento"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False, unique=True)
    descricao = Column(Text, nullable=True)

    equipamentos = relationship("Equipamento", back_populates="tipo")


class Equipamento(Base):
    __tablename__ = "equipamentos"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False)
    tipo_id = Column(BigInteger, ForeignKey("tipos_equipamento.id"), nullable=False)
    identificador_interno = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, server_default="ativo")

    # RF-012: última localização conhecida vive como colunas no próprio
    # equipamento (relação 1:1) em vez de tabela separada.
    ultima_zona_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=True)
    ultima_deteccao_em = Column(TIMESTAMP(timezone=True), nullable=True)
    ultima_passagem_id = Column(BigInteger, ForeignKey("passagens.id"), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    tipo = relationship("TipoEquipamento", back_populates="equipamentos")
    ultima_zona = relationship("Zona", foreign_keys=[ultima_zona_id])
    ultima_passagem = relationship("Passagem", foreign_keys=[ultima_passagem_id])
    associacoes_tag = relationship("AssociacaoTagEquipamento", back_populates="equipamento")
    historico = relationship("HistoricoMovimentacao", back_populates="equipamento")

    __table_args__ = (
        Index("ix_equipamentos_ultima_zona_id", "ultima_zona_id"),
        Index("ix_equipamentos_status", "status"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id = Column(BigInteger, primary_key=True)
    epc = Column(String, nullable=False, unique=True)
    criada_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    associacoes = relationship("AssociacaoTagEquipamento", back_populates="tag")


class AssociacaoTagEquipamento(Base):
    """
    Histórico de vínculo tag <-> equipamento (RF-003).
    `fim IS NULL` = associação ativa. As duas constraints de índice único
    parcial abaixo garantem, a nível de banco, que existe no máximo UMA
    associação ativa por tag e por equipamento (critério de aceitação).
    """

    __tablename__ = "associacoes_tag_equipamento"

    id = Column(BigInteger, primary_key=True)
    tag_id = Column(BigInteger, ForeignKey("tags.id"), nullable=False)
    equipamento_id = Column(BigInteger, ForeignKey("equipamentos.id"), nullable=False)
    inicio = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    fim = Column(TIMESTAMP(timezone=True), nullable=True)

    tag = relationship("Tag", back_populates="associacoes")
    equipamento = relationship("Equipamento", back_populates="associacoes_tag")

    __table_args__ = (
        Index(
            "uq_tag_ativa",
            "tag_id",
            unique=True,
            postgresql_where=(fim.is_(None)),
        ),
        Index(
            "uq_equipamento_tag_ativa",
            "equipamento_id",
            unique=True,
            postgresql_where=(fim.is_(None)),
        ),
    )


class Andar(Base):
    __tablename__ = "andares"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False, unique=True)

    setores = relationship("Setor", back_populates="andar")


class Setor(Base):
    __tablename__ = "setores"

    id = Column(BigInteger, primary_key=True)
    andar_id = Column(BigInteger, ForeignKey("andares.id"), nullable=False)
    nome = Column(String, nullable=False)

    andar = relationship("Andar", back_populates="setores")
    zonas = relationship("Zona", back_populates="setor")

    __table_args__ = (UniqueConstraint("andar_id", "nome", name="uq_setor_nome_por_andar"),)


class Zona(Base):
    __tablename__ = "zonas"

    id = Column(BigInteger, primary_key=True)
    setor_id = Column(BigInteger, ForeignKey("setores.id"), nullable=False)
    nome = Column(String, nullable=False)
    # Zona morta não é entidade própria: é só uma observação textual
    # sobre uma zona já existente (ver "Termos e definições").
    observacoes = Column(Text, nullable=True)

    setor = relationship("Setor", back_populates="zonas")

    __table_args__ = (UniqueConstraint("setor_id", "nome", name="uq_zona_nome_por_setor"),)


class Portal(Base):
    __tablename__ = "portais"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False)
    zona_a_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    zona_b_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    localizacao_fisica = Column(Text, nullable=True)

    zona_a = relationship("Zona", foreign_keys=[zona_a_id])
    zona_b = relationship("Zona", foreign_keys=[zona_b_id])
    leitores = relationship("Leitor", back_populates="portal")

    __table_args__ = (
        CheckConstraint("zona_a_id <> zona_b_id", name="ck_portal_zonas_distintas"),
    )


class Leitor(Base):
    __tablename__ = "leitores"

    id = Column(BigInteger, primary_key=True)
    portal_id = Column(BigInteger, ForeignKey("portais.id"), nullable=True)
    fabricante = Column(String, nullable=False)
    modelo = Column(String, nullable=False)
    identificador_serial = Column(String, nullable=False, unique=True)
    endereco_rede = Column(String, nullable=True)
    status = Column(String, nullable=False, server_default="offline")
    ultimo_heartbeat_em = Column(TIMESTAMP(timezone=True), nullable=True)

    portal = relationship("Portal", back_populates="leitores")
    antenas = relationship("Antena", back_populates="leitor")


class Antena(Base):
    __tablename__ = "antenas"

    id = Column(BigInteger, primary_key=True)
    leitor_id = Column(BigInteger, ForeignKey("leitores.id"), nullable=False)
    porta_numero = Column(Integer, nullable=False)
    zona_associada_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    funcao = Column(String, nullable=False)  # 'entrada' | 'saida' | 'indefinido'

    leitor = relationship("Leitor", back_populates="antenas")
    zona_associada = relationship("Zona")

    __table_args__ = (
        UniqueConstraint("leitor_id", "porta_numero", name="uq_antena_por_porta_leitor"),
        CheckConstraint(
            "funcao IN ('entrada', 'saida', 'indefinido')", name="ck_antena_funcao_valida"
        ),
    )


class LeituraBruta(Base):
    """
    RF-007 / RF-008. Sem FK direta para `tags`: uma leitura de EPC ainda
    não cadastrado não pode ser perdida, só fica "órfã" do lado do ativo
    até alguém cadastrar aquele EPC.
    """

    __tablename__ = "leituras_brutas"

    id = Column(BigInteger, primary_key=True)
    # Gerado no app/ingestão (não no banco) — chave de idempotência.
    event_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    antena_id = Column(BigInteger, ForeignKey("antenas.id"), nullable=False)
    epc = Column(String, nullable=False)
    rssi = Column(Numeric, nullable=False)
    lido_em = Column(TIMESTAMP(timezone=True), nullable=False)
    recebido_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    antena = relationship("Antena")

    __table_args__ = (
        Index("ix_leituras_brutas_epc_lido_em", "epc", "lido_em"),
        Index("ix_leituras_brutas_antena_lido_em", "antena_id", "lido_em"),
    )


class Passagem(Base):
    """RF-009 a RF-011. antena_destino/direcao ficam NULL até a inferência
    de direção (RF-011, Should) estar implementada."""

    __tablename__ = "passagens"

    id = Column(BigInteger, primary_key=True)
    epc = Column(String, nullable=False)
    portal_id = Column(BigInteger, ForeignKey("portais.id"), nullable=False)
    antena_origem_id = Column(BigInteger, ForeignKey("antenas.id"), nullable=False)
    antena_destino_id = Column(BigInteger, ForeignKey("antenas.id"), nullable=True)
    direcao = Column(String, nullable=True)  # 'entrada' | 'saida' | 'indeterminada'
    leitura_origem_id = Column(BigInteger, ForeignKey("leituras_brutas.id"), nullable=False)
    leitura_destino_id = Column(BigInteger, ForeignKey("leituras_brutas.id"), nullable=True)
    detectada_em = Column(TIMESTAMP(timezone=True), nullable=False)

    portal = relationship("Portal")
    antena_origem = relationship("Antena", foreign_keys=[antena_origem_id])
    antena_destino = relationship("Antena", foreign_keys=[antena_destino_id])
    leitura_origem = relationship("LeituraBruta", foreign_keys=[leitura_origem_id])
    leitura_destino = relationship("LeituraBruta", foreign_keys=[leitura_destino_id])

    __table_args__ = (
        Index("ix_passagens_epc_detectada_em", "epc", "detectada_em"),
        Index("ix_passagens_portal_detectada_em", "portal_id", "detectada_em"),
        CheckConstraint(
            "direcao IS NULL OR direcao IN ('entrada', 'saida', 'indeterminada')",
            name="ck_passagem_direcao_valida",
        ),
    )


class HistoricoMovimentacao(Base):
    """RF-013 / RF-020. passagem_id NULL = correção manual."""

    __tablename__ = "historico_movimentacoes"

    id = Column(BigInteger, primary_key=True)
    equipamento_id = Column(BigInteger, ForeignKey("equipamentos.id"), nullable=False)
    zona_origem_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=True)
    zona_destino_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    passagem_id = Column(BigInteger, ForeignKey("passagens.id"), nullable=True)
    origem_registro = Column(String, nullable=False)  # 'passagem_automatica' | 'correcao_manual'
    registrado_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    equipamento = relationship("Equipamento", back_populates="historico")
    zona_origem = relationship("Zona", foreign_keys=[zona_origem_id])
    zona_destino = relationship("Zona", foreign_keys=[zona_destino_id])
    passagem = relationship("Passagem")

    __table_args__ = (
        Index("ix_historico_equipamento_registrado_em", "equipamento_id", "registrado_em"),
        CheckConstraint(
            "origem_registro IN ('passagem_automatica', 'correcao_manual')",
            name="ck_historico_origem_valida",
        ),
    )


class Perfil(Base):
    __tablename__ = "perfis"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False, unique=True)  # 'operacional' | 'administrador'

    usuarios = relationship("Usuario", back_populates="perfil")


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    senha_hash = Column(String, nullable=False)
    perfil_id = Column(BigInteger, ForeignKey("perfis.id"), nullable=False)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    perfil = relationship("Perfil", back_populates="usuarios")


class Auditoria(Base):
    """RF-023 / RNF-006. Genérica o suficiente para auditar qualquer
    tabela sem precisar de uma tabela de auditoria por entidade."""

    __tablename__ = "auditorias"

    id = Column(BigInteger, primary_key=True)
    usuario_id = Column(BigInteger, ForeignKey("usuarios.id"), nullable=True)  # NULL = sistema
    entidade = Column(String, nullable=False)
    entidade_id = Column(BigInteger, nullable=False)
    acao = Column(String, nullable=False)  # 'create' | 'update' | 'delete' | 'correcao_manual'
    dados_antes = Column(JSONB, nullable=True)
    dados_depois = Column(JSONB, nullable=True)
    registrado_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    usuario = relationship("Usuario")

    __table_args__ = (
        Index("ix_auditorias_entidade", "entidade", "entidade_id", "registrado_em"),
        CheckConstraint(
            "acao IN ('create', 'update', 'delete', 'correcao_manual')",
            name="ck_auditoria_acao_valida",
        ),
    )
