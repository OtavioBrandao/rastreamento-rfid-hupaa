"""
Models SQLAlchemy do MVP de rastreamento RFID (EASY/HUPAA).

Mirrors the canonical schema defined in "docs/architecture/data-model.md" and the
"docs/architecture/er-diagrama.mermaid" ER diagram. Any schema change must be
reflected in both artifacts to avoid divergence.

Convenções:
- Tabelas em português, plural, snake_case.
- PK interna: BigInteger autoincremento (BIGSERIAL, default do SQLAlchemy
  para `BigInteger, primary_key=True` no dialeto Postgres).
- Timestamps: sempre TIMESTAMP(timezone=True); a aplicação grava em UTC.
"""

from sqlalchemy import (
    TIMESTAMP,
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base


class TipoEquipamento(Base):
    """
    ISS-009. `nome` guarda o texto como o usuário digitou (é o que aparece
    na tela); `nome_normalizado` é a chave real de unicidade — sem acento,
    sem espaço sobrando e em minúsculas (ver `api/normalizacao.py`). Sem
    ela, "Cadeira de Rodas" e "cadeira  de rodas" entrariam como dois
    tipos diferentes.

    Baixa é sempre LÓGICA (`ativo = false`), nunca DELETE: `equipamentos`
    tem FK obrigatória para cá (ISS-008) e o histórico precisa continuar
    resolvendo o tipo de um equipamento mesmo depois de ele sair de uso.

    A UniqueConstraint é declarada com nome explícito (em vez de
    `unique=True` na coluna) porque o `unique=True` gera uma constraint
    anônima, cujo nome o Postgres escolhe — e aí o `downgrade` da
    migration não tem como derrubá-la de forma determinística.
    """

    __tablename__ = "tipos_equipamento"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False, unique=True)
    nome_normalizado = Column(String, nullable=False)
    descricao = Column(Text, nullable=True)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    # Mesma ressalva do `updated_at` de `equipamentos`: `onupdate` só
    # dispara em UPDATE feito via SQLAlchemy, não em SQL cru.
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    equipamentos = relationship("Equipamento", back_populates="tipo")

    __table_args__ = (
        UniqueConstraint("nome_normalizado", name="uq_tipos_equipamento_nome_normalizado"),
        Index("ix_tipos_equipamento_ativo", "ativo"),
    )


