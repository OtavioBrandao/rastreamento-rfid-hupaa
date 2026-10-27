"""Consulta paginada da projeção ISS-017, sem inferir localização por leitura bruta.

A última leitura bruta é exposta à parte (`ultima_leitura`) como presença.
"""

from datetime import datetime, timedelta

from sqlalchemy import and_, case, false, func, literal_column, or_, select, true
from sqlalchemy.orm import Session, contains_eager

from api.equipamento_visivel import nao_arquivado
from api.schemas_busca_ativos import AtivoBusca, BuscaAtivosPagina, LeituraRecente, ZonaBusca
from api.service_leituras import ultimas_leituras
from api.timestamps import em_utc
from db.models import AssociacaoTagEquipamento, Equipamento, LeituraBruta, Setor, Tag, Zona
from rfid_location.recency import classify_recency

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
# Mesmo intervalo da badge "Lida agora" no frontend; não muda a recência da zona.
PRESENCE_FRESH_WINDOW = timedelta(seconds=30)


def _nome_natural():
    """Produz chave SQL de nome com números naturais, antes da paginação.

    Divide o nome em trechos textuais e numéricos: Bomba 2 precede Bomba 10.
    Números são comparados por quantidade de dígitos e valor textual, sem
    conversão para inteiro nem limite de tamanho. O ID desempata nomes iguais.
    A expressão é fixa e não interpola filtros fornecidos pelo usuário.
    """
    return literal_column("""ARRAY(
        SELECT CASE WHEN parte[1] ~ '^[0-9]+$'
            THEN lpad(length(ltrim(parte[1], '0'))::text, 10, '0')
                || ltrim(parte[1], '0')
            ELSE parte[1] END
        FROM regexp_matches(
            translate(lower(equipamentos.nome),
                'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc'),
            '([0-9]+|[^0-9]+)', 'g') WITH ORDINALITY AS partes(parte, posicao)
        ORDER BY posicao
    )""")


