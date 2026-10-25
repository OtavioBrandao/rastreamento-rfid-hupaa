"""Layouts e sessões do simulador web, com o estado compartilhado no banco.

O banco é a fonte da verdade de propósito: o dashboard (configuração e
monitoramento) e a aba de controle podem estar em navegadores diferentes, e
recarregar a página recupera tudo. Cada alteração da sessão incrementa
`versao` sob `SELECT ... FOR UPDATE`, então duas abas arrastando itens ao
mesmo tempo não perdem a escrita uma da outra.

A posição virtual dos itens só serve ao motor de publicação: o monitoramento
(`monitor`) é calculado inteiramente a partir do que o pipeline gravou —
leituras brutas, passagens e última zona confirmada —, nunca da posição.
"""

from __future__ import annotations

import copy
import random
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from api import service_cadastro
from api.epc import EpcInvalido, normalizar_epc
from api.normalizacao import normalizar_nome
from api.service_tipos_equipamento import criar as criar_tipo
from api.timestamps import em_utc
from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    Leitor,
    LeituraBruta,
    Passagem,
    Portal,
    SimulacaoLayout,
    SimulacaoSessao,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_ingestion.reader_status import StatusPolicy, classify
from rfid_location.recency import classify_recency, recency_threshold_from_env

from . import topologia
from .esquema import Layout, avisos
from .presets import (
    ITENS_TESTE_RAPIDO,
    NOMES_PRESET,
    NOMES_TESTE_RAPIDO,
    POSICOES_TESTE_RAPIDO,
    preset,
)
from .presets import teste_rapido as preset_teste_rapido

MAX_ITENS = 30
PREFIXO_EPC = "E2804C41"
ESTADOS_ABERTOS = ("em_execucao", "pausada")
# Mesmo tipo do launcher (tools/lab_launcher/seed.py) e da limpeza do banco.
TIPO_SINTETICO_LABORATORIO = "Equipamento sintético de laboratório RFID"


class SimulacaoRecusada(ValueError):
    """Regra do simulador recusada; `codigo` é estável para API e interface."""

    def __init__(self, codigo: str, mensagem: str, status: int = 409) -> None:
        """Guarda código, mensagem e status HTTP sugerido."""
        super().__init__(mensagem)
        self.codigo = codigo
        self.status = status


def validar_layout(configuracao: dict) -> Layout:
    """Valida a configuração; erros viram `SimulacaoRecusada` legível (422)."""
    try:
        return Layout.model_validate(configuracao)
    except ValidationError as erro:
        mensagens = []
        for item in erro.errors():
            local = ".".join(str(parte) for parte in item.get("loc", ()))
            texto = str(item.get("msg", "")).removeprefix("Value error, ")
            mensagens.append(f"{local}: {texto}" if local else texto)
        raise SimulacaoRecusada("layout_invalido", "; ".join(mensagens), 422) from erro


def _layout_dict(layout: Layout) -> dict:
    """Forma persistida: JSON puro, com a zona das antenas já derivada do portal."""
    return layout.model_dump(mode="json")


def resumo_layout(registro: SimulacaoLayout) -> dict:
    """Layout completo para a interface, com avisos não bloqueantes."""
    return {
        "id": registro.id, "nome": registro.nome, "cenario": registro.cenario,
        "configuracao": registro.configuracao, "versao": registro.versao,
        "arquivado": registro.arquivado, "aplicado_em": em_utc(registro.aplicado_em),
        "updated_at": em_utc(registro.updated_at),
        "avisos": avisos(Layout.model_validate(registro.configuracao)),
    }


def listar_layouts(db: Session, cenario: str | None = None) -> list[SimulacaoLayout]:
    """Layouts não arquivados, mais recentes primeiro."""
    consulta = select(SimulacaoLayout).where(SimulacaoLayout.arquivado.is_(False))
    if cenario:
        consulta = consulta.where(SimulacaoLayout.cenario == cenario)
    return list(db.scalars(consulta.order_by(SimulacaoLayout.updated_at.desc(),
                                             SimulacaoLayout.id.desc())))