class Equipamento(Base):
    """
    ISS-008. `identificador_interno` é a etiqueta física do ativo (nº de
    patrimônio) — imutável depois de criado, o schema de update nem aceita
    o campo. `identificador_interno_normalizado` é a chave real de
    unicidade, mesmo padrão de `TipoEquipamento.nome_normalizado`.

    Baixa é sempre LÓGICA (`status = 'inativo'`), nunca DELETE — mesmo
    critério de `TipoEquipamento`, mas aqui sem bloqueio de "em uso":
    inativar um equipamento não quebra integridade de nada.

    A CHECK de `status` restringe às duas transições que esta issue cobre.
    Se um status novo (ex.: "manutenção") virar necessário, é uma
    migration própria que altera a CHECK — não um valor livre.
    """

    __tablename__ = "equipamentos"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False)
    tipo_id = Column(BigInteger, ForeignKey("tipos_equipamento.id"), nullable=False)
    identificador_interno = Column(String, nullable=False, unique=True)
    identificador_interno_normalizado = Column(String, nullable=False)
    descricao = Column(Text, nullable=True)
    status = Column(String, nullable=False, server_default="ativo")

    # RF-012: última localização conhecida vive como colunas no próprio
    # equipamento (relação 1:1) em vez de tabela separada.
    ultima_zona_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=True)
    ultima_deteccao_em = Column(TIMESTAMP(timezone=True), nullable=True)
    ultima_passagem_id = Column(BigInteger, ForeignKey("passagens.id"), nullable=True)
    ultima_movimentacao_id = Column(
        BigInteger, ForeignKey("historico_movimentacoes.id"), nullable=True
    )

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    # onupdate=func.now() só dispara em UPDATEs feitos VIA SQLAlchemy.
    # Um UPDATE executado direto em SQL (fora do ORM) não atualiza este
    # campo automaticamente. Aceitável para o MVP (revisão de código,
    # Otávio) — se isso virar problema real, a correção é um trigger de
    # banco (`BEFORE UPDATE ... SET updated_at = now()`), não implementado
    # agora.
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    tipo = relationship("TipoEquipamento", back_populates="equipamentos")
    ultima_zona = relationship("Zona", foreign_keys=[ultima_zona_id])
    ultima_passagem = relationship("Passagem", foreign_keys=[ultima_passagem_id])
    ultima_movimentacao = relationship(
        "HistoricoMovimentacao", foreign_keys=[ultima_movimentacao_id]
    )
    associacoes_tag = relationship("AssociacaoTagEquipamento", back_populates="equipamento")
    historico = relationship(
        "HistoricoMovimentacao", back_populates="equipamento",
        foreign_keys="HistoricoMovimentacao.equipamento_id",
    )

    __table_args__ = (
        Index("ix_equipamentos_tipo_id", "tipo_id"),
        Index("ix_equipamentos_ultima_zona_id", "ultima_zona_id"),
        Index("ix_equipamentos_ultima_deteccao_em", "ultima_deteccao_em"),
        Index("ix_equipamentos_status", "status"),
        UniqueConstraint(
            "identificador_interno_normalizado",
            name="uq_equipamentos_identificador_interno_normalizado",
        ),
        CheckConstraint(
            "status IN ('ativo', 'inativo')", name="ck_equipamento_status_valido"
        ),
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

    Semântica temporal (revisão de código, Otávio): o intervalo de cada
    associação é **meio-aberto** `[inicio, fim)` — ou seja, uma leitura
    com `lido_em == fim` já pertence à associação SEGUINTE, não a essa.
    Para descobrir a qual equipamento um EPC pertencia no momento T de
    uma leitura (não necessariamente o vínculo ativo HOJE):

        SELECT equipamento_id FROM associacoes_tag_equipamento
        WHERE tag_id = :tag_id
          AND inicio <= :t
          AND (fim IS NULL OR fim > :t)

    Isso é o que garante que uma leitura antiga continue relacionada ao
    equipamento correto mesmo depois de uma troca de tag (ex.: Tag A na
    cadeira em janeiro, na maca em março — uma leitura de janeiro deve
    seguir apontando para a cadeira).

    Constraint de banco vs. responsabilidade de aplicação: o CHECK abaixo
    garante que `fim >= inicio` dentro de UMA linha. Impedir períodos
    SOBREPOSTOS entre linhas diferentes da mesma tag (ex.: duas
    associações "ativas ao mesmo tempo" por erro de aplicação) NÃO é
    garantido pelo banco nesta migration — fica sob responsabilidade da
    aplicação, que deve sempre fechar (`fim = now()`) a associação
    anterior antes de abrir uma nova, dentro da mesma transação. Se isso
    se mostrar insuficiente, a evolução natural é uma constraint
    `EXCLUDE` sobre `tstzrange(inicio, fim)` com a extensão `btree_gist`
    — não implementada agora por ser complexidade desnecessária pro MVP.
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
        CheckConstraint(
            "fim IS NULL OR fim >= inicio", name="ck_associacao_periodo_valido"
        ),
    )


class Andar(Base):
    """
    Nível 1 da hierarquia física (andar -> setor -> zona), ISS-011 (RF-004).
    `nome_normalizado` é único GLOBALMENTE. Ver `TipoEquipamento` para a
    lógica de `nome`/`nome_normalizado`/`ativo`: baixa sempre LÓGICA, nunca
    DELETE, porque portais/antenas/histórico/equipamentos referenciam a
    hierarquia.
    """

    __tablename__ = "andares"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False, unique=True)
    nome_normalizado = Column(String, nullable=False)
    descricao = Column(Text, nullable=True)
    referencia_planta = Column(String, nullable=True)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    setores = relationship("Setor", back_populates="andar")

    __table_args__ = (
        UniqueConstraint("nome_normalizado", name="uq_andares_nome_normalizado"),
    )


