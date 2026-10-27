"""Simulador web: layouts da planta, sessões compartilhadas e monitoramento.

Consulta exige `simulacao:consultar`; criar/editar layout, iniciar sessão e
mover itens exigem `simulacao:alterar` (administrador). Com o simulador
desabilitado (padrão) ou em `APP_ENV=production`, nenhuma sessão é iniciada
e nada é publicado — layouts podem ser editados fora de produção.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo
from api.service_auth import SessaoAutenticada
from api.simulacao import cenario_demo, service
from api.simulacao import config as config_simulador
from api.simulacao import relogio as relogio_sim
from api.simulacao.esquema import MAX_ANTENAS_POR_LEITOR, MODELOS_LEITOR
from api.simulacao.motor import motor_atual
from api.simulacao.presets import NOMES_PRESET

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.SIMULACAO_CONSULTAR, alterar=Permissao.SIMULACAO_ALTERAR
)
router = APIRouter(prefix="/api/simulacao", tags=["simulador"])


def obter_config() -> config_simulador.ConfigSimulador:
    """Configuração lida do ambiente do servidor (substituível nos testes)."""
    return config_simulador.carregar()


def _relogio(db: Session = Depends(get_db)) -> datetime:
    """Instante da requisição no relógio da simulação (acelerado/adiantado ou real)."""
    real = relogio_sim.real_agora()
    return relogio_sim.do_banco(db, real).agora(real)


def _traduzir(erro: service.SimulacaoRecusada) -> HTTPException:
    """Erro de domínio vira status + corpo com código estável."""
    return HTTPException(erro.status, detail={"codigo": erro.codigo, "mensagem": str(erro)})


def _fora_de_producao(config: config_simulador.ConfigSimulador) -> None:
    """Em produção o simulador inteiro fica indisponível."""
    if config.ambiente == "production":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={
            "codigo": "simulador_indisponivel", "mensagem": "simulador indisponível em produção"})


def _exigir_habilitado(config: config_simulador.ConfigSimulador) -> None:
    """Sessão só começa com o simulador habilitado neste servidor."""
    _fora_de_producao(config)
    if not config.habilitado:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "codigo": "simulador_desabilitado", "mensagem": config.motivo})


class LayoutCriar(BaseModel):
    """Novo layout: do preset (sem configuração) ou de uma configuração enviada."""

    nome: str | None = Field(None, max_length=120)
    cenario: str = Field(..., pattern="^(easy|hupaa)$")
    configuracao: dict | None = None


class LayoutSalvar(BaseModel):
    """Edição completa do layout com a versão que a aba carregou."""

    nome: str | None = Field(None, max_length=120)
    configuracao: dict
    versao: int = Field(..., ge=1)


class SessaoCriar(BaseModel):
    """Iniciar simulação de um layout."""

    layout_id: int = Field(..., ge=1)


class CenarioEscolhido(BaseModel):
    """Cenário alvo de uma ação de atalho (teste rápido, apagar tudo)."""

    cenario: str = Field(..., pattern="^(easy|hupaa)$")


class ItemCriar(BaseModel):
    """Equipamento virtual: EPC informado, gerado (`gerar_epc`) ou nenhum (sem etiqueta)."""

    nome: str = Field(..., min_length=1, max_length=80)
    tipo: str | None = Field(None, max_length=60)
    epc: str | None = Field(None, max_length=64)
    gerar_epc: bool = False
    x: float | None = Field(None, ge=0, le=100)
    y: float | None = Field(None, ge=0, le=100)


class PontoTrajeto(BaseModel):
    """Ponto do desenho: posição na planta e segundos desde o início do gesto."""

    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)
    t: float = Field(..., ge=0)


class TrajetoCriar(BaseModel):
    """Trajeto desenhado, enviado só ao soltar o botão."""

    pontos: list[PontoTrajeto] = Field(..., min_length=2, max_length=4000)


class RelogioAlterar(BaseModel):
    """Acelerar (fator) e/ou avançar o tempo simulado."""

    fator: float | None = None
    avancar_s: float = Field(0, ge=0)


class ItemAlterar(BaseModel):
    """Movimento e edição de item; campos ausentes ficam como estão."""

    x: float | None = Field(None, ge=0, le=100)
    y: float | None = Field(None, ge=0, le=100)
    nome: str | None = Field(None, max_length=80)
    tipo: str | None = Field(None, max_length=60)
    epc: str | None = Field(None, max_length=64)
    gerar_epc: bool = False
    remover_epc: bool = False


def _estado_motor(sessao_id: int | None = None) -> dict | None:
    """Estatísticas do motor deste processo (None se desabilitado aqui)."""
    motor = motor_atual()
    return motor.estado(sessao_id) if motor is not None else None


def _resposta_sessao(sessao) -> dict:
    """Sessão completa + motor."""
    return {**service.resumo_sessao(sessao), "motor": _estado_motor(sessao.id)}


@router.get("/config", dependencies=[Depends(_PERMISSAO)], summary="Estado do simulador")
def configuracao(config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Habilitação, ambiente, modelos de leitor e cenários disponíveis."""
    return {
        **config.publico(),
        "max_antenas_por_leitor": MAX_ANTENAS_POR_LEITOR,
        "modelos_leitor": [{"id": chave, **valor} for chave, valor in MODELOS_LEITOR.items()],
        "cenarios": [{"id": chave, "nome": nome} for chave, nome in NOMES_PRESET.items()],
        "motor": _estado_motor(),
    }