def _escape_like(value: str) -> str:
    """Escapa barra, porcentagem e sublinhado para busca textual literal com LIKE."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def buscar(
    db: Session,
    *,
    now: datetime,
    threshold: timedelta,
    q: str | None = None,
    tipo: int | None = None,
    epc: str | None = None,
    status: str | None = None,
    zona: int | None = None,
    equipamento_id: int | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE_DEFAULT,
    sort: str = "nome",
    somente_ativos: bool = False,
) -> BuscaAtivosPagina:
    # Os vínculos ativos são únicos por equipamento e tag no PostgreSQL.
    """Consulta ativos filtrados, conta o total e ordena antes de paginar.

    now e threshold fixam a classificação temporal de toda a página. A prioridade
    usa somente a tag ativa e agrupa presença/trânsito antes da ordem natural do
    nome. A última leitura é presença; não altera a zona confirmada."""
    query = (
        db.query(Equipamento, Tag.epc)
        .join(Equipamento.tipo)
        .outerjoin(
            AssociacaoTagEquipamento,
            and_(
                AssociacaoTagEquipamento.equipamento_id == Equipamento.id,
                AssociacaoTagEquipamento.fim.is_(None),
            ),
        )
        .outerjoin(Tag, Tag.id == AssociacaoTagEquipamento.tag_id)
        .outerjoin(Equipamento.ultima_zona)
        .options(
            contains_eager(Equipamento.tipo),
            contains_eager(Equipamento.ultima_zona)
            .joinedload(Zona.setor)
            .joinedload(Setor.andar),
        )
    )
    if somente_ativos:
        query = query.filter(nao_arquivado())  # fora de serviço continua visível
    if q is not None:
        pattern = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            Equipamento.nome.ilike(pattern, escape="\\"),
            Equipamento.identificador_interno.ilike(pattern, escape="\\"),
        ))
    if tipo is not None:
        query = query.filter(Equipamento.tipo_id == tipo)
    if epc is not None:
        query = query.filter(Tag.epc == epc)
    if zona is not None:
        query = query.filter(Equipamento.ultima_zona_id == zona)
    if equipamento_id is not None:
        query = query.filter(Equipamento.id == equipamento_id)

    cutoff = now - threshold
    # Predicados diretos permitem ao planner usar os índices de status e recência.
    status_predicates = {
        "nunca_detectado": Equipamento.ultima_deteccao_em.is_(None),
        "fora_de_servico": and_(Equipamento.ultima_deteccao_em.is_not(None),
                                Equipamento.status == "inativo"),
        "atencao": and_(Equipamento.status == "ativo",
                        Equipamento.ultima_deteccao_em < cutoff),
        "disponivel": and_(Equipamento.status == "ativo",
                           Equipamento.ultima_deteccao_em >= cutoff),
        "offline": false(),
    }
    if status is not None:
        query = query.filter(status_predicates[status])

    total = query.with_entities(func.count(Equipamento.id)).scalar() or 0
    ordering = {
        "nome": (Equipamento.nome.asc(), Equipamento.id.asc()),
        "-nome": (Equipamento.nome.desc(), Equipamento.id.asc()),
        "ultima_deteccao_em": (Equipamento.ultima_deteccao_em.asc().nullslast(),
                               Equipamento.id.asc()),
        "-ultima_deteccao_em": (Equipamento.ultima_deteccao_em.desc().nullslast(),
                                Equipamento.id.asc()),
    }
    if sort == "prioridade":
        # Busca indexada pela tag ativa; ordenar antes do LIMIT mantém a prioridade
        # entre páginas, sem promover leituras de EPCs desvinculados.
        last_read = (
            select(LeituraBruta.lido_em)
            .where(LeituraBruta.epc == Tag.epc)
            .order_by(LeituraBruta.lido_em.desc()).limit(1)
            .correlate(Tag).lateral("leitura_prioridade")
        )
        query = query.outerjoin(last_read, true())
        fresh = last_read.c.lido_em >= now - PRESENCE_FRESH_WINDOW
        priority = case(
            (and_(fresh, status_predicates["disponivel"]), 0),
            (status_predicates["disponivel"], 1),
            (fresh, 2),
            (status_predicates["atencao"], 3),
            (status_predicates["nunca_detectado"], 4),
            else_=5,
        )
        ordering["prioridade"] = (
            priority.asc(),
            _nome_natural().asc(), Equipamento.id.asc(),
        )
    rows = query.order_by(*ordering[sort]).limit(page_size).offset((page - 1) * page_size).all()
    leituras = ultimas_leituras(db, (epc for _, epc in rows if epc))
    items = []
    for equipment, active_epc in rows:
        recency = classify_recency(equipment.ultima_deteccao_em, now, threshold)
        if recency == "nunca_detectada":
            visual_status = "nunca_detectado"
        elif equipment.status == "inativo":
            visual_status = "fora_de_servico"
        elif recency == "desatualizada":
            visual_status = "atencao"
        else:
            visual_status = "disponivel"
        zone = equipment.ultima_zona if equipment.ultima_deteccao_em else None
        items.append(AtivoBusca(
            id=equipment.id,
            nome=equipment.nome,
            identificador_interno=equipment.identificador_interno,
            tipo=equipment.tipo.nome,
            tipo_id=equipment.tipo_id,
            epc=active_epc,
            status=visual_status,
            ultima_zona=ZonaBusca(
                id=zone.id, nome=zone.nome, referencia_planta=zone.referencia_planta,
                setor=zone.setor.nome, andar=zone.setor.andar.nome,
                caminho=f"{zone.setor.andar.nome} → {zone.setor.nome} → {zone.nome}",
            ) if zone else None,
            ultima_deteccao_em=em_utc(equipment.ultima_deteccao_em),
            localizacao_desatualizada=None if recency == "nunca_detectada"
            else recency == "desatualizada",
            ultima_leitura=LeituraRecente(**leituras[active_epc])
            if active_epc in leituras else None,
        ))
    return BuscaAtivosPagina(items=items, total=total, page=page, page_size=page_size)


def obter(db: Session, equipamento_id: int, *, now: datetime, threshold: timedelta) -> AtivoBusca | None:
    """Um ativo pelo ID, no mesmo formato da busca. O painel de detalhe recarrega por
    aqui: o ID é a identidade estável depois de uma correção de nome ou patrimônio
    (ISS-025), e uma busca textual paginada pode não trazer o item na 1ª página."""
    pagina = buscar(db, now=now, threshold=threshold, equipamento_id=equipamento_id, page_size=1)
    return pagina.items[0] if pagina.items else None