class Setor(Base):
    """
    Nível 2. `nome_normalizado` é único DENTRO do andar (o mesmo nome em
    andares diferentes é permitido — ex.: "Enfermaria" no 3º e no 4º).
    """

    __tablename__ = "setores"

    id = Column(BigInteger, primary_key=True)
    andar_id = Column(BigInteger, ForeignKey("andares.id"), nullable=False)
    nome = Column(String, nullable=False)
    nome_normalizado = Column(String, nullable=False)
    descricao = Column(Text, nullable=True)
    referencia_planta = Column(String, nullable=True)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    andar = relationship("Andar", back_populates="setores")
    zonas = relationship("Zona", back_populates="setor")

    __table_args__ = (
        UniqueConstraint("andar_id", "nome", name="uq_setor_nome_por_andar"),
        UniqueConstraint(
            "andar_id", "nome_normalizado", name="uq_setor_nome_normalizado_por_andar"
        ),
    )


class Zona(Base):
    """
    Nível 3. `nome_normalizado` é único DENTRO do setor.

    `observacoes` (zona morta) é semanticamente diferente de `descricao`:
    é a anotação textual de zona morta descrita em "Termos e definições".
    Só a zona tem esse campo, e o CRUD da ISS-011 o expõe (criar, PATCH e
    resposta) como qualquer outro campo opcional.
    """

    __tablename__ = "zonas"

    id = Column(BigInteger, primary_key=True)
    setor_id = Column(BigInteger, ForeignKey("setores.id"), nullable=False)
    nome = Column(String, nullable=False)
    nome_normalizado = Column(String, nullable=False)
    descricao = Column(Text, nullable=True)
    referencia_planta = Column(String, nullable=True)
    # Zona morta não é entidade própria: é só uma observação textual
    # sobre uma zona já existente (ver "Termos e definições").
    observacoes = Column(Text, nullable=True)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    setor = relationship("Setor", back_populates="zonas")

    __table_args__ = (
        UniqueConstraint("setor_id", "nome", name="uq_zona_nome_por_setor"),
        UniqueConstraint(
            "setor_id", "nome_normalizado", name="uq_zona_nome_normalizado_por_setor"
        ),
    )


class Portal(Base):
    """
    ISS-012. Um portal é o conjunto de antenas que detecta a passagem entre
    duas zonas. A associação portal <-> antena é DIRETA (`Antena.portal_id`):
    um portal pode agregar antenas de leitores diferentes, e um leitor pode
    ter antenas em portais diferentes.

    `ativo` é o ciclo de vida do CADASTRO (baixa lógica, nunca DELETE). Inativar
    um portal NÃO é bloqueado por `passagens` que o referenciam: hardware
    inativo continua referenciado pelo histórico.
    """

    __tablename__ = "portais"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False)
    zona_a_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    zona_b_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    localizacao_fisica = Column(Text, nullable=True)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    zona_a = relationship("Zona", foreign_keys=[zona_a_id])
    zona_b = relationship("Zona", foreign_keys=[zona_b_id])
    antenas = relationship("Antena", back_populates="portal")
    mapeamentos_antena = relationship("MapeamentoAntenaPortal", back_populates="portal")

    __table_args__ = (
        CheckConstraint("zona_a_id <> zona_b_id", name="ck_portal_zonas_distintas"),
    )


class Leitor(Base):
    """
    ISS-012. Três identificadores DISTINTOS, que podem até coincidir por
    acaso mas não são o mesmo campo:
    - `id`: PK interna.
    - `reader_id`: identificador lógico usado como ORIGEM no MQTT (segmento
      `<reader_id>` do tópico `easy/<env>/<site>/<portal>/<reader_id>/readings`).
    - `identificador_serial`: número de série de fábrica, inalterado.

    `ativo` (cadastro/ciclo de vida, gerido por este CRUD) é SEPARADO de
    `status`/`ultimo_heartbeat_em` (conectividade ao vivo, geridos pela
    ingestão/heartbeat — o CRUD só os expõe para leitura).

    `parametros_ingestao` guarda metadados de ingestão ESTRITAMENTE
    não-secretos. Senha/credencial de broker fica fora do banco (env/secret
    manager), como o `DATABASE_URL`. A barreira é uma ALLOWLIST FECHADA de chaves
    (`protocolo`, `adapter`, `formato_timestamp`, `topico`, `qos`), com o valor de
    cada uma validado, no schema da API (`api/schemas_hardware.py`) — o banco não
    tem como reconhecer um segredo.

    Não há mais `portal_id` aqui: a associação com portal mora na antena.
    """

    __tablename__ = "leitores"

    id = Column(BigInteger, primary_key=True)
    reader_id = Column(String, nullable=False)
    fabricante = Column(String, nullable=False)
    modelo = Column(String, nullable=False)
    identificador_serial = Column(String, nullable=False, unique=True)
    endereco_rede = Column(String, nullable=True)
    # none_as_null: sem isso, None viraria o literal JSON `null` em vez de SQL NULL.
    parametros_ingestao = Column(JSONB(none_as_null=True), nullable=True)
    status = Column(String, nullable=False, server_default="offline")
    ultimo_heartbeat_em = Column(TIMESTAMP(timezone=True), nullable=True)
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    antenas = relationship("Antena", back_populates="leitor")

    __table_args__ = (UniqueConstraint("reader_id", name="uq_leitores_reader_id"),)


