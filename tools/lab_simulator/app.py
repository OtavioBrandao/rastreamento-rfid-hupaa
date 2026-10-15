"""Interface Flet do simulador visual do laboratório EASY."""

from __future__ import annotations

import asyncio
import queue
import random
import threading
import time
from collections.abc import Callable

import flet as ft

from . import modelo
from .modelo import ANTENAS, Item

LARGURA = 880
ALTURA = round(LARGURA * modelo.PROPORCAO_Y)
SX = LARGURA / 100
SY = ALTURA / 100
ITEM_DIAMETRO = 30
ITEM_CAIXA = 96
PULSO_S = 0.35
TICK_S = 0.1

COR_PAREDE = "#263a41"
COR_BANCADA = "#b6c9c9"
COR_ALCANCE = "#1f8a70"
COR_ITEM = "#2f6fb2"
COR_ITEM_LIDO = "#1f8a70"


class Envio:
    """Fila consumida por uma thread própria; a interface nunca espera o broker."""

    def __init__(self, publicador) -> None:
        """Inicializa Envio com as dependências e valores recebidos."""
        self.publicador = publicador
        self.fila: queue.Queue[tuple[str, int, int]] = queue.Queue()
        self.erro: str | None = None
        self.conectado = False
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._executar, daemon=True)

    def iniciar(self) -> None:
        """Inicia a thread de publicação que mantém a interface livre de esperas MQTT."""
        self._thread.start()

    def parar(self) -> None:
        """Sinaliza parada da thread de envio e fecha a conexão do publicador."""
        self._parar.set()
        self._thread.join(timeout=5)

    def _executar(self) -> None:
        """Executa operação administrativa e traduz erros de usuário para HTTP."""
        try:
            self.publicador.conectar()
            self.conectado = True
            while not self._parar.is_set():
                try:
                    leitura = self.fila.get(timeout=0.2)
                except queue.Empty:
                    self.publicador.conferir()
                    continue
                self.publicador.emitir(*leitura)
        except (OSError, RuntimeError, ValueError) as erro:
            self.erro = str(erro)
        finally:
            self.conectado = False
            try:
                self.publicador.fechar()
            except OSError:
                pass


def _linha(x1: float, y1: float, x2: float, y2: float, cor: str = COR_PAREDE,
           espessura: float = 2) -> ft.Container:
    """Cria elemento de linha da planta na interface do simulador."""
    return ft.Container(left=x1 * SX - espessura / 2, top=y1 * SY - espessura / 2,
                        width=max((x2 - x1) * SX, 0) + espessura,
                        height=max((y2 - y1) * SY, 0) + espessura, bgcolor=cor)


def _rotulo(texto: str, x: float, y: float, tamanho: int = 15, largura: int = 260
            ) -> ft.Container:
    """Cria rótulo de identificação na planta do simulador."""
    return ft.Container(
        left=x * SX - largura / 2, top=y * SY - tamanho, width=largura,
        content=ft.Text(texto, size=tamanho, weight=ft.FontWeight.BOLD, color="#6b7f86",
                        text_align=ft.TextAlign.CENTER))


def _planta() -> list[ft.Control]:
    """Mesmo esquema do FloorMap (modo lab): salas A/B, divisória e área comum."""
    controles: list[ft.Control] = [
        ft.Container(left=1 * SX, top=5 * SY, width=98 * SX, height=90 * SY,
                     bgcolor="#ffffff", border=ft.Border.all(2, COR_PAREDE),
                     border_radius=4),
        _linha(50, 5, 50, 65),
        _linha(1, 65, 13, 65), _linha(24, 65, 88, 65), _linha(94, 65, 99, 65),
        *(_linha(x, 13, x, 55, COR_BANCADA, 5) for x in (9, 41, 59, 91)),
        ft.Container(left=3 * SX, top=74 * SY, width=7 * SX, height=17 * SY,
                     bgcolor="#eef3f3", border=ft.Border.all(1, "#aebdbf")),
        ft.Container(left=89 * SX, top=69 * SY, width=7 * SX, height=12 * SY,
                     bgcolor="#eef3f3", border=ft.Border.all(1, "#aebdbf")),
        _rotulo("SALA A", 25, 38, 20), _rotulo("SALA B", 75, 38, 20),
        _rotulo("ÁREA COMUM / PORTAL DE TESTES", 50, 90, 13, 360),
    ]
    return controles