@router.get("/layouts", dependencies=[Depends(_PERMISSAO)], summary="Layouts salvos")
def listar_layouts(cenario: str | None = Query(None, pattern="^(easy|hupaa)$"),
                   db: Session = Depends(get_db)) -> list[dict]:
    """Layouts não arquivados do cenário."""
    return [service.resumo_layout(item) for item in service.listar_layouts(db, cenario)]


@router.post("/layouts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(_PERMISSAO)],
             summary="Criar layout")
def criar_layout(payload: LayoutCriar, db: Session = Depends(get_db),
                 config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Cria a partir do preset do cenário ou da configuração enviada."""
    _fora_de_producao(config)
    try:
        registro = service.criar_layout(db, nome=payload.nome, cenario=payload.cenario,
                                        configuracao=payload.configuracao)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return service.resumo_layout(registro)


@router.get("/layouts/{layout_id}", dependencies=[Depends(_PERMISSAO)], summary="Detalhar layout")
def obter_layout(layout_id: int, db: Session = Depends(get_db)) -> dict:
    """Layout completo com avisos."""
    try:
        return service.resumo_layout(service.obter_layout(db, layout_id))
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.put("/layouts/{layout_id}", dependencies=[Depends(_PERMISSAO)], summary="Salvar layout")
def salvar_layout(layout_id: int, payload: LayoutSalvar, db: Session = Depends(get_db),
                  config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Valida e salva; 409 se outra aba salvou antes."""
    _fora_de_producao(config)
    try:
        registro = service.atualizar_layout(db, layout_id, nome=payload.nome,
                                            configuracao=payload.configuracao,
                                            versao_esperada=payload.versao)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return service.resumo_layout(registro)


class RotuloZona(BaseModel):
    """Posição do nome da zona na planta (0–100)."""

    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)


@router.put("/layouts/{layout_id}/zonas/{chave}/rotulo", dependencies=[Depends(_PERMISSAO)],
            summary="Mover o nome da zona no mapa")