class Antena(Base):
    """
    ISS-012. `portal_id` (nullable) liga a antena DIRETAMENTE ao portal: uma
    antena pode existir antes de ser instalada em algum portal, e antenas do
    mesmo portal podem vir de leitores diferentes.

    `leitor_id` é imutável (a antena é fisicamente cabeada naquele leitor);
    `portal_id` é uma associação lógica e pode mudar, inclusive voltar a NULL.

    Coerência de topologia (revisão de código, Otávio): `zona_associada_id`
    deveria, por regra de negócio, ser sempre uma das duas zonas do portal
    a que esta antena pertence (`portal.zona_a_id` ou `zona_b_id`). Essa
    regra NÃO é validada pelo banco — fica para a ISS-013 (associar antena a
    lado/zona/função do portal), como validação de aplicação.
    """

    __tablename__ = "antenas"

    id = Column(BigInteger, primary_key=True)
    leitor_id = Column(BigInteger, ForeignKey("leitores.id"), nullable=False)
    portal_id = Column(BigInteger, ForeignKey("portais.id", name="fk_antenas_portal_id"), nullable=True)
    porta_numero = Column(Integer, nullable=False)
    zona_associada_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    funcao = Column(String, nullable=False)  # 'entrada' | 'saida' | 'indefinido'
    ativo = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    leitor = relationship("Leitor", back_populates="antenas")
    portal = relationship("Portal", back_populates="antenas")
    zona_associada = relationship("Zona")
    mapeamentos_portal = relationship("MapeamentoAntenaPortal", back_populates="antena")

    __table_args__ = (
        # Índice único PARCIAL (mesmo padrão de `uq_tag_ativa`, ISS-010): só as
        # antenas ATIVAS ocupam a porta do leitor. Inativar uma antena libera a
        # porta para uma antena nova; a linha antiga continua (o histórico de
        # leituras a referencia). Reativar uma antena cuja porta já foi tomada
        # por outra ativa viola o índice — o serviço traduz isso.
        Index(
            "uq_antena_ativa_por_porta_leitor",
            "leitor_id",
            "porta_numero",
            unique=True,
            postgresql_where=(ativo.is_(True)),
        ),
        CheckConstraint(
            "funcao IN ('entrada', 'saida', 'indefinido')", name="ck_antena_funcao_valida"
        ),
        Index("ix_antenas_portal_id", "portal_id"),
    )


