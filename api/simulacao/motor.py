"""Motor do simulador web: transforma posições virtuais em leituras MQTT.

Roda numa thread do processo da API (só quando `SIMULADOR_HABILITADO=true`).
A cada ciclo lê as sessões em execução no banco, calcula quais antenas
alcançam cada item etiquetado e publica, no máximo, uma leitura por item e
antena a cada `periodo_leitura_s` — o mesmo ritmo do simulador Flet anterior.

Daí em diante é o pipeline real: broker → ingestor → `leituras_brutas` →
debounce → passagem → direção → histórico/última zona. O motor não escreve em
nenhuma tabela do pipeline.

Com vários workers da API, só um publica: o que obtém o advisory lock do
PostgreSQL. As estatísticas expostas à interface são as deste processo.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from api.logging_config import registrar_evento

from . import relogio as relogio_sim
from . import trajeto
from .config import ConfigSimulador
from .geometria import AntenaVirtual, antenas_do_layout, detectar
from .publicador import PublicadorMultiLeitor

logger = logging.getLogger("api.simulacao")
CHAVE_LOCK = 7_340_401  # advisory lock exclusivo do motor de simulação
OCIOSO_S = 60.0


@dataclass
class EstadoSessao:
    """Runtime de uma sessão em execução neste processo."""

    sessao_id: int
    codigo: str
    versao: int
    portal_segmento: str
    proporcao: float
    antenas: list[AntenaVirtual]
    topicos: dict[str, str]
    itens: list[dict]
    ultima_leitura: dict[tuple[str, str], float] = field(default_factory=dict)
    no_alcance: dict[str, list[str]] = field(default_factory=dict)
    ultima_deteccao: dict[str, str] = field(default_factory=dict)
    publicadas: int = 0
    erro_topologia: str | None = None
    # Último instante simulado já avaliado e, por item/antena, a leitura mais
    # recente ainda não publicada (o período limita a taxa, não o que foi visto).
    sim_avaliado: datetime | None = None
    pendentes: dict[tuple[str, str], tuple[datetime, AntenaVirtual, int, str]] = field(
        default_factory=dict)

    def devidas(self, agora: float, periodo: float, sim_agora: datetime | None = None,
                ) -> list[tuple[str, str, int, int, str, str | None]]:
        """Leituras a publicar agora: (tópico, EPC, porta, RSSI, reader_id, lido_em).

        Em trajeto, avalia vários instantes entre o ciclo anterior e este (no
        relógio da simulação), para não pular antena em movimento rápido nem
        com o tempo acelerado; cada leitura leva o instante em que a tag estava
        no alcance. Parado, avalia só o instante atual (como antes).

        Com ``sim_agora`` a leitura leva esse instante: duas antenas cruzadas no
        mesmo ciclo chegariam ao ingestor juntas e, pelo horário de recebimento,
        ficariam sem ordem (a passagem não seria confirmada).
        """
        fim = sim_agora or relogio_sim.real_agora()
        inicio = self.sim_avaliado if self.sim_avaliado and self.sim_avaliado < fim else fim
        self.sim_avaliado = fim
        self.no_alcance = {}
        vivos = set()
        for item in self.itens:
            alcance = []
            for instante, x, y in trajeto.amostras(item, inicio, fim):
                alcance = detectar(x, y, self.antenas, self.proporcao)
                if item.get("epc"):  # sem etiqueta: está no alcance, mas não há o que ler
                    for antena, valor in alcance:
                        self.pendentes[(item["id"], antena.chave)] = (instante, antena, valor,
                                                                       item["epc"])
            if item.get("epc"):
                vivos.add((item["id"], item["epc"]))
            if alcance:
                self.no_alcance[item["id"]] = [antena.chave for antena, _ in alcance]
        saida = []
        for chave, (instante, antena, valor, epc) in sorted(self.pendentes.items(),
                                                            key=lambda par: par[1][0]):
            if (chave[0], epc) not in vivos:
                del self.pendentes[chave]  # item removido ou etiqueta trocada
                continue
            anterior = self.ultima_leitura.get(chave)
            # Tolerância: o ciclo não cai exatamente no período.
            if anterior is None or agora - anterior >= periodo - 0.01:
                del self.pendentes[chave]
                self.ultima_leitura[chave] = agora
                self.ultima_deteccao[chave[0]] = instante.isoformat()
                saida.append((self.topicos[antena.reader_id], epc, antena.porta, valor,
                              antena.reader_id, instante.isoformat() if sim_agora else None))
        return saida

    def publico(self) -> dict:
        """Estado para a interface (sem credenciais)."""
        return {"publicadas": self.publicadas, "no_alcance": self.no_alcance,
                "ultima_deteccao": self.ultima_deteccao, "erro": self.erro_topologia}


class MotorSimulacao:
    """Thread única que publica as leituras de todas as sessões em execução."""

    def __init__(self, config: ConfigSimulador, engine: Engine,
                 fabrica_publicador=PublicadorMultiLeitor) -> None:
        """Não conecta nada ainda: a conexão MQTT abre com a primeira sessão ativa."""
        self.config = config
        self.engine = engine
        self._fabrica = fabrica_publicador
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_conexao: Connection | None = None
        self._publicador: PublicadorMultiLeitor | None = None
        self._sessoes: dict[int, EstadoSessao] = {}
        self._ocioso_desde: float | None = None
        self._mutex = threading.Lock()
        self.erro: str | None = None
        self.lider = False
        self.conectado = False

    # --- ciclo de vida ---------------------------------------------------------

    def iniciar(self) -> None:
        """Inicia a thread daemon do motor."""
        self._thread = threading.Thread(target=self._executar, name="simulador-web", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        """Sinaliza parada e libera MQTT e o advisory lock."""
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._fechar_publicador()
        self._liberar_lock()

    def _executar(self) -> None:
        """Laço principal; falhas viram `erro` visível e nova tentativa com espera."""
        espera = 1.0
        while not self._parar.is_set():
            try:
                if not self._garantir_lock():
                    self._parar.wait(2.0)
                    continue
                self.ciclo(time.monotonic())
                self.erro = None
                espera = 1.0
                self._parar.wait(self.config.tick_s)
            except Exception as erro:  # noqa: BLE001 - o motor nunca derruba a API
                self.erro = str(erro)[:300]
                registrar_evento(logger, "simulador_falha", erro=self.erro)
                self._fechar_publicador()
                self._parar.wait(espera)
                espera = min(espera * 2, 15.0)

    def _garantir_lock(self) -> bool:
        """Advisory lock de sessão em conexão dedicada: um único motor publica."""
        if self._lock_conexao is not None and not self._lock_conexao.closed:
            return True
        conexao = self.engine.connect()
        obtido = conexao.execute(text("SELECT pg_try_advisory_lock(:chave)"),
                                 {"chave": CHAVE_LOCK}).scalar()
        conexao.commit()
        if not obtido:
            conexao.close()
            self.lider = False
            return False
        self._lock_conexao = conexao
        self.lider = True
        return True

    def _liberar_lock(self) -> None:
        """Fecha a conexão do lock (o PostgreSQL o libera junto)."""
        conexao, self._lock_conexao = self._lock_conexao, None
        if conexao is not None:
            try:
                conexao.close()
            except Exception:  # noqa: BLE001 - encerramento
                pass
        self.lider = False

    def _fechar_publicador(self) -> None:
        """Desconecta do broker."""
        publicador, self._publicador = self._publicador, None
        self.conectado = False
        if publicador is not None:
            try:
                publicador.fechar()
            except OSError:
                pass

    # --- ciclo -------------------------------------------------------------------

    def _carregar(self) -> list[EstadoSessao]:
        """Sessões em execução; relê a linha inteira só quando a versão muda."""
        with self.engine.connect() as conexao:
            versoes = dict(conexao.execute(text(
                "SELECT id, versao FROM simulacao_sessoes WHERE estado = 'em_execucao'")).all())
            mudadas = [sessao_id for sessao_id, versao in versoes.items()
                       if sessao_id not in self._sessoes
                       or self._sessoes[sessao_id].versao != versao]
            linhas = conexao.execute(text(
                "SELECT id, codigo, versao, layout_id, layout, itens FROM simulacao_sessoes "
                "WHERE id = ANY(:ids)"), {"ids": mudadas}).all() if mudadas else []
        with self._mutex:
            for sessao_id in list(self._sessoes):
                if sessao_id not in versoes:
                    del self._sessoes[sessao_id]
            for linha in linhas:
                anterior = self._sessoes.get(linha.id)
                estado = EstadoSessao(
                    linha.id, linha.codigo, linha.versao, f"sim-l{linha.layout_id}",
                    float(linha.layout["proporcao"]), antenas_do_layout(linha.layout), {},
                    list(linha.itens))
                if anterior is not None:
                    estado.ultima_leitura = anterior.ultima_leitura
                    estado.ultima_deteccao = anterior.ultima_deteccao
                    estado.publicadas = anterior.publicadas
                    estado.sim_avaliado = anterior.sim_avaliado
                    estado.pendentes = anterior.pendentes
                self._sessoes[linha.id] = estado
            return list(self._sessoes.values())

    def _relogio(self) -> datetime:
        """Instante simulado deste ciclo (o mesmo que API e telas usam)."""
        real = relogio_sim.real_agora()
        with Session(self.engine) as db:
            return relogio_sim.do_banco(db, real).agora(real)

    def ciclo(self, agora: float) -> None:
        """Um passo: carrega sessões, publica o que é devido, confere PUBACKs."""
        sessoes = self._carregar()
        if not sessoes:
            if self._publicador is not None:
                self._ocioso_desde = self._ocioso_desde or agora
                if agora - self._ocioso_desde > OCIOSO_S:
                    self._fechar_publicador()
            return
        self._ocioso_desde = None
        if self._publicador is None:
            publicador = self._fabrica(self.config.mqtt, assinatura=self.config.assinatura,
                                       permitido=self.config.topico_permitido,
                                       relay=self.config.topico_relay)
            publicador.conectar()
            self._publicador = publicador
            self.conectado = True
            registrar_evento(logger, "simulador_conectado", destino=publicador.destino)
        sim_agora = self._relogio()
        for sessao in sessoes:
            try:
                for antena in sessao.antenas:
                    if antena.reader_id not in sessao.topicos:
                        sessao.topicos[antena.reader_id] = self._publicador.topico(
                            antena.reader_id, sessao.portal_segmento)
                sessao.erro_topologia = None
            except ValueError as erro:
                sessao.erro_topologia = str(erro)
                continue
            for topico, epc, porta, rssi, reader_id, lido_em in sessao.devidas(
                    agora, self.config.periodo_leitura_s, sim_agora):
                self._publicador.emitir(topico, epc, porta, rssi, reader_id, lido_em)
                sessao.publicadas += 1
        self._publicador.conferir()

    # --- consulta ----------------------------------------------------------------

    def estado(self, sessao_id: int | None = None) -> dict:
        """Estado do motor (e da sessão pedida) para a interface."""
        with self._mutex:
            sessao = self._sessoes.get(sessao_id) if sessao_id is not None else None
            return {
                "ativo": self._thread is not None and self._thread.is_alive(),
                "lider": self.lider, "conectado": self.conectado, "erro": self.erro,
                "destino": self._publicador.destino if self._publicador else None,
                "pendentes": self._publicador.pendentes if self._publicador else 0,
                "sessao": sessao.publico() if sessao else None,
            }


_MOTOR: MotorSimulacao | None = None


def iniciar_motor(config: ConfigSimulador, engine: Engine) -> MotorSimulacao | None:
    """Sobe o motor uma vez por processo, se o simulador estiver habilitado."""
    global _MOTOR
    if not config.habilitado:
        return None
    if _MOTOR is None:
        _MOTOR = MotorSimulacao(config, engine)
        _MOTOR.iniciar()
    return _MOTOR


def parar_motor() -> None:
    """Para o motor deste processo, se houver."""
    global _MOTOR
    if _MOTOR is not None:
        _MOTOR.parar()
        _MOTOR = None


def motor_atual() -> MotorSimulacao | None:
    """Motor deste processo (None se desabilitado)."""
    return _MOTOR