def obter_layout(db: Session, layout_id: int, *, travar: bool = False) -> SimulacaoLayout:
    """Layout pelo id; 404 se não existir ou estiver arquivado."""
    consulta = select(SimulacaoLayout).where(SimulacaoLayout.id == layout_id)
    if travar:
        consulta = consulta.with_for_update()
    registro = db.scalar(consulta)
    if registro is None or registro.arquivado:
        raise SimulacaoRecusada("layout_inexistente", "layout não encontrado", 404)
    return registro


def criar_layout(db: Session, *, nome: str | None, cenario: str,
                 configuracao: dict | None = None) -> SimulacaoLayout:
    """Novo layout a partir do preset do cenário ou de uma configuração enviada."""
    base = configuracao if configuracao is not None else preset(cenario)
    layout = validar_layout(base)
    if layout.cenario != cenario:
        raise SimulacaoRecusada("cenario_divergente", "configuração de outro cenário", 422)
    registro = SimulacaoLayout(nome=(nome or "").strip() or NOMES_PRESET[cenario],
                               cenario=cenario, configuracao=_layout_dict(layout))
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def atualizar_layout(db: Session, layout_id: int, *, nome: str | None, configuracao: dict,
                     versao_esperada: int) -> SimulacaoLayout:
    """Salva o layout; versão otimista evita sobrescrever a edição de outra aba."""
    registro = obter_layout(db, layout_id, travar=True)
    if registro.versao != versao_esperada:
        raise SimulacaoRecusada("conflito_de_versao",
                                "o layout foi alterado em outra aba; recarregue antes de salvar")
    layout = validar_layout(configuracao)
    if layout.cenario != registro.cenario:
        raise SimulacaoRecusada("cenario_divergente", "não é possível trocar o cenário", 422)
    registro.configuracao = _layout_dict(layout)
    if nome is not None and nome.strip():
        registro.nome = nome.strip()[:120]
    registro.versao += 1
    db.commit()
    db.refresh(registro)
    return registro


def restaurar_preset(db: Session, layout_id: int) -> SimulacaoLayout:
    """Volta a configuração do layout ao preset do cenário."""
    registro = obter_layout(db, layout_id, travar=True)
    return atualizar_layout(db, layout_id, nome=None, configuracao=preset(registro.cenario),
                            versao_esperada=registro.versao)


def arquivar_layout(db: Session, layout_id: int) -> None:
    """Arquiva (não apaga) o layout; recusa se houver sessão aberta nele."""
    registro = obter_layout(db, layout_id, travar=True)
    if db.scalar(select(SimulacaoSessao.id).where(
            SimulacaoSessao.layout_id == layout_id,
            SimulacaoSessao.estado.in_(ESTADOS_ABERTOS))):
        raise SimulacaoRecusada("sessao_aberta", "encerre a simulação deste layout antes")
    registro.arquivado = True
    db.commit()


# --- sessões ------------------------------------------------------------------


def _agora() -> datetime:
    """Relógio UTC."""
    return datetime.now(timezone.utc)