class MapeamentoAntenaPortal(Base):
    """
    ISS-013. Logical, versioned mapping defining the operational meaning of an
    antenna inside a portal (logical side A or B, adjacent zone, and function).

    `fim IS NULL` represents the currently active mapping. Historical records
    preserve previous configurations with `fim` populated, allowing past
    readings and passages to be interpreted deterministically.

    Temporal half-open interval [inicio, fim):
    - Reading at timestamp T belongs to this mapping if:
        inicio <= T and (fim IS NULL or fim > T)

    Invariants enforced at DB level:
    - lado IN ('a', 'b')
    - funcao IN ('entrada', 'saida', 'auxiliar')
    - fim IS NULL OR fim >= inicio
    - At most ONE active mapping per antenna via partial unique index
      `uq_mapeamento_antena_ativo` (WHERE fim IS NULL). Multiple antennas on
      the same side of a portal are explicitly allowed.
    """

    __tablename__ = "mapeamentos_antena_portal"

    id = Column(BigInteger, primary_key=True)
    antena_id = Column(
        BigInteger, ForeignKey("antenas.id", name="fk_mapeamentos_antena_id"), nullable=False
    )
    portal_id = Column(
        BigInteger, ForeignKey("portais.id", name="fk_mapeamentos_portal_id"), nullable=False
    )
    lado = Column(String(1), nullable=False)
    zona_id = Column(
        BigInteger, ForeignKey("zonas.id", name="fk_mapeamentos_zona_id"), nullable=False
    )
    funcao = Column(String(20), nullable=False)
    inicio = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    fim = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    antena = relationship("Antena", back_populates="mapeamentos_portal")
    portal = relationship("Portal", back_populates="mapeamentos_antena")
    zona = relationship("Zona")

    __table_args__ = (
        CheckConstraint("lado IN ('a', 'b')", name="ck_mapeamento_lado_valido"),
        CheckConstraint(
            "funcao IN ('entrada', 'saida', 'auxiliar')", name="ck_mapeamento_funcao_valida"
        ),
        CheckConstraint("fim IS NULL OR fim >= inicio", name="ck_mapeamento_periodo_valido"),
        Index(
            "uq_mapeamento_antena_ativo",
            "antena_id",
            unique=True,
            postgresql_where=(fim.is_(None)),
        ),
        Index("ix_mapeamentos_portal_id", "portal_id"),
        Index("ix_mapeamentos_antena_id", "antena_id"),
        Index("ix_mapeamentos_zona_id", "zona_id"),
    )


class LeituraBruta(Base):
    """
    RF-007 / RF-008. Sem FK direta para `tags`: uma leitura de EPC ainda
    não cadastrado não pode ser perdida, só fica "órfã" do lado do ativo
    até alguém cadastrar aquele EPC.

    Preserva diretamente o event_id canônico da ISS-005, sem outro hash.
    RSSI nulo significa unidade desconhecida; dados_origem preserva a origem.
    """

    __tablename__ = "leituras_brutas"

    id = Column(BigInteger, primary_key=True)
    # Gerado de forma determinística pela camada de ingestão (ver
    # docstring acima) — NUNCA por default aleatório aqui no model.
    event_id = Column(String(71), nullable=False, unique=True)
    antena_id = Column(BigInteger, ForeignKey("antenas.id"), nullable=False)
    epc = Column(String, nullable=False)
    rssi = Column(Numeric, nullable=True)
    dados_origem = Column(JSONB, nullable=True)
    lido_em = Column(TIMESTAMP(timezone=True), nullable=False)
    recebido_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    antena = relationship("Antena")

    __table_args__ = (
        Index("ix_leituras_brutas_epc_lido_em", "epc", "lido_em"),
        Index("ix_leituras_brutas_antena_lido_em", "antena_id", "lido_em"),
    )


