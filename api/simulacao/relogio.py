"""Relógio da simulação: um só tempo para motor, leituras, recência e alertas.

O tempo simulado anda ``fator`` vezes mais rápido que o real a partir de uma
âncora (``base_real`` → ``base_sim``) e pode ser **avançado**, nunca recuado:
leituras, passagens e a última detecção já gravadas com o tempo simulado não
podem ficar "no futuro" do relógio, senão a projeção de localização recusaria
as passagens seguintes como antigas.

O relógio fica no JSON ``topologia["relogio"]`` de cada sessão (sem tabela
nova; o banco externo é compartilhado e não migra sozinho). Vale o maior tempo
entre as sessões recentes; mudar fator ou avançar grava em todas as abertas, e
encerrar uma sessão fixa o fator em 1 para o relógio seguir no ritmo real.
O relógio do computador nunca é alterado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import SimulacaoSessao

FATORES = (1, 2, 5, 10, 30, 60)
AVANCO_MAX_S = 24 * 3600
SESSOES_CONSIDERADAS = 20


@dataclass(frozen=True)
class Relogio:
    """Tempo simulado = base_sim + (real − base_real) · fator."""

    fator: float = 1.0
    base_real: datetime | None = None
    base_sim: datetime | None = None

    def agora(self, real: datetime) -> datetime:
        """Instante simulado correspondente ao instante real; nunca antes do real."""
        if self.base_real is None or self.base_sim is None:
            return real
        return max(real, self.base_sim + (real - self.base_real) * self.fator)

    def com(self, real: datetime, *, fator: float | None = None, avancar_s: float = 0) -> Relogio:
        """Reancora no instante atual com outro fator e/ou um avanço (só para frente)."""
        return Relogio(self.fator if fator is None else float(fator), real,
                       self.agora(real) + timedelta(seconds=max(0.0, avancar_s)))

    def para_dict(self) -> dict:
        """Formato guardado no JSON da sessão."""
        return {"fator": self.fator,
                "base_real": self.base_real.isoformat() if self.base_real else None,
                "base_sim": self.base_sim.isoformat() if self.base_sim else None}

    @classmethod
    def de_dict(cls, dados: dict | None) -> Relogio:
        """Lê o JSON da sessão; ausente ou inválido = tempo real."""
        if not dados:
            return cls()
        try:
            return cls(float(dados.get("fator") or 1),
                       datetime.fromisoformat(dados["base_real"]) if dados.get("base_real") else None,
                       datetime.fromisoformat(dados["base_sim"]) if dados.get("base_sim") else None)
        except (TypeError, ValueError):
            return cls()


def real_agora() -> datetime:
    """Relógio do computador, em UTC."""
    return datetime.now(UTC)


def do_banco(db: Session, real: datetime | None = None) -> Relogio:
    """Relógio vigente: fator das sessões abertas, tempo da mais adiantada.

    Devolve um relógio ancorado agora, de modo que ``agora(real)`` seja o maior
    tempo simulado entre as sessões recentes (abertas ou não).
    """
    real = real or real_agora()
    linhas = db.execute(select(SimulacaoSessao.estado, SimulacaoSessao.topologia)
                        .order_by(SimulacaoSessao.id.desc()).limit(SESSOES_CONSIDERADAS)).all()
    instante, fator = real, 1.0
    for estado, topo in linhas:
        relogio = Relogio.de_dict((topo or {}).get("relogio"))
        instante = max(instante, relogio.agora(real))
        if estado != "encerrada" and relogio.fator > fator:
            fator = relogio.fator
    return Relogio(fator, real, instante)


def gravar(sessao: SimulacaoSessao, relogio: Relogio) -> None:
    """Guarda o relógio no JSON da sessão (reatribui para o ORM ver a mudança)."""
    sessao.topologia = {**(sessao.topologia or {}), "relogio": relogio.para_dict()}


def resumo(relogio: Relogio, real: datetime | None = None) -> dict:
    """O que as telas precisam para mostrar o mesmo tempo."""
    real = real or real_agora()
    agora = relogio.agora(real)
    return {"agora": agora.isoformat(), "real": real.isoformat(), "fator": relogio.fator,
            "adiantado_s": round((agora - real).total_seconds(), 3),
            "acelerado": relogio.fator != 1 or agora - real > timedelta(seconds=1),
            "fatores": list(FATORES)}