def iniciar_sessao(db: Session, layout_id: int, usuario_id: int | None) -> SimulacaoSessao:
    """Aplica a topologia do layout e abre uma sessão nova (encerrando a anterior)."""
    registro = obter_layout(db, layout_id, travar=True)
    layout = validar_layout(registro.configuracao)
    agora = _agora()
    itens: list = []
    for anterior in db.scalars(select(SimulacaoSessao).where(
            SimulacaoSessao.layout_id == layout_id,
            SimulacaoSessao.estado.in_(ESTADOS_ABERTOS)).with_for_update()):
        itens = [dict(item, ultima_deteccao=None) for item in anterior.itens]
        anterior.estado, anterior.encerrada_em = "encerrada", agora
    db.flush()
    try:
        vinculos = topologia.aplicar(db, registro, layout)
    except topologia.TopologiaRecusada as erro:
        db.rollback()
        raise SimulacaoRecusada("topologia_recusada", str(erro)) from erro
    sessao = SimulacaoSessao(
        codigo=secrets.token_hex(8), layout_id=registro.id, cenario=registro.cenario,
        layout=_layout_dict(layout), topologia=vinculos, itens=itens, estado="em_execucao",
        criada_por=usuario_id, iniciada_em=agora, atualizada_em=agora)
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def obter_sessao(db: Session, codigo: str, *, travar: bool = False) -> SimulacaoSessao:
    """Sessão pelo código do link; 404 se não existir."""
    consulta = select(SimulacaoSessao).where(SimulacaoSessao.codigo == codigo)
    if travar:
        consulta = consulta.with_for_update()
    sessao = db.scalar(consulta)
    if sessao is None:
        raise SimulacaoRecusada("sessao_inexistente", "sessão de simulação não encontrada", 404)
    return sessao


def listar_sessoes(db: Session, *, abertas: bool = True, limite: int = 20) -> list[SimulacaoSessao]:
    """Sessões abertas (ou as últimas, inclusive encerradas)."""
    consulta = select(SimulacaoSessao)
    if abertas:
        consulta = consulta.where(SimulacaoSessao.estado.in_(ESTADOS_ABERTOS))
    return list(db.scalars(consulta.order_by(SimulacaoSessao.iniciada_em.desc()).limit(limite)))


def _alterar(db: Session, codigo: str, mudanca: Callable[[SimulacaoSessao, list[dict]], None]
             ) -> SimulacaoSessao:
    """Aplica uma mudança nos itens sob trava de linha e incrementa a versão."""
    sessao = obter_sessao(db, codigo, travar=True)
    if sessao.estado == "encerrada":
        raise SimulacaoRecusada("sessao_encerrada", "esta sessão já foi encerrada")
    itens = copy.deepcopy(sessao.itens)
    mudanca(sessao, itens)
    sessao.itens = itens
    sessao.versao += 1
    sessao.atualizada_em = _agora()
    db.commit()
    db.refresh(sessao)
    return sessao


def _gerar_epc(existentes: set[str]) -> str:
    """EPC de 96 bits com o prefixo de laboratório, sem repetir na sessão."""
    while True:
        epc = normalizar_epc(PREFIXO_EPC + f"{random.getrandbits(64):016X}")
        if epc not in existentes:
            return epc


def _epc_valido(epc: str, itens: list[dict], ignorar: str | None = None) -> str:
    """Normaliza o EPC e recusa repetição entre os itens da sessão."""
    try:
        epc = normalizar_epc(epc)
    except EpcInvalido as erro:
        raise SimulacaoRecusada("epc_invalido", str(erro), 422) from erro
    if any(item["epc"] == epc and item["id"] != ignorar for item in itens):
        raise SimulacaoRecusada("epc_repetido", "outro item desta simulação já usa este EPC")
    return epc


def _limitar(valor: float) -> float:
    """Mantém a posição dentro da planta."""
    return round(min(max(float(valor), 0.0), 100.0), 3)