class Passagem(Base):
    """ISS-015 guarda evidências temporais; ISS-016 interpreta lados e zonas."""

    __tablename__ = "passagens"

    id = Column(BigInteger, primary_key=True)
    epc = Column(String, nullable=False)
    portal_id = Column(BigInteger, ForeignKey("portais.id"), nullable=False)
    antena_origem_id = Column(BigInteger, ForeignKey("antenas.id"), nullable=False)
    antena_destino_id = Column(BigInteger, ForeignKey("antenas.id"), nullable=True)
    direcao = Column(String, nullable=True)  # a_para_b | b_para_a | indeterminada
    direcao_status = Column(String(20), nullable=True)
    direcao_regra = Column(String(40), nullable=True)
    zona_origem_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=True)
    zona_destino_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=True)
    leitura_origem_id = Column(BigInteger, ForeignKey("leituras_brutas.id"), nullable=False)
    leitura_destino_id = Column(BigInteger, ForeignKey("leituras_brutas.id"), nullable=True)
    detectada_em = Column(TIMESTAMP(timezone=True), nullable=False)

    portal = relationship("Portal")
    antena_origem = relationship("Antena", foreign_keys=[antena_origem_id])
    antena_destino = relationship("Antena", foreign_keys=[antena_destino_id])
    leitura_origem = relationship("LeituraBruta", foreign_keys=[leitura_origem_id])
    leitura_destino = relationship("LeituraBruta", foreign_keys=[leitura_destino_id])
    zona_origem = relationship("Zona", foreign_keys=[zona_origem_id])
    zona_destino = relationship("Zona", foreign_keys=[zona_destino_id])

    __table_args__ = (
        Index("uq_passagem_evidencias", "leitura_origem_id", "leitura_destino_id", unique=True),
        Index("ix_passagens_epc_detectada_em", "epc", "detectada_em"),
        Index("ix_passagens_portal_detectada_em", "portal_id", "detectada_em"),
        CheckConstraint(
            "direcao IS NULL OR direcao IN ('a_para_b', 'b_para_a', 'indeterminada')",
            name="ck_passagem_direcao_valida",
        ),
        CheckConstraint(
            "((direcao_status IS NULL AND direcao IS NULL AND direcao_regra IS NULL "
            "AND zona_origem_id IS NULL AND zona_destino_id IS NULL) OR "
            "(direcao_status = 'confirmed' AND direcao IN ('a_para_b', 'b_para_a') "
            "AND direcao_regra IS NOT NULL AND zona_origem_id IS NOT NULL "
            "AND zona_destino_id IS NOT NULL AND zona_origem_id <> zona_destino_id) OR "
            "(direcao_status IN ('ambiguous', 'unknown') AND direcao = 'indeterminada' "
            "AND direcao_regra IS NOT NULL AND zona_origem_id IS NULL "
            "AND zona_destino_id IS NULL)) IS TRUE",
            name="ck_passagem_direcao_estado",
        ),
    )


class HistoricoMovimentacao(Base):
    """RF-013: ledger append-only, sem materializar a última localização."""

    __tablename__ = "historico_movimentacoes"

    id = Column(BigInteger, primary_key=True)
    equipamento_id = Column(BigInteger, ForeignKey("equipamentos.id"), nullable=False)
    zona_origem_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=True)
    zona_destino_id = Column(BigInteger, ForeignKey("zonas.id"), nullable=False)
    passagem_id = Column(BigInteger, ForeignKey("passagens.id"), nullable=True)
    epc = Column(String, nullable=True)
    portal_id = Column(BigInteger, ForeignKey("portais.id"), nullable=True)
    leitura_origem_id = Column(BigInteger, ForeignKey("leituras_brutas.id"), nullable=True)
    leitura_destino_id = Column(BigInteger, ForeignKey("leituras_brutas.id"), nullable=True)
    movimentada_em = Column(TIMESTAMP(timezone=True), nullable=True)
    justificativa = Column(Text, nullable=True)
    registro_anterior_id = Column(BigInteger, ForeignKey("historico_movimentacoes.id"), nullable=True)
    origem_registro = Column(String, nullable=False)  # 'passagem_automatica' | 'correcao_manual'
    registrado_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    equipamento = relationship(
        "Equipamento", back_populates="historico", foreign_keys=[equipamento_id]
    )
    zona_origem = relationship("Zona", foreign_keys=[zona_origem_id])
    zona_destino = relationship("Zona", foreign_keys=[zona_destino_id])
    passagem = relationship("Passagem")
    portal = relationship("Portal")
    leitura_origem = relationship("LeituraBruta", foreign_keys=[leitura_origem_id])
    leitura_destino = relationship("LeituraBruta", foreign_keys=[leitura_destino_id])
    registro_anterior = relationship("HistoricoMovimentacao", remote_side=[id])

    __table_args__ = (
        Index("ix_historico_equipamento_registrado_em", "equipamento_id", "registrado_em"),
        Index("ix_historico_equipamento_movimentada_id", "equipamento_id", "movimentada_em", "id"),
        Index("ix_historico_atividade_recente", "movimentada_em", "id",
              postgresql_where=movimentada_em.is_not(None)),
        Index("uq_historico_passagem_automatica", "passagem_id", unique=True,
              postgresql_where=(origem_registro == "passagem_automatica")),
        CheckConstraint(
            "origem_registro IN ('passagem_automatica', 'correcao_manual')",
            name="ck_historico_origem_valida",
        ),
        CheckConstraint(
            "(origem_registro = 'passagem_automatica' AND passagem_id IS NOT NULL "
            "AND epc IS NOT NULL AND portal_id IS NOT NULL AND leitura_origem_id IS NOT NULL "
            "AND leitura_destino_id IS NOT NULL AND movimentada_em IS NOT NULL "
            "AND zona_origem_id IS NOT NULL AND zona_origem_id <> zona_destino_id "
            "AND justificativa IS NULL AND registro_anterior_id IS NULL) OR "
            "(origem_registro = 'correcao_manual' AND passagem_id IS NULL "
            "AND justificativa IS NOT NULL AND length(btrim(justificativa)) > 0 "
            "AND movimentada_em IS NOT NULL)",
            name="ck_historico_registro_completo",
        ),
    )