def mover_rotulo(layout_id: int, chave: str, payload: RotuloZona, db: Session = Depends(get_db),
                 config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Grava a posição do nome no layout compartilhado (não altera os limites da zona)."""
    _fora_de_producao(config)
    try:
        return service.resumo_layout(service.mover_rotulo(db, layout_id, chave, payload.x, payload.y))
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.post("/layouts/{layout_id}/restaurar-preset", dependencies=[Depends(_PERMISSAO)],
             summary="Restaurar configuração predefinida")
def restaurar(layout_id: int, db: Session = Depends(get_db),
              config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Volta o layout ao preset do cenário."""
    _fora_de_producao(config)
    try:
        return service.resumo_layout(service.restaurar_preset(db, layout_id))
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.delete("/layouts/{layout_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(_PERMISSAO)], summary="Arquivar layout")
def arquivar(layout_id: int, db: Session = Depends(get_db)) -> None:
    """Arquiva o layout (sem apagar sessões nem topologia já usada)."""
    try:
        service.arquivar_layout(db, layout_id)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.get("/sessoes", dependencies=[Depends(_PERMISSAO)], summary="Sessões de simulação")
def listar_sessoes(abertas: bool = Query(True), db: Session = Depends(get_db)) -> list[dict]:
    """Sessões abertas (padrão) ou as últimas sessões."""
    return [{key: valor for key, valor in service.resumo_sessao(sessao).items()
             if key not in ("layout", "itens")} | {"itens": len(sessao.itens)}
            for sessao in service.listar_sessoes(db, abertas=abertas)]


@router.post("/sessoes", status_code=status.HTTP_201_CREATED, summary="Iniciar simulação")
def iniciar(payload: SessaoCriar, db: Session = Depends(get_db),
            sessao_auth: SessaoAutenticada = Depends(_PERMISSAO),
            config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Aplica a topologia do layout e devolve a sessão com o código do link de controle."""
    _exigir_habilitado(config)
    try:
        usuario = sessao_auth.usuario.id or None
        # O layout padrão do HU é o das apresentações: iniciar monta o cenário de demonstração.
        sessao = (cenario_demo.iniciar(db, usuario) if cenario_demo.e_layout_padrao(db, payload.layout_id)
                  else service.iniciar_sessao(db, payload.layout_id, usuario))
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return _resposta_sessao(sessao)


@router.post("/teste-rapido", status_code=status.HTTP_201_CREATED,
             summary="Layout pronto, sessão iniciada e equipamentos de demonstração")
def teste_rapido(payload: CenarioEscolhido, db: Session = Depends(get_db),
                 sessao_auth: SessaoAutenticada = Depends(_PERMISSAO),
                 config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Um clique para testar: reaproveita o layout do teste rápido ou cria um."""
    _exigir_habilitado(config)
    try:
        sessao = service.teste_rapido(db, payload.cenario, sessao_auth.usuario.id or None)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return _resposta_sessao(sessao)


@router.post("/apagar-tudo", dependencies=[Depends(_PERMISSAO)],
             summary="Encerrar sessões e arquivar todos os layouts do cenário")
def apagar_tudo(payload: CenarioEscolhido, db: Session = Depends(get_db),
                config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Recomeça o cenário do zero; dados do pipeline ficam (ver tools.limpeza_banco)."""
    _fora_de_producao(config)
    return service.apagar_cenario(db, payload.cenario)


@router.get("/sessoes/{codigo}", dependencies=[Depends(_PERMISSAO)], summary="Estado da sessão")
def obter_sessao(codigo: str, desde_versao: int | None = Query(None, ge=0),
                 db: Session = Depends(get_db)) -> dict:
    """Estado compartilhado; com `desde_versao` igual à atual, devolve só o motor."""
    try:
        sessao = service.obter_sessao(db, codigo)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    if desde_versao is not None and desde_versao == sessao.versao:
        return {"codigo": sessao.codigo, "versao": sessao.versao, "estado": sessao.estado,
                "inalterada": True, "motor": _estado_motor(sessao.id)}
    return _resposta_sessao(sessao)


@router.post("/sessoes/{codigo}/itens", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(_PERMISSAO)], summary="Adicionar equipamento virtual")
def adicionar_item(codigo: str, payload: ItemCriar, db: Session = Depends(get_db)) -> dict:
    """Item com EPC (etiquetado), EPC gerado ou sem etiqueta."""
    try:
        sessao = service.adicionar_item(db, codigo, nome=payload.nome, tipo=payload.tipo,
                                        epc=payload.epc, gerar_epc=payload.gerar_epc,
                                        x=payload.x, y=payload.y)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return _resposta_sessao(sessao)


@router.patch("/sessoes/{codigo}/itens/{item_id}", dependencies=[Depends(_PERMISSAO)],
              summary="Mover ou editar equipamento virtual")
def alterar_item(codigo: str, item_id: str, payload: ItemAlterar,
                 db: Session = Depends(get_db)) -> dict:
    """Arrastar envia só x/y; etiquetar envia `epc` ou `gerar_epc`."""
    try:
        sessao = service.alterar_item(db, codigo, item_id, payload.model_dump(exclude_unset=True))
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return {"codigo": sessao.codigo, "versao": sessao.versao, "itens": sessao.itens}


@router.delete("/sessoes/{codigo}/itens", dependencies=[Depends(_PERMISSAO)],
               summary="Remover todos os equipamentos virtuais")
def limpar_itens(codigo: str, db: Session = Depends(get_db)) -> dict:
    """Esvazia a planta da sessão (cadastros no banco não mudam)."""
    try:
        sessao = service.limpar_itens(db, codigo)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return {"codigo": sessao.codigo, "versao": sessao.versao, "itens": sessao.itens}


@router.delete("/sessoes/{codigo}/itens/{item_id}", dependencies=[Depends(_PERMISSAO)],
               summary="Remover equipamento virtual")
def remover_item(codigo: str, item_id: str, db: Session = Depends(get_db)) -> dict:
    """Retira o item da planta virtual."""
    try:
        sessao = service.remover_item(db, codigo, item_id)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return {"codigo": sessao.codigo, "versao": sessao.versao, "itens": sessao.itens}


@router.post("/sessoes/{codigo}/itens/{item_id}/trajeto", dependencies=[Depends(_PERMISSAO)],
             summary="Executar o trajeto desenhado")
def executar_trajeto(codigo: str, item_id: str, payload: TrajetoCriar,
                     db: Session = Depends(get_db),
                     config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Só a execução gera leituras; o desenho em si nunca chega ao motor."""
    _exigir_habilitado(config)
    try:
        sessao = service.executar_trajeto(db, codigo, item_id,
                                          [ponto.model_dump() for ponto in payload.pontos])
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return {"codigo": sessao.codigo, "versao": sessao.versao, "itens": sessao.itens,
            "relogio": relogio_sim.resumo(relogio_sim.do_banco(db))}


@router.get("/demo-hu", dependencies=[Depends(_PERMISSAO)], summary="Cenário de demonstração do HU")
def demo_hu(db: Session = Depends(get_db)) -> dict:
    """Quantos equipamentos do cenário existem e se ele está em execução."""
    try:
        return cenario_demo.estado(db)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.post("/demo-hu/preparar", dependencies=[Depends(_PERMISSAO)],
             summary="Voltar ao início: seis equipamentos antigos, nada em execução")
def preparar_demo_hu(db: Session = Depends(get_db),
                     config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Antes da apresentação: o dashboard passa a mostrar os seis equipamentos parados."""
    _fora_de_producao(config)
    try:
        return cenario_demo.preparar(db)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.get("/relogio", dependencies=[Depends(_PERMISSAO)], summary="Relógio da simulação")
def ler_relogio(db: Session = Depends(get_db)) -> dict:
    """O mesmo tempo para simulador e dashboard (o relógio do computador não muda)."""
    return relogio_sim.resumo(relogio_sim.do_banco(db))


@router.post("/relogio", dependencies=[Depends(_PERMISSAO)], summary="Acelerar ou avançar o tempo")
def alterar_relogio(payload: RelogioAlterar, db: Session = Depends(get_db),
                    config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Muda o estado real da simulação: leituras, recência e alertas seguem o novo tempo."""
    _exigir_habilitado(config)
    try:
        return service.definir_relogio(db, fator=payload.fator, avancar_s=payload.avancar_s)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro


@router.post("/sessoes/{codigo}/{acao}", dependencies=[Depends(_PERMISSAO)],
             summary="Pausar, retomar, reiniciar ou encerrar")
def transicionar(codigo: str, acao: str, db: Session = Depends(get_db),
                 config: config_simulador.ConfigSimulador = Depends(obter_config)) -> dict:
    """Controle de execução compartilhado pelas duas interfaces."""
    if acao not in ("pausar", "retomar", "reiniciar", "encerrar"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ação desconhecida")
    if acao in ("retomar", "reiniciar"):
        _exigir_habilitado(config)
    try:
        atual = service.obter_sessao(db, codigo)
        sessao = (cenario_demo.reiniciar(db, codigo)
                  if acao == "reiniciar" and cenario_demo.e_layout_padrao(db, atual.layout_id)
                  else service.transicionar(db, codigo, acao))
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return _resposta_sessao(sessao)


@router.get("/sessoes/{codigo}/monitor", dependencies=[Depends(_PERMISSAO)],
            summary="O que o pipeline RFID registrou nesta sessão")
def monitorar(codigo: str, db: Session = Depends(get_db),
              agora: datetime = Depends(_relogio)) -> dict:
    """Leituras, tags, passagens, leitores e equipamentos por zona confirmada."""
    try:
        sessao = service.obter_sessao(db, codigo)
    except service.SimulacaoRecusada as erro:
        raise _traduzir(erro) from erro
    return {**service.monitor(db, sessao, now=agora),
            "relogio": relogio_sim.resumo(relogio_sim.do_banco(db))}