def adicionar_item(db: Session, codigo: str, *, nome: str, tipo: str | None, epc: str | None,
                   gerar_epc: bool, x: float | None, y: float | None) -> SimulacaoSessao:
    """Novo equipamento virtual, com EPC informado, gerado ou sem etiqueta."""
    def mudanca(_sessao: SimulacaoSessao, itens: list[dict]) -> None:
        """Acrescenta o item na posição pedida (ou numa fila na borda da planta)."""
        if len(itens) >= MAX_ITENS:
            raise SimulacaoRecusada("limite_de_itens", f"no máximo {MAX_ITENS} itens por sessão")
        valor = None
        if epc:
            valor = _epc_valido(epc, itens)
        elif gerar_epc:
            valor = _gerar_epc({item["epc"] for item in itens if item["epc"]})
        # Sem posição informada: fila na borda inferior, longe das antenas do preset.
        px = _limitar(x if x is not None else 8 + (len(itens) % 6) * 16)
        py = _limitar(y if y is not None else 94 - (len(itens) // 6 % 4) * 5)
        itens.append({"id": f"it-{secrets.token_hex(4)}", "nome": nome.strip()[:80],
                      "tipo": (tipo or "").strip()[:60] or None, "epc": valor,
                      "x": px, "y": py, "x0": px, "y0": py})
    return _alterar(db, codigo, mudanca)


def alterar_item(db: Session, codigo: str, item_id: str, campos: dict) -> SimulacaoSessao:
    """Move, renomeia, etiqueta (EPC informado/gerado) ou remove a etiqueta."""
    def mudanca(_sessao: SimulacaoSessao, itens: list[dict]) -> None:
        """Aplica só os campos enviados ao item."""
        item = next((item for item in itens if item["id"] == item_id), None)
        if item is None:
            raise SimulacaoRecusada("item_inexistente", "item não encontrado", 404)
        if "x" in campos and campos["x"] is not None:
            item["x"] = _limitar(campos["x"])
        if "y" in campos and campos["y"] is not None:
            item["y"] = _limitar(campos["y"])
        if campos.get("nome"):
            item["nome"] = campos["nome"].strip()[:80]
        if "tipo" in campos and campos["tipo"] is not None:
            item["tipo"] = campos["tipo"].strip()[:60] or None
        if campos.get("remover_epc"):
            item["epc"] = None
        elif campos.get("epc"):
            item["epc"] = _epc_valido(campos["epc"], itens, ignorar=item_id)
        elif campos.get("gerar_epc"):
            item["epc"] = _gerar_epc({outro["epc"] for outro in itens if outro["epc"]})
    return _alterar(db, codigo, mudanca)


def remover_item(db: Session, codigo: str, item_id: str) -> SimulacaoSessao:
    """Retira o item da planta virtual (o cadastro no banco, se houver, fica)."""
    def mudanca(_sessao: SimulacaoSessao, itens: list[dict]) -> None:
        """Remove o item pelo id."""
        restantes = [item for item in itens if item["id"] != item_id]
        if len(restantes) == len(itens):
            raise SimulacaoRecusada("item_inexistente", "item não encontrado", 404)
        itens[:] = restantes
    return _alterar(db, codigo, mudanca)


def transicionar(db: Session, codigo: str, acao: str) -> SimulacaoSessao:
    """Pausar, retomar, reiniciar (reaplica o layout e volta os itens) ou encerrar."""
    sessao = obter_sessao(db, codigo, travar=True)
    if sessao.estado == "encerrada":
        raise SimulacaoRecusada("sessao_encerrada", "esta sessão já foi encerrada")
    agora = _agora()
    if acao == "pausar":
        sessao.estado = "pausada"
    elif acao == "retomar":
        sessao.estado = "em_execucao"
    elif acao == "encerrar":
        sessao.estado, sessao.encerrada_em = "encerrada", agora
    elif acao == "reiniciar":
        registro = obter_layout(db, sessao.layout_id, travar=True)
        layout = validar_layout(registro.configuracao)
        try:
            sessao.topologia = topologia.aplicar(db, registro, layout)
        except topologia.TopologiaRecusada as erro:
            db.rollback()
            raise SimulacaoRecusada("topologia_recusada", str(erro)) from erro
        sessao.layout = _layout_dict(layout)
        sessao.itens = [dict(item, x=item["x0"], y=item["y0"]) for item in sessao.itens]
        sessao.estado = "em_execucao"
    else:
        raise SimulacaoRecusada("acao_invalida", "ação desconhecida", 422)
    sessao.versao += 1
    sessao.atualizada_em = agora
    db.commit()
    db.refresh(sessao)
    return sessao


def limpar_itens(db: Session, codigo: str) -> SimulacaoSessao:
    """Tira todos os equipamentos virtuais da planta (cadastros no banco ficam)."""
    def mudanca(_sessao: SimulacaoSessao, itens: list[dict]) -> None:
        """Esvazia a lista."""
        itens.clear()
    return _alterar(db, codigo, mudanca)


def apagar_cenario(db: Session, cenario: str) -> dict:
    """Encerra as sessões abertas e arquiva todos os layouts do cenário.

    Nada do pipeline é apagado (leituras, passagens, histórico): isso fica com
    `tools.limpeza_banco`, que tem prévia, backup e travas de produção.
    """
    agora = _agora()
    sessoes = list(db.scalars(select(SimulacaoSessao).where(
        SimulacaoSessao.cenario == cenario,
        SimulacaoSessao.estado.in_(ESTADOS_ABERTOS)).with_for_update()))
    for sessao in sessoes:
        sessao.estado, sessao.encerrada_em = "encerrada", agora
        sessao.versao += 1
    layouts = list(db.scalars(select(SimulacaoLayout).where(
        SimulacaoLayout.cenario == cenario,
        SimulacaoLayout.arquivado.is_(False)).with_for_update()))
    for layout in layouts:
        layout.arquivado = True
    db.commit()
    return {"sessoes_encerradas": len(sessoes), "layouts_arquivados": len(layouts)}


def _tipo_laboratorio(db: Session) -> int:
    """Tipo dos equipamentos sintéticos do launcher (criado se faltar)."""
    nome = TIPO_SINTETICO_LABORATORIO
    tipo = db.scalar(select(TipoEquipamento).where(
        TipoEquipamento.nome_normalizado == normalizar_nome(nome)))
    return tipo.id if tipo is not None else criar_tipo(db, nome).id


def _cadastrar_demo(db: Session, nome: str, epc: str) -> None:
    """Cadastra o equipamento de demonstração se o EPC ainda não tiver vínculo."""
    if db.scalar(select(AssociacaoTagEquipamento.id).join(Tag).where(
            Tag.epc == epc, AssociacaoTagEquipamento.fim.is_(None))):
        return
    try:
        service_cadastro.cadastrar(db, nome=nome, tipo_id=_tipo_laboratorio(db),
                                   identificador_interno=f"LAB-RFID-{epc}", epc=epc)
    except (service_cadastro.TagJaAssociada, service_cadastro.IdentificadorDuplicado):
        db.rollback()  # outra aba cadastrou ao mesmo tempo, ou ficou de um teste anterior


def teste_rapido(db: Session, cenario: str, usuario_id: int | None) -> SimulacaoSessao:
    """Layout pronto + sessão iniciada + equipamentos de demonstração na planta.

    Reaproveita o layout do teste rápido se já existir (sem sobrescrever ajustes);
    se a sessão vier sem itens, coloca os equipamentos de demonstração.
    """
    registro = db.scalar(select(SimulacaoLayout).where(
        SimulacaoLayout.cenario == cenario, SimulacaoLayout.arquivado.is_(False),
        SimulacaoLayout.nome == NOMES_TESTE_RAPIDO[cenario]).order_by(SimulacaoLayout.id.desc()))
    if registro is None:
        registro = criar_layout(db, nome=NOMES_TESTE_RAPIDO[cenario], cenario=cenario,
                                configuracao=preset_teste_rapido(cenario))
    for item in ITENS_TESTE_RAPIDO:
        if item["cadastrar"]:
            _cadastrar_demo(db, item["nome"], item["epc"])
    sessao = iniciar_sessao(db, registro.id, usuario_id)
    if sessao.itens:
        return sessao

    def mudanca(_sessao: SimulacaoSessao, itens: list[dict]) -> None:
        """Coloca os itens de demonstração na fila inicial."""
        for item, (x, y) in zip(ITENS_TESTE_RAPIDO, POSICOES_TESTE_RAPIDO[cenario]):
            itens.append({"id": f"it-{secrets.token_hex(4)}", "nome": item["nome"],
                          "tipo": item["tipo"], "epc": item["epc"],
                          "x": x, "y": y, "x0": x, "y0": y})
    return _alterar(db, sessao.codigo, mudanca)


def resumo_sessao(sessao: SimulacaoSessao) -> dict:
    """Estado completo da sessão (o que as duas abas compartilham)."""
    return {
        "codigo": sessao.codigo, "layout_id": sessao.layout_id, "cenario": sessao.cenario,
        "estado": sessao.estado, "versao": sessao.versao, "layout": sessao.layout,
        "itens": sessao.itens, "iniciada_em": em_utc(sessao.iniciada_em),
        "atualizada_em": em_utc(sessao.atualizada_em), "encerrada_em": em_utc(sessao.encerrada_em),
    }


# --- monitoramento (somente o que o pipeline gravou) ---------------------------


def monitor(db: Session, sessao: SimulacaoSessao, *, now: datetime,
            policy: StatusPolicy | None = None, limite: int = 25) -> dict:
    """Leituras, passagens, leitores e zonas confirmadas desde o início da sessão."""
    policy = policy or StatusPolicy.from_env()
    topo = sessao.topologia
    antenas = {antena_id: chave for chave, antena_id in topo.get("antenas", {}).items()}
    zonas = {zona_id: chave for chave, zona_id in topo.get("zonas", {}).items()}
    portais = list(topo.get("portais", {}).values())
    leitores = topo.get("leitores", {})
    inicio = sessao.iniciada_em
    ids_antenas = list(antenas) or [0]

    vinculo = and_(AssociacaoTagEquipamento.tag_id == Tag.id,
                   AssociacaoTagEquipamento.fim.is_(None))
    leituras = db.execute(
        select(LeituraBruta.id, LeituraBruta.epc, LeituraBruta.antena_id, LeituraBruta.lido_em,
               LeituraBruta.rssi, Antena.porta_numero, Leitor.reader_id,
               Equipamento.id.label("equipamento_id"), Equipamento.nome.label("equipamento"))
        .join(Antena, Antena.id == LeituraBruta.antena_id)
        .join(Leitor, Leitor.id == Antena.leitor_id)
        .outerjoin(Tag, Tag.epc == LeituraBruta.epc)
        .outerjoin(AssociacaoTagEquipamento, vinculo)
        .outerjoin(Equipamento, Equipamento.id == AssociacaoTagEquipamento.equipamento_id)
        .where(LeituraBruta.antena_id.in_(ids_antenas), LeituraBruta.lido_em >= inicio)
        .order_by(LeituraBruta.id.desc()).limit(limite)
    ).all()
    total_leituras = db.scalar(select(func.count()).select_from(LeituraBruta).where(
        LeituraBruta.antena_id.in_(ids_antenas), LeituraBruta.lido_em >= inicio)) or 0

    epcs_sessao = db.execute(
        select(LeituraBruta.epc, func.count().label("leituras"),
               func.max(LeituraBruta.lido_em).label("ultima"),
               Equipamento.id.label("equipamento_id"), Equipamento.nome.label("equipamento"))
        .outerjoin(Tag, Tag.epc == LeituraBruta.epc)
        .outerjoin(AssociacaoTagEquipamento, vinculo)
        .outerjoin(Equipamento, Equipamento.id == AssociacaoTagEquipamento.equipamento_id)
        .where(LeituraBruta.antena_id.in_(ids_antenas), LeituraBruta.lido_em >= inicio)
        .group_by(LeituraBruta.epc, Equipamento.id, Equipamento.nome)
        .order_by(func.max(LeituraBruta.lido_em).desc())
    ).all()

    origem, destino = aliased(Zona), aliased(Zona)
    passagens = db.execute(
        select(Passagem.id, Passagem.epc, Passagem.direcao, Passagem.direcao_status,
               Passagem.detectada_em, Portal.nome.label("portal"),
               origem.nome.label("zona_origem"), destino.nome.label("zona_destino"),
               Equipamento.nome.label("equipamento"))
        .join(Portal, Portal.id == Passagem.portal_id)
        .outerjoin(origem, origem.id == Passagem.zona_origem_id)
        .outerjoin(destino, destino.id == Passagem.zona_destino_id)
        .outerjoin(Tag, Tag.epc == Passagem.epc)
        .outerjoin(AssociacaoTagEquipamento, vinculo)
        .outerjoin(Equipamento, Equipamento.id == AssociacaoTagEquipamento.equipamento_id)
        .where(Passagem.portal_id.in_(portais or [0]), Passagem.detectada_em >= inicio)
        .order_by(Passagem.detectada_em.desc(), Passagem.id.desc()).limit(limite)
    ).all()

    limiar = recency_threshold_from_env()
    equipamentos = db.execute(
        select(Equipamento.id, Equipamento.nome, Equipamento.ultima_zona_id,
               Equipamento.ultima_deteccao_em, TipoEquipamento.nome.label("tipo"),
               Tag.epc)
        .join(TipoEquipamento, TipoEquipamento.id == Equipamento.tipo_id)
        .outerjoin(AssociacaoTagEquipamento, and_(
            AssociacaoTagEquipamento.equipamento_id == Equipamento.id,
            AssociacaoTagEquipamento.fim.is_(None)))
        .outerjoin(Tag, Tag.id == AssociacaoTagEquipamento.tag_id)
        .where(Equipamento.ultima_zona_id.in_(list(zonas) or [0]),
               Equipamento.status == "ativo")
        .order_by(Equipamento.nome, Equipamento.id)
    ).all()
    por_zona: dict[str, list] = {chave: [] for chave in zonas.values()}
    for linha in equipamentos:
        por_zona[zonas[linha.ultima_zona_id]].append({
            "id": linha.id, "nome": linha.nome, "tipo": linha.tipo, "epc": linha.epc,
            "ultima_deteccao_em": em_utc(linha.ultima_deteccao_em),
            "estado_recencia": classify_recency(linha.ultima_deteccao_em, now, limiar),
        })

    estado_leitores = []
    for chave, leitor_id in leitores.items():
        leitor = db.get(Leitor, leitor_id)
        if leitor is None:
            continue
        estado_leitores.append({
            "chave": chave, "reader_id": leitor.reader_id, "modelo": leitor.modelo,
            "status": classify(leitor.ultimo_contato_em, leitor.saude_reportada, now, policy)[0],
            "ultimo_contato_em": em_utc(leitor.ultimo_contato_em),
            "leituras_sessao": db.scalar(
                select(func.count()).select_from(LeituraBruta)
                .join(Antena, Antena.id == LeituraBruta.antena_id)
                .where(Antena.leitor_id == leitor_id, LeituraBruta.lido_em >= inicio)) or 0,
        })

    return {
        "gerado_em": em_utc(now),
        "leituras_total": total_leituras,
        "leituras": [{
            "id": linha.id, "epc": linha.epc, "reader_id": linha.reader_id,
            "porta": linha.porta_numero, "antena": antenas.get(linha.antena_id),
            "lido_em": em_utc(linha.lido_em),
            "rssi": float(linha.rssi) if linha.rssi is not None else None,
            "equipamento": ({"id": linha.equipamento_id, "nome": linha.equipamento}
                            if linha.equipamento_id else None),
        } for linha in leituras],
        "tags": [{
            "epc": linha.epc, "leituras": linha.leituras, "ultima_leitura_em": em_utc(linha.ultima),
            "recente": linha.ultima >= now - timedelta(seconds=30),
            "equipamento": ({"id": linha.equipamento_id, "nome": linha.equipamento}
                            if linha.equipamento_id else None),
        } for linha in epcs_sessao],
        "passagens": [{
            "id": linha.id, "epc": linha.epc, "portal": linha.portal,
            "direcao": linha.direcao, "direcao_status": linha.direcao_status,
            "zona_origem": linha.zona_origem, "zona_destino": linha.zona_destino,
            "detectada_em": em_utc(linha.detectada_em), "equipamento": linha.equipamento,
        } for linha in passagens],
        "zonas": por_zona,
        "leitores": estado_leitores,
    }
