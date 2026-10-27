"""Limpeza segura dos dados experimentais do banco (pré-visualização por padrão).

Uso (na raiz do repositório):

    python -m tools.limpeza_banco previa   --env-file config/environments/.env.local
    python -m tools.limpeza_banco executar --env-file config/environments/.env.local \\
        --confirmar rfid_hospital_dev
    python -m tools.limpeza_banco verificar --env-file config/environments/.env.local

O que é PRESERVADO sempre: usuários, perfis, sessões de login, auditoria
(append-only), migrations, tipos de equipamento em uso, zonas/portais/leitores
físicos e o cadastro do laboratório EASY. Nenhuma tabela é apagada.

Escopos removíveis (padrão: todos):
- `telemetria`: leituras brutas, passagens, histórico de movimentações e a
  projeção de última zona; o último contato dos leitores volta a "nunca
  conectado". Sem isso não há como apagar o resto sem violar as FKs.
- `simulacao`: sessões do simulador web, leitores virtuais (`SIM-*`), suas
  antenas/mapeamentos e a topologia do andar "Simulação HUPAA". Layouts são
  configurações: ficam, salvo `--incluir-layouts`.
- `laboratorio`: equipamentos criados pelo launcher (`LAB-RFID-*` ou tipos de
  laboratório), seus vínculos e as tags que ficarem sem vínculo algum.

Equipamentos cadastrados pelo dashboard NÃO são classificados como teste
automaticamente: só saem com `--incluir-equipamento ID` explícito.

Travas: `APP_ENV=production` recusa execução; banco fora de localhost exige
`--permitir-banco-remoto`; executar exige `--confirmar <nome do banco>`.
Tudo roda em UMA transação: falhou, nada muda.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from api.ambiente import ambiente_atual

ESCOPOS = ("telemetria", "simulacao", "laboratorio")
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1", "postgres", None, ""}
TIPOS_LABORATORIO = ("Equipamento sintético de laboratório RFID",
                     "Equipamento físico de laboratório RFID")
ANDAR_SIMULACAO = "Simulação HUPAA"


class LimpezaRecusada(RuntimeError):
    """A trava de segurança impediu a execução."""


@dataclass(frozen=True)
class Etapa:
    """Uma operação da limpeza: contagem (prévia) e comando (execução)."""

    escopo: str
    descricao: str
    contagem: str
    comando: str


# Conjuntos reutilizados nas consultas (CTEs textuais, sem parâmetros do usuário).
_LEITORES_SIM = "SELECT id FROM leitores WHERE identificador_serial LIKE 'SIM-%'"
_ANTENAS_SIM = f"SELECT id FROM antenas WHERE leitor_id IN ({_LEITORES_SIM})"
_ZONAS_SIM = ("SELECT z.id FROM zonas z JOIN setores s ON s.id = z.setor_id "
              "JOIN andares a ON a.id = s.andar_id WHERE a.nome = '" + ANDAR_SIMULACAO + "'")
_EQUIP_LAB = ("SELECT e.id FROM equipamentos e JOIN tipos_equipamento t ON t.id = e.tipo_id "
              "WHERE e.identificador_interno LIKE 'LAB-RFID-%' OR t.nome IN ("
              + ", ".join(f"'{nome}'" for nome in TIPOS_LABORATORIO) + ")")


def _equip_alvo(extras: Sequence[int], laboratorio: bool) -> str:
    """Equipamentos removíveis: laboratório e/ou ids explícitos (inteiros validados)."""
    partes = []
    if laboratorio:
        partes.append(_EQUIP_LAB)
    if extras:
        partes.append("SELECT id FROM equipamentos WHERE id IN ("
                      + ", ".join(str(int(item)) for item in extras) + ")")
    return " UNION ".join(partes) if partes else "SELECT NULL::bigint WHERE false"


def planejar(escopos: Sequence[str], *, incluir_layouts: bool = False,
             equipamentos: Sequence[int] = ()) -> list[Etapa]:
    """Etapas na ordem que respeita as FKs (filhos antes dos pais)."""
    escopos = tuple(escopos)
    desconhecidos = set(escopos) - set(ESCOPOS)
    if desconhecidos:
        raise ValueError(f"escopo desconhecido: {', '.join(sorted(desconhecidos))}")
    if ("simulacao" in escopos or "laboratorio" in escopos or equipamentos) \
            and "telemetria" not in escopos:
        raise ValueError("remover simulação ou equipamentos exige o escopo telemetria "
                         "(leituras e histórico os referenciam)")
    etapas: list[Etapa] = []
    if "telemetria" in escopos:
        etapas += [
            Etapa("telemetria", "Projeção de última zona dos equipamentos (zerada, não apagada)",
                  "SELECT count(*) FROM equipamentos WHERE ultima_zona_id IS NOT NULL "
                  "OR ultima_passagem_id IS NOT NULL OR ultima_movimentacao_id IS NOT NULL "
                  "OR ultima_deteccao_em IS NOT NULL",
                  "UPDATE equipamentos SET ultima_zona_id = NULL, ultima_deteccao_em = NULL, "
                  "ultima_passagem_id = NULL, ultima_movimentacao_id = NULL, versao = versao + 1 "
                  "WHERE ultima_zona_id IS NOT NULL OR ultima_passagem_id IS NOT NULL "
                  "OR ultima_movimentacao_id IS NOT NULL OR ultima_deteccao_em IS NOT NULL"),
            Etapa("telemetria", "Histórico de movimentações",
                  "SELECT count(*) FROM historico_movimentacoes",
                  "DELETE FROM historico_movimentacoes"),
            Etapa("telemetria", "Passagens", "SELECT count(*) FROM passagens",
                  "DELETE FROM passagens"),
            Etapa("telemetria", "Leituras brutas", "SELECT count(*) FROM leituras_brutas",
                  "DELETE FROM leituras_brutas"),
            Etapa("telemetria", "Contato observado dos leitores (volta a 'nunca conectado')",
                  "SELECT count(*) FROM leitores WHERE ultimo_contato_em IS NOT NULL "
                  "OR ultimo_heartbeat_em IS NOT NULL",
                  "UPDATE leitores SET ultimo_contato_em = NULL, ultimo_heartbeat_em = NULL, "
                  "origem_ultimo_contato = NULL, saude_reportada = NULL, "
                  "status = 'nunca_conectado' WHERE ultimo_contato_em IS NOT NULL "
                  "OR ultimo_heartbeat_em IS NOT NULL"),
        ]
    if "simulacao" in escopos:
        etapas += [
            Etapa("simulacao", "Sessões do simulador web",
                  "SELECT count(*) FROM simulacao_sessoes", "DELETE FROM simulacao_sessoes"),
            Etapa("simulacao", "Mapeamentos de antenas virtuais e da topologia simulada",
                  f"SELECT count(*) FROM mapeamentos_antena_portal WHERE antena_id IN "
                  f"({_ANTENAS_SIM}) OR zona_id IN ({_ZONAS_SIM})",
                  f"DELETE FROM mapeamentos_antena_portal WHERE antena_id IN ({_ANTENAS_SIM}) "
                  f"OR zona_id IN ({_ZONAS_SIM})"),
            Etapa("simulacao", "Antenas dos leitores virtuais (SIM-*)",
                  f"SELECT count(*) FROM antenas WHERE leitor_id IN ({_LEITORES_SIM})",
                  f"DELETE FROM antenas WHERE leitor_id IN ({_LEITORES_SIM})"),
            Etapa("simulacao", "Leitores virtuais (serial SIM-*)",
                  f"SELECT count(*) FROM ({_LEITORES_SIM}) x", f"DELETE FROM leitores WHERE id IN ({_LEITORES_SIM})"),
            Etapa("simulacao", f"Portais do andar '{ANDAR_SIMULACAO}' sem antenas físicas",
                  f"SELECT count(*) FROM portais p WHERE (p.zona_a_id IN ({_ZONAS_SIM}) OR "
                  f"p.zona_b_id IN ({_ZONAS_SIM})) AND NOT EXISTS (SELECT 1 FROM antenas a "
                  "WHERE a.portal_id = p.id)",
                  f"DELETE FROM portais p WHERE (p.zona_a_id IN ({_ZONAS_SIM}) OR "
                  f"p.zona_b_id IN ({_ZONAS_SIM})) AND NOT EXISTS (SELECT 1 FROM antenas a "
                  "WHERE a.portal_id = p.id)"),
            Etapa("simulacao", f"Zonas, setores e andar '{ANDAR_SIMULACAO}' sem referências",
                  f"SELECT count(*) FROM ({_ZONAS_SIM}) z WHERE NOT EXISTS (SELECT 1 FROM "
                  "portais p WHERE p.zona_a_id = z.id OR p.zona_b_id = z.id) AND NOT EXISTS "
                  "(SELECT 1 FROM antenas a WHERE a.zona_associada_id = z.id)",
                  f"DELETE FROM zonas WHERE id IN ({_ZONAS_SIM}) AND NOT EXISTS (SELECT 1 FROM "
                  "portais p WHERE p.zona_a_id = zonas.id OR p.zona_b_id = zonas.id) AND NOT EXISTS "
                  "(SELECT 1 FROM antenas a WHERE a.zona_associada_id = zonas.id); "
                  "DELETE FROM setores s USING andares a WHERE a.id = s.andar_id AND a.nome = '"
                  + ANDAR_SIMULACAO + "' AND NOT EXISTS (SELECT 1 FROM zonas z WHERE z.setor_id = s.id); "
                  "DELETE FROM andares a WHERE a.nome = '" + ANDAR_SIMULACAO + "' AND NOT EXISTS "
                  "(SELECT 1 FROM setores s WHERE s.andar_id = a.id)"),
            Etapa("simulacao", "Vínculos de topologia dos layouts (recriados ao iniciar)",
                  "SELECT count(*) FROM simulacao_layouts WHERE vinculos IS NOT NULL",
                  "UPDATE simulacao_layouts SET vinculos = NULL, aplicado_em = NULL "
                  "WHERE vinculos IS NOT NULL"),
        ]
        if incluir_layouts:
            etapas.append(Etapa("simulacao", "Layouts do simulador (configurações salvas)",
                                "SELECT count(*) FROM simulacao_layouts",
                                "DELETE FROM simulacao_layouts"))
    alvo = _equip_alvo(equipamentos, "laboratorio" in escopos)
    if "laboratorio" in escopos or equipamentos:
        etapas += [
            Etapa("laboratorio", "Vínculos de tag dos equipamentos de teste",
                  f"SELECT count(*) FROM associacoes_tag_equipamento WHERE equipamento_id IN ({alvo})",
                  f"DELETE FROM associacoes_tag_equipamento WHERE equipamento_id IN ({alvo})"),
            Etapa("laboratorio", "Equipamentos de teste",
                  f"SELECT count(*) FROM ({alvo}) x",
                  f"DELETE FROM equipamentos WHERE id IN ({alvo})"),
            Etapa("laboratorio", "Tags sem nenhum vínculo (nem histórico)",
                  "SELECT count(*) FROM tags t WHERE NOT EXISTS (SELECT 1 FROM "
                  "associacoes_tag_equipamento a WHERE a.tag_id = t.id)",
                  "DELETE FROM tags t WHERE NOT EXISTS (SELECT 1 FROM "
                  "associacoes_tag_equipamento a WHERE a.tag_id = t.id)"),
            Etapa("laboratorio", "Tipos de laboratório sem equipamentos",
                  "SELECT count(*) FROM tipos_equipamento t WHERE t.nome IN ("
                  + ", ".join(f"'{nome}'" for nome in TIPOS_LABORATORIO) + ") AND NOT EXISTS "
                  "(SELECT 1 FROM equipamentos e WHERE e.tipo_id = t.id)",
                  "DELETE FROM tipos_equipamento t WHERE t.nome IN ("
                  + ", ".join(f"'{nome}'" for nome in TIPOS_LABORATORIO) + ") AND NOT EXISTS "
                  "(SELECT 1 FROM equipamentos e WHERE e.tipo_id = t.id)"),
        ]
    return etapas


PRESERVADAS = ("usuarios", "perfis", "sessoes", "auditorias", "alembic_version")


def contagens_preservadas(conexao: Connection) -> dict[str, int]:
    """Totais das tabelas que a limpeza nunca toca (comparados antes/depois)."""
    return {tabela: conexao.scalar(text(f"SELECT count(*) FROM {tabela}"))
            for tabela in PRESERVADAS}


def previa(conexao: Connection, etapas: list[Etapa]) -> list[tuple[Etapa, int]]:
    """Quantos registros cada etapa afetaria, sem alterar nada (transação somente leitura)."""
    conexao.execute(text("SET TRANSACTION READ ONLY"))
    return [(etapa, conexao.scalar(text(etapa.contagem))) for etapa in etapas]


def executar(conexao: Connection, etapas: list[Etapa]) -> list[tuple[Etapa, int]]:
    """Executa as etapas na transação do chamador e registra a limpeza na auditoria."""
    antes = contagens_preservadas(conexao)
    resultado = []
    for etapa in etapas:
        total = 0
        for comando in etapa.comando.split("; "):
            total += conexao.execute(text(comando)).rowcount or 0
        resultado.append((etapa, total))
    depois = contagens_preservadas(conexao)
    for tabela in ("usuarios", "perfis", "auditorias"):
        if depois[tabela] != antes[tabela]:
            raise LimpezaRecusada(f"a limpeza alteraria {tabela}; nada foi aplicado")
    conexao.execute(text(
        "INSERT INTO auditorias (origem, entidade, acao, motivo, dados_depois) "
        "VALUES ('sistema', 'limpeza_banco', 'excluir', :motivo, CAST(:dados AS jsonb))"),
        {"motivo": "Limpeza de dados experimentais (tools.limpeza_banco)",
         "dados": json.dumps({etapa.descricao: total for etapa, total in resultado},
                             ensure_ascii=False)})
    return resultado


def verificar(conexao: Connection) -> list[tuple[str, bool, str]]:
    """Checagens de integridade e de preservação de acesso após a limpeza."""
    checks = []

    def check(nome: str, sql: str, esperado) -> None:
        """Executa a consulta e compara com o valor (ou predicado) esperado."""
        valor = conexao.scalar(text(sql))
        checks.append((nome, valor == esperado if not callable(esperado) else esperado(valor),
                       str(valor)))

    check("Perfis operacional e administrador presentes",
          "SELECT count(*) FROM perfis WHERE nome IN ('operacional', 'administrador')", 2)
    check("Ao menos um administrador ativo",
          "SELECT count(*) FROM usuarios u JOIN perfis p ON p.id = u.perfil_id "
          "WHERE p.nome = 'administrador' AND u.ativo", lambda valor: valor >= 1)
    check("Senhas de usuários ativos em Argon2id",
          "SELECT count(*) FROM usuarios WHERE ativo AND senha_hash NOT LIKE '$argon2id$%'", 0)
    check("Trigger de auditoria append-only ativo",
          "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
          "WHERE t.tgname = 'tg_auditorias_append_only' AND NOT t.tgisinternal "
          "AND c.relnamespace = to_regnamespace(current_schema())", 1)
    check("Equipamentos sem zona/passagem órfã",
          "SELECT count(*) FROM equipamentos e WHERE (e.ultima_passagem_id IS NOT NULL AND NOT "
          "EXISTS (SELECT 1 FROM passagens p WHERE p.id = e.ultima_passagem_id))", 0)
    check("No máximo um vínculo ativo por tag",
          "SELECT count(*) FROM (SELECT tag_id FROM associacoes_tag_equipamento WHERE fim IS NULL "
          "GROUP BY tag_id HAVING count(*) > 1) x", 0)
    check("Antenas ativas apontam para leitores existentes",
          "SELECT count(*) FROM antenas a WHERE NOT EXISTS (SELECT 1 FROM leitores l "
          "WHERE l.id = a.leitor_id)", 0)
    check("Constraints de chave estrangeira validadas",
          "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND NOT convalidated "
          "AND connamespace = to_regnamespace(current_schema())", 0)
    return checks


def _destino(url: str) -> tuple[str, str | None, str | None]:
    """Descrição sem credenciais, host e nome do banco."""
    parsed = make_url(url)
    return parsed.render_as_string(hide_password=True), parsed.host, parsed.database


def main(argv: Sequence[str] | None = None) -> int:
    """Entrada de linha de comando: previa (padrão), executar ou verificar."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acao", nargs="?", default="previa", choices=("previa", "executar", "verificar"))
    parser.add_argument("--env-file", type=Path, help="perfil com DATABASE_URL (não sobrescreve o ambiente)")
    parser.add_argument("--escopo", action="append", choices=ESCOPOS,
                        help="repita para combinar; padrão: todos")
    parser.add_argument("--incluir-layouts", action="store_true")
    parser.add_argument("--incluir-equipamento", action="append", type=int, default=[],
                        metavar="ID", help="equipamento cadastrado a remover explicitamente")
    parser.add_argument("--confirmar", metavar="NOME_DO_BANCO",
                        help="obrigatório para executar: o nome exato do banco de destino")
    parser.add_argument("--permitir-banco-remoto", action="store_true",
                        help="aceita banco fora de localhost (nunca em APP_ENV=production)")
    args = parser.parse_args(argv)
    for fluxo in (sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    if args.env_file:
        if not args.env_file.is_file():
            parser.error(f"arquivo de ambiente ausente: {args.env_file}")
        load_dotenv(args.env_file, override=False)
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL ausente (use --env-file)")
    ambiente = ambiente_atual()
    descricao, host, banco = _destino(url)
    print(f"Ambiente (APP_ENV): {ambiente}\nBanco de destino: {descricao}")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        if args.acao == "verificar":
            with engine.connect() as conexao:
                checks = verificar(conexao)
                for tabela, total in contagens_preservadas(conexao).items():
                    print(f"  {tabela}: {total}")
            for nome, ok, valor in checks:
                print(f"[{'OK' if ok else 'FALHA'}] {nome} ({valor})")
            return 0 if all(ok for _, ok, _ in checks) else 1

        etapas = planejar(args.escopo or ESCOPOS, incluir_layouts=args.incluir_layouts,
                          equipamentos=args.incluir_equipamento)
        if args.acao == "previa":
            with engine.connect() as conexao, conexao.begin():
                versao = conexao.scalar(text("SELECT version_num FROM alembic_version"))
                print(f"Migration atual: {versao}\nPRÉ-VISUALIZAÇÃO (nada será alterado):")
                for etapa, total in previa(conexao, etapas):
                    print(f"  [{etapa.escopo}] {etapa.descricao}: {total}")
                print("Preservados: " + ", ".join(f"{k}={v}" for k, v in
                                                  contagens_preservadas(conexao).items()))
            print(f"\nPara aplicar: python -m tools.limpeza_banco executar --confirmar {banco} "
                  "(mesmos escopos). Faça backup antes (docs/operations/limpeza-banco.md).")
            return 0

        if ambiente == "production":
            raise LimpezaRecusada("APP_ENV=production: a limpeza é bloqueada em produção")
        if host not in HOSTS_LOCAIS and not args.permitir_banco_remoto:
            raise LimpezaRecusada(f"o banco {host!r} não é local; use --permitir-banco-remoto "
                                  "somente em um banco descartável de demonstração")
        if args.confirmar != banco:
            raise LimpezaRecusada(f"confirme digitando o nome do banco: --confirmar {banco}")
        with engine.begin() as conexao:
            conexao.execute(text("SET LOCAL lock_timeout = '10s'"))
            resultado = executar(conexao, etapas)
        for etapa, total in resultado:
            print(f"  [{etapa.escopo}] {etapa.descricao}: {total}")
        print("Limpeza concluída e registrada na auditoria. Rode 'verificar' em seguida.")
        return 0
    except (LimpezaRecusada, ValueError) as erro:
        print(f"RECUSADO: {erro}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