def _marcador(x: float, y: float, icone, cor: str, legenda: str) -> ft.Container:
    """Cria marcador visual de antena ou equipamento na planta do simulador."""
    return ft.Container(
        left=x * SX - 40, top=y * SY - 14, width=80,
        content=ft.Column([ft.Icon(icone, color=cor, size=26),
                           ft.Text(legenda, size=11, color=cor, weight=ft.FontWeight.BOLD,
                                   text_align=ft.TextAlign.CENTER)],
                          spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER))


class Simulador:
    """Coordena controles Flet, equipamentos arrastáveis, alcance ilustrativo e publicação MQTT."""
    def __init__(self, page: ft.Page, envio: Envio,
                 cadastrar: Callable[[list[Item]], dict[str, str]],
                 destino: str) -> None:
        """Inicializa Simulador com as dependências e valores recebidos."""
        self.page = page
        self.envio = envio
        self.cadastrar = cadastrar
        self.destino = destino
        self.rng = random.Random()
        self.itens: list[Item] = []
        self.visuais: dict[str, tuple[ft.GestureDetector, ft.Container]] = {}
        self.pulso_ate: dict[int, float] = {}
        self.no_alcance: set[tuple[str, int]] = set()
        self.contagem = {antena.porta: 0 for antena in ANTENAS}

        self.alcances = {
            antena.porta: ft.Container(
                left=antena.x * SX - modelo.RAIO * SX, top=antena.y * SY - modelo.RAIO * SX,
                width=2 * modelo.RAIO * SX, height=2 * modelo.RAIO * SX,
                shape=ft.BoxShape.CIRCLE, bgcolor=ft.Colors.with_opacity(0.10, COR_ALCANCE),
                border=ft.Border.all(2, ft.Colors.with_opacity(0.45, COR_ALCANCE)),
                scale=1.0, animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT))
            for antena in ANTENAS
        }
        self.camada_itens = ft.Stack(width=LARGURA, height=ALTURA)
        self.mapa = ft.Stack(
            width=LARGURA, height=ALTURA,
            controls=[*_planta(), *self.alcances.values(),
                      *(_marcador(a.x, a.y, ft.Icons.SENSORS, COR_ALCANCE, a.nome)
                        for a in ANTENAS),
                      _marcador(*modelo.LEITOR, ft.Icons.ROUTER, "#4b5d63", "Leitor 01"),
                      _marcador(*modelo.PORTAL, ft.Icons.DOOR_SLIDING, "#8a5a1f", "Portal"),
                      self.camada_itens])

        self.quantidade = ft.TextField(label="Quantidade de itens", value="4", width=170,
                                       dense=True, keyboard_type=ft.KeyboardType.NUMBER,
                                       on_submit=lambda _e: self.definir_nomes())
        self.campos_nomes = ft.Column(spacing=6)
        self.botao_gerar = ft.FilledButton("Gerar itens no mapa", icon=ft.Icons.PLAY_ARROW,
                                           on_click=lambda _e: self.gerar())
        self.botao_sortear = ft.OutlinedButton("Novas posições", icon=ft.Icons.SHUFFLE,
                                               on_click=lambda _e: self.sortear(),
                                               disabled=True)
        self.mensagem = ft.Text("", size=12)
        self.estado = ft.Text("Conectando ao broker...", size=12)
        self.lista_itens = ft.Column(spacing=2)
        self.log = ft.ListView(height=200, spacing=2, auto_scroll=True)

    def montar(self) -> None:
        """Monta a janela Flet com planta, formulário de itens e indicadores da conexão."""
        painel = ft.Column(
            width=330, scroll=ft.ScrollMode.AUTO, spacing=10,
            controls=[
                ft.Text("Simulador do laboratório EASY", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(f"Destino: {self.destino}", size=11, color="#4b5d63"),
                self.estado,
                ft.Divider(),
                ft.Row([self.quantidade,
                        ft.OutlinedButton("Definir nomes",
                                          on_click=lambda _e: self.definir_nomes())]),
                self.campos_nomes,
                ft.Row([self.botao_gerar, self.botao_sortear], wrap=True),
                self.mensagem,
                ft.Divider(),
                ft.Text("Itens", weight=ft.FontWeight.BOLD), self.lista_itens,
                ft.Text("Eventos das antenas", weight=ft.FontWeight.BOLD), self.log,
                ft.Text("Arraste um item com o botão esquerdo. Dentro do círculo, a antena "
                        f"gera uma leitura a cada {modelo.PERIODO_LEITURA_S:g} s. Para "
                        "registrar passagem, saia do alcance de uma antena e entre no da "
                        "outra em até 3 s.", size=11, color="#4b5d63"),
            ])
        self.page.add(ft.Row([ft.Container(self.mapa, border_radius=6), painel],
                             vertical_alignment=ft.CrossAxisAlignment.START, spacing=16))
        self.definir_nomes()
        self.page.run_task(self.ciclo)

    def definir_nomes(self) -> None:
        """Cria campos de nome para a quantidade de equipamentos escolhida pelo operador."""
        try:
            total = int(self.quantidade.value or "0")
            if not 1 <= total <= modelo.MAX_ITENS:
                raise ValueError
        except ValueError:
            self._avisar(f"Quantidade deve ser de 1 a {modelo.MAX_ITENS}.", erro=True)
            return
        atuais = [campo.value for campo in self.campos_nomes.controls]
        self.campos_nomes.controls = [
            ft.TextField(label=f"Nome do item {indice + 1}", dense=True,
                         value=atuais[indice] if indice < len(atuais)
                         else f"Equipamento {indice + 1}")
            for indice in range(total)]
        self._avisar("")

    def gerar(self) -> None:
        """Valida nomes e inicia a geração/cadastro dos equipamentos sintéticos."""
        try:
            itens = modelo.criar_itens([c.value or "" for c in self.campos_nomes.controls],
                                       self.rng)
        except (ValueError, RuntimeError) as erro:
            self._avisar(str(erro), erro=True)
            return
        self.botao_gerar.disabled = True
        self._avisar("Cadastrando equipamentos e tags no banco...")
        self.page.run_thread(self._cadastrar_e_posicionar, itens)

    def _cadastrar_e_posicionar(self, itens: list[Item]) -> None:
        """Cadastra os EPCs no banco e cria seus marcadores em posições fora das antenas."""
        try:
            self.cadastrar(itens)
        except Exception as erro:  # noqa: BLE001 - falha de banco exibida ao usuário
            self.botao_gerar.disabled = False
            self._avisar(f"Falha no cadastro: {erro}", erro=True)
            return
        self.itens = itens
        self.no_alcance.clear()
        self.camada_itens.controls = [self._visual(item) for item in itens]
        self.lista_itens.controls = [
            ft.Text(f"{item.nome} · {item.epc}", size=11, selectable=True)
            for item in itens]
        self.botao_gerar.disabled = False
        self.botao_sortear.disabled = False
        self._registrar(f"{len(itens)} item(ns) cadastrado(s) e posicionado(s)")
        self._avisar("Itens prontos. Arraste-os até as antenas.")

    def sortear(self) -> None:
        """Redistribui os equipamentos em posições ilustrativas fora dos alcances de leitura."""
        for item, (x, y) in zip(self.itens,
                                modelo.posicoes_iniciais(len(self.itens), self.rng),
                                strict=True):
            item.x, item.y = x, y
            self._posicionar(item)
        self.page.update()

    def _visual(self, item: Item) -> ft.GestureDetector:
        """Monta o componente visual arrastável de um equipamento sintético."""
        bolinha = ft.Container(
            width=ITEM_DIAMETRO, height=ITEM_DIAMETRO, shape=ft.BoxShape.CIRCLE,
            bgcolor=COR_ITEM, border=ft.Border.all(3, "#ffffff"),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.MEDICAL_SERVICES, color="#ffffff", size=16),
            animate=ft.Animation(150))
        detector = ft.GestureDetector(
            width=ITEM_CAIXA, mouse_cursor=ft.MouseCursor.MOVE, drag_interval=16,
            on_pan_update=lambda e, alvo=item: self._arrastar(alvo, e),
            content=ft.Column(
                [bolinha, ft.Container(
                    bgcolor=ft.Colors.with_opacity(0.85, "#ffffff"), border_radius=4,
                    padding=ft.Padding.symmetric(horizontal=4),
                    content=ft.Text(item.nome, size=11, weight=ft.FontWeight.BOLD,
                                    text_align=ft.TextAlign.CENTER, no_wrap=True))],
                spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        self.visuais[item.epc] = (detector, bolinha)
        self._posicionar(item)
        return detector

    def _posicionar(self, item: Item) -> None:
        """Atualiza a posição do marcador conforme as coordenadas do item na planta."""
        detector, _ = self.visuais[item.epc]
        detector.left = item.x * SX - ITEM_CAIXA / 2
        detector.top = item.y * SY - ITEM_DIAMETRO / 2

    def _arrastar(self, item: Item, evento: ft.DragUpdateEvent) -> None:
        """Aplica o deslocamento do mouse ao item, respeitando os limites da planta."""
        delta = evento.local_delta
        if delta is None:
            return
        item.x, item.y = modelo.limitar(item.x + delta.x / SX, item.y + delta.y / SY)
        self._posicionar(item)
        self.visuais[item.epc][0].update()

    async def ciclo(self) -> None:
        """Avalia periodicamente itens no alcance, enfileira leituras e atualiza os indicadores visuais."""
        while True:
            agora = time.monotonic()
            for item, antena, valor in modelo.leituras_devidas(self.itens, agora):
                self.envio.fila.put((item.epc, antena.porta, valor))
                self.contagem[antena.porta] += 1
                self.pulso_ate[antena.porta] = agora + PULSO_S
            self._atualizar_alcances()
            for antena in ANTENAS:
                ativa = self.pulso_ate.get(antena.porta, 0) > agora
                alcance = self.alcances[antena.porta]
                alcance.scale = 1.06 if ativa else 1.0
                alcance.bgcolor = ft.Colors.with_opacity(0.32 if ativa else 0.10, COR_ALCANCE)
            self._atualizar_estado()
            self.page.update()
            await asyncio.sleep(TICK_S)

    def _atualizar_alcances(self) -> None:
        """Atualiza alcances."""
        atual = {(item.epc, antena.porta) for item in self.itens
                 for antena, _ in modelo.detectar(item.x, item.y)}
        nomes = {item.epc: item.nome for item in self.itens}
        antenas = {antena.porta: antena.nome for antena in ANTENAS}
        for epc, porta in sorted(atual - self.no_alcance):
            self._registrar(f"{nomes[epc]} entrou no alcance da {antenas[porta]}")
        for epc, porta in sorted(self.no_alcance - atual):
            if epc in nomes:
                self._registrar(f"{nomes[epc]} saiu do alcance da {antenas[porta]}")
        self.no_alcance = atual
        lidos = {epc for epc, _ in atual}
        for epc, (_, bolinha) in self.visuais.items():
            bolinha.bgcolor = COR_ITEM_LIDO if epc in lidos else COR_ITEM

    def _atualizar_estado(self) -> None:
        """Atualiza estado."""
        publicador = self.envio.publicador
        if self.envio.erro:
            self.estado.value = f"Erro no MQTT: {self.envio.erro}"
            self.estado.color = ft.Colors.RED_700
        elif not self.envio.conectado:
            self.estado.value = "Conectando ao broker..."
            self.estado.color = "#4b5d63"
        else:
            self.estado.value = (
                f"Conectado · {publicador.publicadas} leituras publicadas "
                f"({publicador.pendentes} aguardando PUBACK, "
                f"{self.envio.fila.qsize()} na fila) · "
                f"A: {self.contagem[1]} · B: {self.contagem[2]}")
            self.estado.color = COR_ITEM_LIDO

    def _registrar(self, texto: str) -> None:
        """Acrescenta evento textual ao painel de acompanhamento do simulador."""
        self.log.controls.append(ft.Text(f"{time.strftime('%H:%M:%S')} {texto}", size=11))
        del self.log.controls[:-60]

    def _avisar(self, texto: str, erro: bool = False) -> None:
        """Apresenta mensagem ao operador na interface do simulador."""
        self.mensagem.value = texto
        self.mensagem.color = ft.Colors.RED_700 if erro else "#4b5d63"
        self.page.update()