class Perfil(Base):
    """ISS-026: as duas linhas são semeadas pela migration, não pela aplicação."""

    __tablename__ = "perfis"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False, unique=True)  # 'operacional' | 'administrador'

    usuarios = relationship("Usuario", back_populates="perfil")


class Usuario(Base):
    """
    ISS-026. `email` é o login e fica SEMPRE normalizado (minúsculas, sem
    espaço nas pontas); a CHECK garante isso no banco, não só na API.
    Baixa é lógica (`ativo = false`): `auditorias` referencia o autor.

    `tentativas_falhas` conta falhas SEGUIDAS de senha; ao atingir o limite a
    conta recebe `bloqueado_ate` e o contador volta a zero. `senha_hash`
    guarda apenas o hash Argon2id — nunca a senha.
    """

    __tablename__ = "usuarios"

    id = Column(BigInteger, primary_key=True)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    senha_hash = Column(String, nullable=False)
    perfil_id = Column(BigInteger, ForeignKey("perfis.id"), nullable=False)
    ativo = Column(Boolean, nullable=False, server_default="true")
    deve_trocar_senha = Column(Boolean, nullable=False, server_default="false")
    tentativas_falhas = Column(Integer, nullable=False, server_default="0")
    bloqueado_ate = Column(TIMESTAMP(timezone=True), nullable=True)
    ultimo_login_em = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    perfil = relationship("Perfil", back_populates="usuarios")
    sessoes = relationship("Sessao", back_populates="usuario")

    __table_args__ = (
        CheckConstraint("email = lower(btrim(email))", name="ck_usuarios_email_normalizado"),
        CheckConstraint("tentativas_falhas >= 0", name="ck_usuarios_tentativas_nao_negativas"),
    )


class Sessao(Base):
    """
    ISS-026. Sessão de login com token opaco: o token aleatório (256 bits)
    vai só no cookie do navegador; aqui fica apenas o SHA-256 dele, em hex.
    Quem lê o banco não consegue reapresentar uma sessão.

    Válida = `revogada_em IS NULL`, `expira_em` no futuro e usuário ativo.
    Revogar nunca apaga a linha: `motivo_revogacao` explica o encerramento.
    """

    __tablename__ = "sessoes"

    id = Column(BigInteger, primary_key=True)
    usuario_id = Column(
        BigInteger, ForeignKey("usuarios.id", name="fk_sessoes_usuario_id"), nullable=False
    )
    token_hash = Column(String(64), nullable=False)
    criada_em = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    expira_em = Column(TIMESTAMP(timezone=True), nullable=False)
    revogada_em = Column(TIMESTAMP(timezone=True), nullable=True)
    motivo_revogacao = Column(String(30), nullable=True)

    usuario = relationship("Usuario", back_populates="sessoes")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessoes_token_hash"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_sessoes_token_hash_formato"),
        CheckConstraint("expira_em > criada_em", name="ck_sessoes_expiracao_posterior"),
        CheckConstraint(
            "(revogada_em IS NULL) = (motivo_revogacao IS NULL)",
            name="ck_sessoes_revogacao_consistente",
        ),
        CheckConstraint(
            "motivo_revogacao IS NULL OR motivo_revogacao IN "
            "('logout', 'troca_senha', 'redefinicao_senha', 'desativacao')",
            name="ck_sessoes_motivo_valido",
        ),
        Index(
            "ix_sessoes_usuario_nao_revogadas",
            "usuario_id",
            postgresql_where=(revogada_em.is_(None)),
        ),
    )


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
